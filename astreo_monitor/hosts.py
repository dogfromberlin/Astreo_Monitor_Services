"""Server collegati (4.0): il centrale è l'host 1, gli altri inviano i dati con un agente.

Ogni agente ha un token (nel database solo il suo sha256) e può solo scrivere i propri dati:
metriche, temperature, stato dei servizi e riavvii. Riceve in risposta l'elenco dei servizi da
controllare per sé, nient'altro.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import secrets

from sqlalchemy import delete, func, select, update

from . import db, events, models

LOCAL_ID = 1
KINDS = ("linux", "windows")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,63}$")
MAX_ITEMS = 500
H = models.hosts


class HostError(ValueError):
    """Dati non validi (messaggio per l'utente o per l'agente)."""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return "agt_" + secrets.token_urlsafe(32)


def clean_services(text: str) -> str:
    units = [u.strip() for u in re.split(r"[,\n]", text or "") if u.strip()]
    for u in units:
        if not re.match(r"^[A-Za-z0-9@._:\-\\$ ]{1,120}$", u):
            raise HostError(f"Nome di servizio non valido: {u}")
    if len(units) > 60:
        raise HostError("Al massimo 60 servizi per server")
    return ",".join(dict.fromkeys(units))


# ----------------------------------------------------------------------------- 4.2: impostazioni per server
LIMIT_KEYS = ("disk_warning", "disk_alert", "temp_warning", "temp_alert", "cpu_warning", "cpu_alert", "mem_warning", "mem_alert")
LIMIT_RANGE = {"disk_warning": (1, 100), "disk_alert": (1, 100), "temp_warning": (20, 120), "temp_alert": (20, 120),
               "cpu_warning": (10, 100), "cpu_alert": (10, 100), "mem_warning": (10, 100), "mem_alert": (10, 100)}
LOAD_DEFAULTS = {"cpu_warning": 90.0, "cpu_alert": 98.0, "mem_warning": 90.0, "mem_alert": 97.0}


def limits(h: dict, cfg, values: dict | None = None) -> dict:
    """Soglie effettive di un server: le sue, oppure quelle generali dove sono vuote.

    Disco e temperatura generali vengono da config.ini; CPU e memoria dalle impostazioni della dashboard (values).
    """
    m = cfg.metrics
    v = values or {}
    general = {"disk_warning": m.disk_warning, "disk_alert": m.disk_alert, "temp_warning": m.temp_warning, "temp_alert": m.temp_alert,
               **{k: float(v.get(f"load.{k}", d)) for k, d in LOAD_DEFAULTS.items()}}
    return {k: (h.get(k) if h.get(k) is not None else general[k]) for k in LIMIT_KEYS}


def local_limits(conn, cfg, values: dict | None = None) -> dict:
    row = db.rows(conn, select(*[H.c[k] for k in LIMIT_KEYS]).where(H.c.id == LOCAL_ID))
    return limits(row[0] if row else {}, cfg, values)


def clean_settings(data: dict, hid: int) -> dict:
    """Valida le impostazioni per server ricevute dalla dashboard (valori vuoti = impostazione generale)."""
    out = {}
    for k in LIMIT_KEYS:
        if k in data:
            v = data[k]
            if v in (None, ""):
                out[k] = None
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise HostError(f"Valore non valido: {k}") from None
            lo, hi = LIMIT_RANGE[k]
            if not lo <= f <= hi:
                raise HostError(f"{k}: valore tra {lo} e {hi}")
            out[k] = f
    for w, a in (("disk_warning", "disk_alert"), ("temp_warning", "temp_alert"), ("cpu_warning", "cpu_alert"), ("mem_warning", "mem_alert")):
        if out.get(w) is not None and out.get(a) is not None and out[w] >= out[a]:
            raise HostError("La soglia di avviso deve essere più bassa di quella di allarme")
    if hid != LOCAL_ID:                                     # il centrale è sempre raggiungibile da sé stesso
        for k in ("notify_offline", "allow_commands", "allow_update"):
            if k in data:
                out[k] = bool(data[k])
        if "services_ondemand" in data:                     # 4.3: servizi discontinui (elenco o testo con virgole)
            v = data["services_ondemand"]
            lst = v if isinstance(v, list) else str(v or "").split(",")
            lst = [str(u).strip() for u in lst if str(u).strip()]
            if len(lst) > 60 or not all(len(u) <= 200 and "," not in u for u in lst):
                raise HostError("Servizi discontinui non validi")
            out["services_ondemand"] = ",".join(dict.fromkeys(lst)) or None
        if "offline_minutes" in data:
            v = data["offline_minutes"]
            if v in (None, ""):
                out["offline_minutes"] = None
            else:
                try:
                    n = int(v)
                except (TypeError, ValueError):
                    raise HostError("Minuti non validi") from None
                if not 2 <= n <= 1440:
                    raise HostError("Minuti: tra 2 e 1440")
                out["offline_minutes"] = n
    return out


def only_configured(state: dict | None, services: str | None) -> dict | None:
    """4.1: dello stato inviato dall'agente si tengono solo i servizi ancora da controllare.

    L'agente riceve il nuovo elenco solo alla risposta del suo invio successivo: senza questo filtro un servizio
    appena tolto resterebbe visibile (e negli avvisi) per uno o due cicli. Il server centrale non ne ha bisogno.
    """
    if not state or services is None:
        return state
    keep = {u.strip().lower() for u in services.split(",") if u.strip()}
    return {**state, "services": [s for s in state.get("services", []) if str(s.get("unit", "")).lower() in keep]}


UNSEEN_MINUTES = 5          # 4.3: dopo, un servizio aggiunto e mai visto dall'agente è "non rilevato"
PROTECTED_WINDOWS = {"mpssvc", "windefend", "wscsvc", "securityhealthservice", "wdnissvc", "sense"}


def units(text: str | None) -> list[str]:
    return [u.strip() for u in (text or "").split(",") if u.strip()]


def with_expected(conn, h: dict, now: dt.datetime) -> dict:
    """4.3: lo stato dei servizi come lo mostra la dashboard.

    - ogni servizio porta ondemand (discontinuo: fermo non è un guasto);
    - un servizio configurato ma non ancora nello stato inviato dall'agente compare "in attesa del primo
      controllo" (pending), e dopo UNSEEN_MINUTES "non rilevato" (unseen);
    - "not-found" dall'agente diventa "inesistente su questo server" (missing).
    """
    state = h.get("services_state") or {"services": []}
    conf = units(h.get("services"))
    od = {u.lower() for u in units(h.get("services_ondemand"))}
    added = db.state_get(conn, f"host:{h['id']}:services_added") or {}
    seen = {}
    for s in state.get("services", []):
        s = dict(s)
        s["ondemand"] = s["unit"].lower() in od
        s["protected"] = h.get("kind") == "windows" and s["unit"].lower() in PROTECTED_WINDOWS
        if s.get("state") in ("not-found", "not found", "missing"):
            s["status"] = "missing"
        elif s.get("up"):
            s["status"] = "up"
        else:
            s["status"] = "rest" if s["ondemand"] else "down"
        seen[s["unit"].lower()] = s
    out = []
    for u in conf:
        s = seen.get(u.lower())
        if s is None:
            since = added.get(u) or state.get("time")
            old = since and (now - dt.datetime.fromisoformat(str(since)[:19])).total_seconds() > UNSEEN_MINUTES * 60
            s = {"unit": u, "label": u, "up": None, "state": "unseen" if old else "pending",
                 "status": "unseen" if old else "pending", "ondemand": u.lower() in od,
                 "protected": h.get("kind") == "windows" and u.lower() in PROTECTED_WINDOWS}
        out.append(s)
    return {**state, "services": out}


def prune_services(conn, hid: int) -> None:
    """Toglie subito dallo stato salvato i servizi non più controllati (dopo una modifica dell'elenco)."""
    services = db.scalar(conn, select(H.c.services).where(H.c.id == hid))
    key = f"host:{hid}:services"
    state = db.state_get(conn, key)
    if state:
        db.state_set(conn, key, only_configured(state, services or ""))
    # 4.3: quando è stato aggiunto ogni servizio (per "in attesa" / "non rilevato") e richiesta di controllo immediato
    added = db.state_get(conn, f"host:{hid}:services_added") or {}
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    added = {u: added.get(u) or now_iso for u in units(services)}
    db.state_set(conn, f"host:{hid}:services_added", added)
    request_refresh(conn, hid)


def request_refresh(conn, hid: int) -> None:
    """4.3: chiede all'agente di ricontrollare e rimandare subito lo stato dei servizi (richiesta innocua)."""
    db.state_set(conn, f"host:{hid}:refresh", {"time": dt.datetime.now().isoformat(timespec="seconds")})


def create(conn, name: str, kind: str, services: str = "") -> tuple[int, str]:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise HostError("Nome non valido: lettere, numeri, spazi, punto, trattino (massimo 64)")
    if kind not in KINDS:
        raise HostError("Sistema non valido: linux o windows")
    if db.scalar(conn, select(func.count()).select_from(H).where(func.lower(H.c.name) == name.lower())):
        raise HostError(f"Esiste già un server chiamato {name}")
    token = new_token()
    top = db.scalar(conn, select(func.coalesce(func.max(H.c.sort_order), 0))) or 0
    hid = conn.execute(H.insert().values(name=name, kind=kind, token_hash=token_hash(token), services=clean_services(services),
                                         enabled=True, sort_order=top + 10, created_at=db.now())).inserted_primary_key[0]
    return int(hid), token


def regenerate(conn, hid: int) -> str:
    token = new_token()
    if hid == LOCAL_ID or not conn.execute(update(H).where(H.c.id == hid).values(token_hash=token_hash(token), enabled=True)).rowcount:
        raise HostError("Server inesistente")
    return token


def by_token(conn, token: str) -> dict | None:
    if not token or len(token) > 200:
        return None
    return db.one(conn, select(H).where(H.c.token_hash == token_hash(token), H.c.enabled == models_true(), H.c.id != LOCAL_ID))


def models_true():
    from sqlalchemy import true
    return true()


def remove(conn, hid: int) -> None:
    if hid == LOCAL_ID:
        raise HostError("Il server centrale non si può eliminare")
    for t in (models.system_metrics, models.system_temperature, models.events):
        conn.execute(delete(t).where(t.c.host_id == hid))
    S = models.monitor_state
    conn.execute(delete(S).where(S.c.key.like(f"host:{hid}:%") | S.c.key.like(f"alert:host:{hid}:%")))
    if not conn.execute(delete(H).where(H.c.id == hid)).rowcount:
        raise HostError("Server inesistente")


def listing(conn, offline_minutes: int) -> list[dict]:
    now = dt.datetime.now()
    out = []
    for h in db.rows(conn, select(H).order_by(H.c.sort_order, H.c.id)):
        h = {k: v for k, v in h.items() if k != "token_hash"}
        if h["id"] == LOCAL_ID:
            h["status"] = "OK"
        else:
            seen = db.as_datetime(h["last_seen"]) if h["last_seen"] else None
            mins = h.get("offline_minutes") or offline_minutes            # 4.2: minuti per server
            h["status"] = ("DISABLED" if not h["enabled"] else "WAITING" if not seen
                           else "DOWN" if (now - seen).total_seconds() > mins * 60 else "OK")
        h["snapshot"] = db.state_get(conn, f"host:{h['id']}:snapshot")
        h["services_state"] = only_configured(db.state_get(conn, f"host:{h['id']}:services"), h.get("services"))
        if h["id"] != LOCAL_ID:
            h["services_state"] = with_expected(conn, h, now)                 # 4.3: discontinui e in attesa
        if h["id"] != LOCAL_ID:                                    # 4.2: dati di salute e Docker degli agenti
            h["health"] = db.state_get(conn, f"host:{h['id']}:health")
            h["containers"] = db.state_get(conn, f"host:{h['id']}:containers")
        for k in ("created_at", "last_seen"):
            h[k] = db.as_datetime(h[k]).isoformat(timespec="seconds") if h[k] else None
        out.append(h)
    return out


# ----------------------------------------------------------------------------- ricezione
def _num(v, lo: float, hi: float):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HostError("valore numerico non valido") from None
    if math.isnan(f) or not lo <= f <= hi:
        raise HostError("valore fuori intervallo")
    return f


def _time(v, now: dt.datetime, max_age_days: int = 2) -> dt.datetime:
    try:
        t = dt.datetime.fromisoformat(str(v)[:19])
    except ValueError:
        raise HostError("ora non valida") from None
    if t > now + dt.timedelta(minutes=10) or t < now - dt.timedelta(days=max_age_days):
        raise HostError("ora fuori intervallo (orologio dell'agente da controllare)")
    return t.replace(microsecond=0)


def _txt(v, n: int) -> str:
    return str(v or "")[:n]


def _disks(v) -> list[dict]:
    """4.0.1: tutti i dischi fissi dell'agente (Linux: punti di montaggio, Windows: unità)."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 32:
        raise HostError("dischi non validi")
    out = []
    for d in v:
        if not isinstance(d, dict):
            raise HostError("disco non valido")
        out.append({"mountpoint": _txt(d.get("mountpoint"), 120), "device": _txt(d.get("device"), 120),
                    "fstype": _txt(d.get("fstype"), 20), "label": _txt(d.get("label"), 60),
                    "total_mb": _num(d.get("total_mb"), 0, 1e12), "used_mb": _num(d.get("used_mb"), 0, 1e12),
                    "free_mb": _num(d.get("free_mb"), 0, 1e12), "used_pct": _num(d.get("used_pct"), 0, 100)})
    return out


def ingest(conn, host: dict, payload: dict) -> dict:
    """Registra un pacchetto dell'agente. Ritorna la risposta per l'agente."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise HostError("formato non valido")
    items = payload["items"]
    if len(items) > MAX_ITEMS:
        raise HostError(f"al massimo {MAX_ITEMS} elementi per invio")
    now = dt.datetime.now()
    agent = payload.get("agent") or {}
    metrics, temps, latest, rejected = [], [], None, []
    for it in items:
        try:
            latest = _item(conn, host, it, now, metrics, temps, latest)
        except HostError as exc:                  # si scarta solo l'elemento non valido, non tutto l'invio
            rejected.append(f"{str(it.get('type') if isinstance(it, dict) else '?')[:20]}: {exc}")
    return _finish(conn, host, agent, items, metrics, temps, latest, rejected, now)


def _item(conn, host: dict, it, now: dt.datetime, metrics: list, temps: list, latest: dict | None) -> dict | None:
    hid = host["id"]
    if not isinstance(it, dict):
        raise HostError("elemento non valido")
    kind, t = it.get("type"), _time(it.get("time"), now)
    if kind == "metrics":
        row = {"timestamp": t, "host_id": hid, "source": "agent",
               "cpu_pct": _num(it.get("cpu_pct"), 0, 100), "load1": _num(it.get("load1"), 0, 10000),
               "load5": _num(it.get("load5"), 0, 10000), "load15": _num(it.get("load15"), 0, 10000),
               "mem_used_pct": _num(it.get("mem_used_pct"), 0, 100), "swap_used_pct": _num(it.get("swap_used_pct"), 0, 100),
               "disk_used_pct": _num(it.get("disk_used_pct"), 0, 100)}
        mb = _num(it.get("mem_used_mb"), 0, 1e9)
        row["mem_used_mb"] = int(mb) if mb is not None else None
        metrics.append(row)
        if latest is None or t >= latest["time"]:
            latest = {**{k: v for k, v in row.items() if k not in ("timestamp", "host_id", "source")}, "time": t,
                      "uptime_s": _num(it.get("uptime_s"), 0, 1e10), "mem_total_mb": _num(it.get("mem_total_mb"), 0, 1e9),
                      "disks": _disks(it.get("disks"))}
    elif kind == "temperatures":
        sensors = it.get("sensors") or []
        if not isinstance(sensors, list) or len(sensors) > 64:
            raise HostError("sensori non validi")
        for s in sensors:
            temps.append({"timestamp": t, "host_id": hid, "adapter": _txt(s.get("adapter"), 255),
                          "device": _txt(s.get("device"), 255), "temperature": _num(s.get("value"), -50, 200)})
    elif kind == "services":
        svc = it.get("services") or []
        if not isinstance(svc, list) or len(svc) > 60:
            raise HostError("servizi non validi")
        current = [{"unit": _txt(s.get("unit"), 120), "label": _txt(s.get("label") or s.get("unit"), 100),
                    "up": bool(s.get("up")), "state": _txt(s.get("state"), 40)} for s in svc]
        _services(conn, host, current, t)
    elif kind == "health":                       # 4.2: dischi (SMART / stato Windows) e aggiornamenti, ogni 6 ore
        db.state_set(conn, f"host:{hid}:health", {"time": t.isoformat(timespec="seconds"), **_health(it)})
    elif kind == "containers":                   # 4.2: container Docker del server collegato
        conts = it.get("containers") or []
        if not isinstance(conts, list) or len(conts) > 200:
            raise HostError("container non validi")
        db.state_set(conn, f"host:{hid}:containers", {"time": t.isoformat(timespec="seconds"),
                                                      "running": it.get("running", True) is not False,     # 4.3: Docker fermo
                                                      "detail": _txt(it.get("detail"), 200), "containers": [
            {"name": _txt(c.get("name"), 120), "image": _txt(c.get("image"), 200), "state": _txt(c.get("state"), 20),
             "status": _txt(c.get("status"), 80), "health": _txt(c.get("health"), 20) or None,
             "restart_policy": _txt(c.get("restart_policy"), 20)} for c in conts if isinstance(c, dict)]})
    elif kind == "command_result":               # 4.3: esito di un comando avvia / ferma / riavvia
        _command_result(conn, host, it, t)
    elif kind == "boot":
        bt = _time(it.get("boot_time"), now, max_age_days=30)
        events.record(conn, "boot", "info", "Riavvio del server", "", ref=f"boot:{hid}:{bt.isoformat()}",
                      when=bt, host_id=hid)
    else:
        raise HostError(f"tipo sconosciuto: {_txt(kind, 20)}")
    return latest


def _health(it: dict) -> dict:
    """Normalizza i dati di salute inviati dall'agente (stessi campi di collectors.smart.parse)."""
    disks = []
    for d in (it.get("disks") or [])[:16]:
        if not isinstance(d, dict):
            continue
        n = lambda k, hi: _num(d.get(k), 0, hi)  # noqa: E731
        disks.append({"device": _txt(d.get("device"), 60), "model": _txt(d.get("model"), 120),
                      "passed": d.get("passed") if isinstance(d.get("passed"), bool) else None,
                      "os_health": _txt(d.get("os_health"), 20) or None, "temperature": n("temperature", 150),
                      "wear_used_pct": n("wear_used_pct", 255), "reallocated": int(n("reallocated", 1e9) or 0),
                      "pending": int(n("pending", 1e9) or 0), "uncorrectable": int(n("uncorrectable", 1e9) or 0),
                      "media_errors": int(n("media_errors", 1e12) or 0), "error": _txt(d.get("error"), 200) or None})
    out = {"disks": disks, "smart_available": bool(it.get("smart_available", bool(disks)))}
    u = it.get("updates")
    if isinstance(u, dict):
        sec = [_txt(x, 80) for x in (u.get("security") or [])[:100] if isinstance(x, str)]
        rb = u.get("reboot") or {}
        out["updates"] = {"total": int(_num(u.get("total"), 0, 1e6) or 0), "security": sec,
                          "security_count": int(_num(u.get("security_count"), 0, 1e6) or len(sec)),
                          "reboot": {"required": bool(rb.get("required")) if isinstance(rb, dict) else False},
                          "error": _txt(u.get("error"), 200) or None}
    return out


def _finish(conn, host, agent, items, metrics, temps, latest, rejected, now) -> dict:
    hid = host["id"]
    if metrics:
        conn.execute(models.system_metrics.insert(), metrics)
    if temps:
        conn.execute(models.system_temperature.insert(), temps)
    if latest:
        latest["time"] = latest["time"].isoformat(timespec="seconds")
        latest["temperature_max"] = max((x["temperature"] for x in temps if x["temperature"] is not None), default=None)
        prev = db.state_get(conn, f"host:{hid}:snapshot") or {}
        if latest["temperature_max"] is None:
            latest["temperature_max"] = prev.get("temperature_max")
        db.state_set(conn, f"host:{hid}:snapshot", latest)
    vals = {"last_seen": now.replace(microsecond=0)}
    if agent.get("version"):                  # la prova di collegamento non li invia: non si cancellano
        vals["agent_version"] = _txt(agent["version"], 32)
    if agent.get("os"):
        vals["os_info"] = _txt(agent["os"], 200)
    conn.execute(update(H).where(H.c.id == hid).values(**vals))
    answer = {"ok": True, "accepted": len(items) - len(rejected), "rejected": rejected[:20],
              "services": [u for u in (host.get("services") or "").split(",") if u]}
    if host.get("allow_commands") or host.get("allow_update"):   # 4.3: comandi in attesa per questo agente
        answer["commands"] = pending_commands(conn, hid, now)
    if db.state_get(conn, f"host:{hid}:refresh"):          # 4.3: "Aggiorna" o servizi cambiati
        answer["refresh"] = True
        db.state_set(conn, f"host:{hid}:refresh", None)
    return answer


# ----------------------------------------------------------------------------- 4.3: comandi ai servizi
def _cmd_state(conn, hid: int) -> dict:
    return db.state_get(conn, f"host:{hid}:commands") or {"pending": [], "results": []}


def pending_commands(conn, hid: int, now: dt.datetime) -> list[dict]:
    """Comandi ancora validi; quelli scaduti senza risposta diventano un risultato "scaduto"."""
    st = _cmd_state(conn, hid)
    utc = dt.datetime.now(dt.timezone.utc)
    keep, expired = [], []
    for c in st["pending"]:
        (keep if dt.datetime.fromisoformat(c["expires"]) > utc else expired).append(c)
    if expired:
        for c in expired:
            st["results"].append({**{k: c[k] for k in ("id", "action", "unit", "by")}, "ok": False,
                                  "detail": "nessuna risposta dall'agente: comando scaduto", "time": now.isoformat(timespec="seconds")})
        st["pending"], st["results"] = keep, st["results"][-30:]
        db.state_set(conn, f"host:{hid}:commands", st)
    return [c["signed"] for c in keep]


def queue_command(conn, host: dict, signed: dict, action: str, unit: str, user: str, expires: str) -> None:
    st = _cmd_state(conn, host["id"])
    st["pending"] = [c for c in st["pending"] if c["unit"] != unit][-9:]     # un solo comando per servizio
    st["pending"].append({"id": signed["id"], "action": action, "unit": unit, "by": user, "expires": expires, "signed": signed})
    db.state_set(conn, f"host:{host['id']}:commands", st)


def command_status(conn, hid: int) -> dict:
    st = _cmd_state(conn, hid)
    return {"pending": [{k: c[k] for k in ("id", "action", "unit", "by", "expires")} for c in st["pending"]],
            "results": st["results"][-10:]}


ACTION_LABEL = {"start": "avviato", "stop": "fermato", "restart": "riavviato", "update": "aggiornato"}


def _command_result(conn, host: dict, it: dict, t: dt.datetime) -> None:
    hid = host["id"]
    st = _cmd_state(conn, hid)
    cid = _txt(it.get("id"), 32)
    match = next((c for c in st["pending"] if c["id"] == cid), None)
    if not match:
        return                                          # già registrato (risultato rimandato) o sconosciuto
    ok = bool(it.get("ok"))
    detail = _txt(it.get("detail"), 300)
    if match["action"] == "update" and not ok and detail == "azione non ammessa":
        # agente precedente alla 4.3.0.dev2: conosce i comandi ai servizi ma non l'aggiornamento
        detail = ("questo agente è di una versione che non sa ancora aggiornarsi dalla dashboard: "
                  "reinstallalo una volta a mano con il pacchetto attuale (Nuovo token), poi gli aggiornamenti partono da qui")
    st["pending"] = [c for c in st["pending"] if c["id"] != cid]
    st["results"] = (st["results"] + [{"id": cid, "action": match["action"], "unit": match["unit"], "by": match["by"],
                                       "ok": ok, "detail": detail, "time": t.isoformat(timespec="seconds")}])[-30:]
    db.state_set(conn, f"host:{hid}:commands", st)
    label = next((s.get("label") for s in (db.state_get(conn, f"host:{hid}:services") or {}).get("services", [])
                  if s.get("unit") == match["unit"]), match["unit"])
    if match["action"] == "update":
        events.record(conn, "host", "info" if ok else "warning",
                      (f"Agente aggiornato dalla dashboard ({match['by']})" if ok else f"Aggiornamento dell'agente non riuscito ({match['by']})"),
                      detail, ref=f"cmd:{hid}:{cid}", when=t, host_id=hid)
    elif ok:
        events.record(conn, "service", "info", f"Servizio {label} {ACTION_LABEL[match['action']]} dalla dashboard ({match['by']})",
                      detail, ref=f"cmd:{hid}:{cid}", when=t, host_id=hid)
    else:
        events.record(conn, "service", "warning", f"Comando non riuscito su {label}: {match['action']} ({match['by']})",
                      detail, ref=f"cmd:{hid}:{cid}", when=t, host_id=hid)


def _services(conn, host: dict, current: list[dict], t: dt.datetime) -> None:
    """Stato dei servizi dell'agente; un evento a ogni cambio (fermo / ripartito)."""
    hid = host["id"]
    prev = {s["unit"]: s for s in (db.state_get(conn, f"host:{hid}:services") or {}).get("services", [])}
    od = {u.lower() for u in units(host.get("services_ondemand"))}
    for s in current:
        p = prev.get(s["unit"])
        if p is not None and p["up"] != s["up"] and s.get("state") != "not-found":
            if s["unit"].lower() in od:                    # 4.3: discontinuo, avvio e arresto sono normali
                events.record(conn, "service", "info", f"Servizio {s['label']} {'avviato' if s['up'] else 'fermato'}",
                              s["state"], when=t, host_id=hid)
            else:
                events.record(conn, "service", "info" if s["up"] else "alert",
                              f"Servizio {s['label']} ripartito" if s["up"] else f"Servizio {s['label']} fermo",
                              s["state"], when=t, host_id=hid)
    db.state_set(conn, f"host:{hid}:services", {"time": t.isoformat(timespec="seconds"), "services": current})
