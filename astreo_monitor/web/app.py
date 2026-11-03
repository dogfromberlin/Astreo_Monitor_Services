"""Applicazione Flask: dashboard (/) e API REST (/api/v1/...)."""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import time
from urllib.parse import urlparse

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .. import __version__, db, events, heartbeat, i18n, integrations, models, notifier, schema, services_store
from .. import checks as checks_mod_errors
from ..integrations import docker as docker_mod
from ..integrations import pihole as pihole_mod
from .. import settings as settings_mod
from ..collectors import sensors, services, system, units
from ..config import Config
from . import history
from .netpulse_compat import bp as netpulse_bp
from .terminal import bp as terminal_bp

log = logging.getLogger("web")

RANGES = {"6h": dt.timedelta(hours=6), "24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7),
          "30d": dt.timedelta(days=30), "90d": dt.timedelta(days=90), "365d": dt.timedelta(days=365)}
MAX_SPAN = dt.timedelta(days=400)
# terminal.lock è pubblico: chiude solo la sessione di chi lo chiama (serve alla chiusura della scheda)
PUBLIC_ENDPOINTS = {"api_health", "static", "favicon", "manifest", "terminal.lock", "ca_cert"}
SPEEDTEST_TIMER = "astreo-speedtest.timer"
SPEEDTEST_SERVICE = "astreo-speedtest.service"


def parse_period() -> tuple[dt.datetime, dt.datetime]:
    """Periodo da ?range=6h|24h|7d|30d|90d|365d oppure ?from=...&to=... (ISO 8601)."""
    now = dt.datetime.now().replace(microsecond=0)
    raw_from, raw_to = request.args.get("from"), request.args.get("to")
    if raw_from or raw_to:
        try:
            start = dt.datetime.fromisoformat(raw_from) if raw_from else now - RANGES["24h"]
            end = dt.datetime.fromisoformat(raw_to) if raw_to else now
        except ValueError:
            abort(400, description="Date non valide: usa il formato AAAA-MM-GGTHH:MM")
    else:
        key = request.args.get("range", "24h")
        if key not in RANGES:
            abort(400, description=f"range non valido: valori ammessi {', '.join(RANGES)}")
        start, end = now - RANGES[key], now
    if end <= start:
        abort(400, description="La data di fine deve essere successiva a quella di inizio")
    if end - start > MAX_SPAN:
        abort(400, description="Periodo massimo: 400 giorni")
    return start, end


def body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="Corpo JSON mancante o non valido")
    return data


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__)
    app.config["ASTREO_CFG"] = cfg
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.register_blueprint(netpulse_bp)
    app.register_blueprint(terminal_bp)

    # --- controllo dello schema all'avvio (e poi al massimo ogni 10 minuti)
    schema_state = {"checked": 0.0, "problems": None}

    def schema_problems(force: bool = False):
        # con problemi aperti ricontrolla ogni 30 secondi: appena esegui lo script, il banner sparisce
        ttl = 30 if schema_state["problems"] else 600
        if force or time.time() - schema_state["checked"] > ttl:
            try:
                with db.connect(cfg.database) as conn:
                    schema_state["problems"] = schema.check(
                        conn, cfg.backup.databases if cfg.backup and cfg.database.engine == "mssql" else None)
            except Exception as exc:  # noqa: BLE001
                log.warning("Controllo dello schema non eseguito: %s", exc)
                schema_state["problems"] = None
            schema_state["checked"] = time.time()
            for p in schema_state["problems"] or []:
                log.warning("Database da sistemare: %s (%s) -> %s", p["item"], p["problem"], p["fix"])
        return schema_state["problems"]

    schema_problems(force=True)

    # --- lingua dell'interfaccia (impostazione ui.language, letta al massimo ogni 30 secondi)
    lang_state = {"checked": 0.0, "lang": i18n.DEFAULT}

    def current_language() -> str:
        if time.time() - lang_state["checked"] > 30:
            try:
                with db.connect(cfg.database) as conn:
                    lang_state["lang"] = i18n.normalize(settings_mod.load(conn, cfg)["ui.language"])
            except Exception:  # noqa: BLE001
                pass
            lang_state["checked"] = time.time()
        return lang_state["lang"]

    def service_user() -> str:
        import getpass
        return getpass.getuser()

    @app.context_processor
    def _i18n():
        lang = current_language()
        return {"_": lambda text, **kw: i18n.t(text, lang, **kw)}

    @app.post("/api/v1/language")
    def api_language():
        lang = i18n.normalize((request.get_json(silent=True) or {}).get("lang"))
        with db.connect(cfg.database) as conn:
            settings_mod.save(conn, cfg, {"ui.language": lang})
        lang_state.update(lang=lang, checked=time.time())
        return jsonify({"lang": lang})
    # Chiave di firma della sessione (sblocco del terminale): nuova a ogni avvio,
    # quindi un riavvio della dashboard richiude il terminale.
    app.secret_key = secrets.token_bytes(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_NAME="astreo_session",
                      SESSION_COOKIE_SECURE=bool(cfg.web.trusted_proxy))

    # ------------------------------------------------------------ sicurezza
    # Utente in sola lettura: solo letture, e non quelle che espongono configurazione, comandi o log
    VIEWER_DENIED = ("/api/v1/logs", "/api/v1/api-token", "/api/v1/backup", "/api/v1/settings", "/api/v1/terminal", "/api/v1/notify", "/api/v1/processes",
                     "/api/v1/services/", "/api/v1/schema", "/terminal")

    def viewer_allowed() -> bool:
        if request.method not in ("GET", "HEAD"):
            return request.path == "/api/v1/terminal/lock"
        return not request.path.startswith(VIEWER_DENIED)

    # Integrazioni (Prometheus, Home Assistant): token dedicato, solo questi due indirizzi, solo lettura
    TOKEN_PATHS = ("/metrics", "/api/v1/status")
    token_state = {"checked": 0.0, "token": ""}

    def api_token() -> str:
        if time.time() - token_state["checked"] > 30:
            try:
                with db.connect(cfg.database) as conn:
                    token_state["token"] = settings_mod.load(conn, cfg)["api.token"]
            except Exception:  # noqa: BLE001
                pass
            token_state["checked"] = time.time()
        return token_state["token"]

    def bearer_ok() -> bool:
        import hmac
        h = request.headers.get("Authorization", "")
        tok = api_token()
        return bool(tok) and h.startswith("Bearer ") and hmac.compare_digest(h[7:].strip(), tok)

    @app.before_request
    def require_auth():
        if request.endpoint in PUBLIC_ENDPOINTS or request.path.startswith("/api/netpulse/"):
            return None  # /api/netpulse usa il proprio token (widget Windows)
        if request.path in TOKEN_PATHS and request.method == "GET" and bearer_ok():
            g.role = "integration"
            return None
        auth = request.authorization
        if (
            auth
            and cfg.web.password_hash
            and auth.username == cfg.web.username
            and check_password_hash(cfg.web.password_hash, auth.password or "")
        ):
            g.role = "admin"
            return None
        if (
            auth
            and cfg.web.viewer_username and cfg.web.viewer_password_hash
            and auth.username == cfg.web.viewer_username
            and check_password_hash(cfg.web.viewer_password_hash, auth.password or "")
        ):
            g.role = "viewer"
            if not viewer_allowed():
                return jsonify({"error": "Forbidden", "detail": i18n.t("Non consentito all'utente in sola lettura",
                                                                        current_language())}), 403
            return None
        if auth:
            log.warning("Autenticazione fallita da %s (utente %r)", request.remote_addr, auth.username)
        return Response("Autenticazione richiesta", 401, {"WWW-Authenticate": 'Basic realm="Astreo Monitor", charset="UTF-8"'})

    @app.before_request
    def csrf_guard():
        """Le modifiche arrivano solo come JSON dalla dashboard stessa.

        Il browser invia le credenziali Basic Auth anche a richieste partite da
        altri siti: un form esterno non può però inviare application/json senza
        preflight CORS, e l'Origin, se presente, deve coincidere con l'host.
        """
        if request.method in ("GET", "HEAD", "OPTIONS") or request.path.startswith("/api/netpulse/"):
            return None
        if request.path == "/api/v1/terminal/lock" and not request.is_json:
            return None  # chiusura dal browser con sendBeacon
        if not request.is_json:
            abort(415, description="Le modifiche devono essere inviate come JSON")
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if origin and urlparse(origin).netloc != request.host:
            log.warning("Richiesta rifiutata: origine %s diversa da %s", origin, request.host)
            abort(403, description="Origine della richiesta non ammessa")
        return None

    @app.before_request
    def start_timer():
        request.environ["astreo.t0"] = time.perf_counter()

    @app.after_request
    def log_request(resp):
        t0 = request.environ.get("astreo.t0")
        ms = (time.perf_counter() - t0) * 1000 if t0 else 0
        level = logging.INFO if resp.status_code < 400 else logging.WARNING
        if request.endpoint != "static":
            log.log(level, "%s %s %s -> %s (%.0f ms)", request.remote_addr, request.method, request.full_path.rstrip("?"), resp.status_code, ms)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------------------------------------------------------------- errori
    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.name, "detail": i18n.translate_stored(exc.description or "", current_language())}), exc.code
        return exc

    @app.errorhandler(settings_mod.SettingsError)
    def settings_error(exc):
        lang = current_language()
        return jsonify({"error": i18n.t("Valore non valido", lang), "detail": i18n.translate_stored(str(exc), lang)}), 400

    @app.errorhandler(checks_mod_errors.CheckError)
    def check_error(exc):
        lang = current_language()
        return jsonify({"error": i18n.t("Valore non valido", lang), "detail": i18n.translate_stored(str(exc), lang)}), 400

    @app.errorhandler(units.UnitControlError)
    def unit_error(exc):
        return jsonify({"error": "Operazione non riuscita", "detail": str(exc)}), 502

    @app.errorhandler(db.DatabaseError)
    def db_error(exc):
        log.error("Errore database: %s", exc)
        return jsonify({"error": "Database non disponibile", "detail": str(exc)[:300]}), 503

    @app.errorhandler(Exception)
    def unhandled(exc):
        log.exception("Errore non gestito su %s", request.path)
        return jsonify({"error": "Errore interno", "detail": str(exc)[:300]}), 500

    # ------------------------------------------------------------- dashboard
    @app.get("/")
    def dashboard():
        lang = current_language()
        return render_template("index.html", version=__version__, lang=lang, languages=i18n.LANGUAGES,
                               catalog=i18n.catalog(lang), service_user=service_user(), role=g.get("role", "admin"))

    @app.get("/astreomonitor")  # vecchio indirizzo, mantenuto per i preferiti
    def legacy_dashboard():
        return redirect(url_for("dashboard"), code=301)

    @app.get("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.ico")

    @app.get("/astreo-ca.crt")
    def ca_cert():
        """Certificato PUBBLICO della CA privata (mkcert), da installare su PC e telefoni."""
        import os
        from flask import send_file
        if not os.path.isfile(cfg.web.ca_cert):
            abort(404, description="Certificato della CA non presente (vedi docs/it/https-terminal.md)")
        return send_file(cfg.web.ca_cert, mimetype="application/x-x509-ca-cert", as_attachment=True,
                         download_name="astreo-ca.crt")

    @app.get("/manifest.webmanifest")
    def manifest():
        resp = app.send_static_file("manifest.webmanifest")
        resp.headers["Content-Type"] = "application/manifest+json"
        return resp

    # ------------------------------------------------------ API: tempo reale
    @app.get("/api/v1/health")
    def api_health():
        ok = db.ping(cfg.database)
        problems = schema_problems() if ok else None
        return jsonify({"status": "ok", "version": __version__, "database": ok,
                        "schema_ok": problems == [] if problems is not None else None,
                        "schema_fixes": schema.fixes(problems) if problems else [],
                        "https_port": cfg.web.https_port,
                        "time": dt.datetime.now().isoformat(timespec="seconds")})

    @app.get("/api/v1/schema")
    def api_schema():
        return jsonify({"problems": schema_problems(force=True)})

    @app.get("/api/v1/system")
    def api_system():
        return jsonify(system.snapshot(cfg.metrics.root_disk))

    @app.get("/api/v1/processes")
    def api_processes():
        limit = min(max(request.args.get("limit", 15, type=int), 1), 50)
        return jsonify(system.processes(limit))

    @app.get("/api/v1/temperatures")
    def api_temperatures():
        return jsonify({"warning": cfg.metrics.temp_warning, "alert": cfg.metrics.temp_alert, "sensors": sensors.read()})

    # ------------------------------------------------------- API: servizi
    @app.get("/api/v1/services")
    def api_services():
        with db.connect(cfg.database) as conn:
            rows = services_store.monitored(conn, cfg)
        return jsonify(services.statuses(rows))

    @app.get("/api/v1/services/<path:unit>")
    def api_service_detail(unit: str):
        with db.connect(cfg.database) as conn:
            rows = {r["unit"]: r for r in services_store.all_rows(conn)}
        if unit not in rows:
            abort(404, description=f"Servizio '{unit}' non presente tra quelli monitorati")
        state = services.statuses([rows[unit]])[0]
        state["detail"] = services.detail(unit)
        return jsonify(state)

    @app.get("/api/v1/settings/services")
    def api_services_catalog():
        with db.connect(cfg.database) as conn:
            services_store.seed_if_empty(conn, cfg)
            stored = {r["unit"]: r for r in services_store.all_rows(conn)}
        out = []
        for u in services.catalog():
            s = stored.get(u["unit"])
            out.append({**u, "monitored": bool(s and s["enabled"]), "notify": bool(s and s["notify"]),
                        "label": s["label"] if s else u["unit"].removesuffix(".service"),
                        "sort_order": s["sort_order"] if s else None})
        # servizi salvati ma non più presenti su astreo
        known = {u["unit"] for u in out}
        for unit, s in stored.items():
            if unit not in known:
                out.append({"unit": unit, "load": "not-found", "active": "unknown", "sub": "", "description": "",
                            "monitored": bool(s["enabled"]), "notify": bool(s["notify"]), "label": s["label"],
                            "sort_order": s["sort_order"]})
        return jsonify(out)

    @app.put("/api/v1/settings/services/<path:unit>")
    def api_services_update(unit: str):
        data = body()
        with db.connect(cfg.database) as conn:
            try:
                row = services_store.upsert(conn, unit, enabled=data.get("monitored"), notify=data.get("notify"),
                                            label=data.get("label"))
            except ValueError as exc:
                abort(400, description=str(exc))
        return jsonify(row)

    @app.put("/api/v1/settings/services-order")
    def api_services_order():
        order = body().get("units")
        if not isinstance(order, list) or not all(isinstance(u, str) for u in order):
            abort(400, description="units deve essere un elenco di nomi")
        with db.connect(cfg.database) as conn:
            services_store.reorder(conn, order)
        return jsonify({"ok": True})

    # -------------------------------------------------- API: impostazioni
    @app.get("/api/v1/settings")
    def api_settings():
        with db.connect(cfg.database) as conn:
            return jsonify(settings_mod.public_view(cfg, settings_mod.load(conn, cfg), current_language()))

    @app.put("/api/v1/settings")
    def api_settings_update():
        with db.connect(cfg.database) as conn:
            values = settings_mod.save(conn, cfg, body())
            log.info("Impostazioni aggiornate da %s", request.remote_addr)
            return jsonify(settings_mod.public_view(cfg, values, current_language()))

    @app.post("/api/v1/notify/test")
    def api_notify_test():
        channel = body().get("channel")
        if channel not in settings_mod.CHANNELS:
            abort(400, description="Canale non valido")
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
            _ = i18n.translator(i18n.lang_of(values))
            ok, err = notifier.send_channel(
                conn, cfg, values, channel, "test", _("Messaggio di prova"),
                _("Messaggio di prova inviato dalla dashboard di Astreo Monitor {versione} alle {quando}.",
                  versione=__version__, quando=f"{dt.datetime.now():%d/%m/%Y %H:%M}"))
        return jsonify({"ok": ok, "error": err})

    @app.get("/api/v1/notify/log")
    def api_notify_log():
        with db.connect(cfg.database) as conn:
            from sqlalchemy import func, select
            from .. import models
            L, Q = models.notification_log, models.notification_queue
            rows = db.rows(conn, select(L.c.timestamp, L.c.channel, L.c.source, L.c.subject, L.c.ok, L.c.error, L.c.status)
                           .order_by(L.c.timestamp.desc()).limit(30))
            pending = db.scalar(conn, select(func.count()).select_from(Q).where(Q.c.sent_at.is_(None)))
        for r in rows:
            r["timestamp"] = db.as_datetime(r["timestamp"]).isoformat(timespec="seconds")
            r["ok"] = bool(r["ok"])
            r["status"] = r["status"] or ("inviata" if r["ok"] else "fallita")
        return jsonify({"items": rows, "pending": pending})

    # ---------------------------------------------------- API: speedtest
    @app.get("/api/v1/speedtest/status")
    def api_speedtest_status():
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
            return jsonify({
                "enabled": values["speedtest.enabled"],
                "timer": units.info(SPEEDTEST_TIMER),
                "service": units.info(SPEEDTEST_SERVICE),
                "latest": history.latest_speedtest(conn),
                "alert": db.state_get(conn, "alert:speedtest"),
            })

    @app.post("/api/v1/speedtest/run")
    def api_speedtest_run():
        units.control(SPEEDTEST_SERVICE, "start")
        log.info("Speedtest avviato manualmente da %s", request.remote_addr)
        return jsonify({"ok": True})

    @app.post("/api/v1/speedtest/pause")
    def api_speedtest_pause():
        paused = bool(body().get("paused"))
        with db.connect(cfg.database) as conn:
            settings_mod.save(conn, cfg, {"speedtest.enabled": not paused})
        # Il flag nel DB vale anche dopo un riavvio; il timer si ferma/riparte per coerenza visiva.
        try:
            units.control(SPEEDTEST_TIMER, "stop" if paused else "start")
            timer_error = None
        except units.UnitControlError as exc:
            timer_error = str(exc)
        log.info("Speedtest %s da %s", "sospeso" if paused else "riattivato", request.remote_addr)
        return jsonify({"ok": True, "enabled": not paused, "timer_error": timer_error})

    # ------------------------------------------------------- API: storico
    @app.get("/api/v1/history/metrics")
    def api_history_metrics():
        start, end = parse_period()
        with db.connect(cfg.database) as conn:
            return jsonify(history.metrics(conn, start, end))

    @app.get("/api/v1/history/temperatures")
    def api_history_temperatures():
        start, end = parse_period()
        with db.connect(cfg.database) as conn:
            return jsonify(history.temperatures(conn, start, end))

    @app.get("/api/v1/history/speedtest")
    def api_history_speedtest():
        start, end = parse_period()
        with db.connect(cfg.database) as conn:
            data = history.speedtests(conn, start, end)
            values = settings_mod.load(conn, cfg)
        data["from"], data["to"] = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        data["thresholds"] = {k: values[f"speedtest.{k}"] for k in
                              ("download_warning", "download_alert", "upload_warning", "upload_alert")}
        return jsonify(data)

    @app.get("/api/v1/history/connectivity")
    def api_history_connectivity():
        start, end = parse_period()
        with db.connect(cfg.database) as conn:
            data = history.connectivity(conn, start, end)
            values = settings_mod.load(conn, cfg)
        data["from"], data["to"] = start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")
        data["thresholds"] = {"loss_warning": values["connectivity.loss_warning"], "rtt_warning": values["connectivity.rtt_warning"]}
        return jsonify(data)

    @app.get("/api/v1/expiry")
    def api_expiry():
        with db.connect(cfg.database) as conn:
            return jsonify(i18n.translate_fields(db.state_get(conn, "expiry:last") or {"items": []}, current_language()))

    @app.get("/api/v1/health-checks")
    def api_health_checks():
        with db.connect(cfg.database) as conn:
            return jsonify(i18n.translate_fields({"health": db.state_get(conn, "health:last"),
                                                  "restoretest": db.state_get(conn, "restoretest:last")}, current_language()))

    @app.post("/api/v1/summary/test")
    def api_summary_test():
        from ..jobs import weekly_summary
        now = dt.datetime.now().replace(second=0, microsecond=0)
        with db.connect(cfg.database) as conn:
            subject, text = weekly_summary.build(conn, now, settings_mod.load(conn, cfg))
            _ = i18n.translator(current_language())
            ok = notifier.dispatch(conn, cfg, "summary", _("{oggetto} (prova)", oggetto=subject), text, detected_at=now)
        if not ok:
            abort(400, description="Nessun canale attivo per il Riepilogo settimanale (tabella Quali avvisi su quali canali)")
        return jsonify({"ok": True})

    # ------------------------------------------------------- moduli ed eventi
    @app.get("/api/v1/integrations")
    def api_integrations():
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
        return jsonify({"modules": integrations.status(values), "events_visible": values["ui.events"]})

    @app.get("/api/v1/docker")
    def api_docker():
        present, reason = docker_mod.detect()
        if not present:
            return jsonify({"available": False, "reason": reason, "containers": []})
        return jsonify({"available": True, "reason": reason, "containers": docker_mod.containers()})

    def pihole_client():
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
        return values, pihole_mod.Client(values["pihole.url"], values["pihole.password"])

    @app.get("/api/v1/pihole")
    def api_pihole():
        values, client = pihole_client()
        present, reason = pihole_mod.detect(values["pihole.url"])
        if not present:
            return jsonify({"available": False, "reason": reason})
        if not values["pihole.password"]:
            return jsonify({"available": True, "configured": False, "reason": "password per le app non impostata"})
        try:
            return jsonify({"available": True, "configured": True, **client.overview()})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"available": True, "configured": True, "error": str(exc)[:200]})

    @app.post("/api/v1/pihole/test")
    def api_pihole_test():
        values, client = pihole_client()
        try:
            ov = client.overview()
            return jsonify({"ok": True, "detail": pihole_mod.evaluate(ov, None)[1]})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "detail": str(exc)[:200]})

    @app.get("/api/v1/events")
    def api_events():
        start, end = parse_period()
        with db.connect(cfg.database) as conn:
            outages = history.connectivity(conn, start, end)["outages"]
            return jsonify({"events": events.list_events(conn, start, end, outages, current_language()), "kinds": {k: i18n.t(v, current_language()) for k, v in events.KINDS.items()}})

    # ------------------------------------------- controlli di dispositivi e servizi
    from sqlalchemy import delete as sa_delete, func as sa_func, select as sa_select, update as sa_update
    from .. import checks as checks_mod

    def check_row(conn, c: dict) -> dict:
        lang = current_language()
        st = db.state_get(conn, f"check:{c['id']}") or {}
        R = models.check_results
        since = dt.datetime.now() - dt.timedelta(hours=24)
        tot, good = db.one(conn, sa_select(sa_func.count().label("n"),
                                           sa_func.sum(sa_func.cast(R.c.ok, models.Integer)).label("ok"))
                           .where(R.c.check_id == c["id"], R.c.timestamp >= since)).values()
        st = i18n.translate_fields(st, lang, fields=("detail", "warning"))
        return {**c, "updated_at": None, "state": st,
                "availability_24h": round(100 * (good or 0) / tot, 2) if tot else None}

    @app.get("/api/v1/checks")
    def api_checks():
        C = models.checks
        with db.connect(cfg.database) as conn:
            return jsonify({"checks": [check_row(conn, c) for c in db.rows(conn, sa_select(C).order_by(C.c.sort_order, C.c.id))]})

    @app.post("/api/v1/checks")
    def api_check_create():
        data = checks_mod.validate(request.get_json(silent=True) or {})
        C = models.checks
        with db.connect(cfg.database) as conn:
            top = db.scalar(conn, sa_select(sa_func.coalesce(sa_func.max(C.c.sort_order), 0))) or 0
            new_id = conn.execute(C.insert().values(**data, sort_order=top + 10, updated_at=db.now())).inserted_primary_key[0]
            return jsonify(check_row(conn, db.one(conn, sa_select(C).where(C.c.id == new_id)))), 201

    @app.put("/api/v1/checks/<int:cid>")
    def api_check_update(cid: int):
        data = checks_mod.validate(request.get_json(silent=True) or {})
        C = models.checks
        with db.connect(cfg.database) as conn:
            if not conn.execute(sa_update(C).where(C.c.id == cid).values(**data, updated_at=db.now())).rowcount:
                abort(404, description="Controllo inesistente")
            return jsonify(check_row(conn, db.one(conn, sa_select(C).where(C.c.id == cid))))

    @app.delete("/api/v1/checks/<int:cid>")
    def api_check_delete(cid: int):
        C, R, S = models.checks, models.check_results, models.monitor_state
        with db.connect(cfg.database) as conn:
            conn.execute(sa_delete(R).where(R.c.check_id == cid))
            conn.execute(sa_delete(S).where(S.c.key.in_((f"check:{cid}", f"alert:check:{cid}"))))
            if not conn.execute(sa_delete(C).where(C.c.id == cid)).rowcount:
                abort(404, description="Controllo inesistente")
        return jsonify({"deleted": cid})

    @app.post("/api/v1/checks/test")
    def api_check_test():
        data = checks_mod.validate(request.get_json(silent=True) or {})
        r = checks_mod.run(data)
        lang = current_language()
        return jsonify({"ok": r.ok, "latency_ms": r.latency_ms, "detail": i18n.translate_stored(r.detail, lang),
                        "warning": i18n.translate_stored(r.warning, lang), "cert_days": r.cert_days})

    @app.get("/api/v1/checks/<int:cid>/history")
    def api_check_history(cid: int):
        start, end = parse_period()
        R = models.check_results
        with db.connect(cfg.database) as conn:
            b = history.bucket_seconds(start, end)
            if (end - start).total_seconds() <= 6 * 3600:
                b = 60
            expr, epoch = db.bucket_expr(conn, R.c.timestamp, b)
            inner = sa_select(expr.label("bucket"), R.c.latency_ms, sa_func.cast(R.c.ok, models.Integer).label("ok")) \
                .where(R.c.check_id == cid, R.c.timestamp >= start, R.c.timestamp < end).subquery()
            rows = db.rows(conn, sa_select(inner.c.bucket, sa_func.avg(inner.c.latency_ms).label("lat"),
                                           sa_func.avg(inner.c.ok * 100.0).label("up"))
                           .group_by(inner.c.bucket).order_by(inner.c.bucket))
        return jsonify({"labels": [db.from_bucket(r["bucket"], epoch).isoformat(timespec="seconds") for r in rows],
                        "latency": [None if r["lat"] is None else round(float(r["lat"]), 1) for r in rows],
                        "up": [round(float(r["up"]), 1) for r in rows]})

    # ------------------------------------------------------------------ backup
    @app.get("/api/v1/backup")
    def api_backup():
        from .. import rclone
        b = cfg.backup
        with db.connect(cfg.database) as conn:
            last = db.state_get(conn, "backup:last")
        try:
            unit = units.info("astreo-backup.timer")
        except Exception:  # noqa: BLE001
            unit = None
        return jsonify({
            "configured": b is not None, "last": last, "timer": unit,
            "engine": cfg.database.engine,
            "local_dir": b.local_dir if b else None, "local_keep": b.local_keep if b else None,
            "github_repo": b.github_repo if b else None, "github_keep": b.github_keep if b else None,
            "rclone": {"available": rclone.available(), "remotes": rclone.remotes()},
        })

    @app.post("/api/v1/backup/test")
    def api_backup_test():
        from .. import rclone
        dest = str((request.get_json(silent=True) or {}).get("dest", "")).strip().rstrip("/")
        lang = current_language()
        try:
            return jsonify({"ok": True, "detail": i18n.translate_stored(rclone.test(dest), lang)})
        except (rclone.RcloneError, OSError) as exc:
            return jsonify({"ok": False, "detail": i18n.translate_stored(str(exc), lang)})

    @app.post("/api/v1/backup/run")
    def api_backup_run():
        units.control("astreo-backup.service", "start")
        return jsonify({"started": True})

    # ------------------------------------------------------------ integrazioni
    from .. import exporter

    @app.get("/metrics")
    def prometheus_metrics():
        with db.connect(cfg.database) as conn:
            text = exporter.metrics(conn, cfg)
        return Response(text, mimetype="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/api/v1/status")
    def api_status():
        with db.connect(cfg.database) as conn:
            return jsonify(exporter.status(conn, cfg))

    @app.post("/api/v1/api-token")
    def api_token_new():
        import secrets as _secrets
        tok = _secrets.token_urlsafe(32)
        with db.connect(cfg.database) as conn:
            settings_mod.save(conn, cfg, {"api.token": tok})
        token_state.update(token=tok, checked=time.time())
        return jsonify({"token": tok})                 # mostrato una sola volta

    @app.delete("/api/v1/api-token")
    def api_token_delete():
        with db.connect(cfg.database) as conn:
            settings_mod.save(conn, cfg, {"api.token": ""})
        token_state.update(token="", checked=time.time())
        return jsonify({"deleted": True})

    # --------------------------------------------------------------------- log
    from ..collectors import logs as logs_mod

    def log_units() -> list[dict]:
        with db.connect(cfg.database) as conn:
            mon = [{"unit": s["unit"], "label": s["label"]} for s in services_store.monitored(conn, cfg)]
        own = sorted({u for u in units.CONTROLLABLE if u.endswith(".service")} |
                     {"astreo-monitor-web.service", "astreo-telegram.service", "astreo-terminal.service"})
        return mon + [{"unit": u, "label": u.removesuffix(".service")} for u in own if u not in {m["unit"] for m in mon}]

    @app.get("/api/v1/logs/units")
    def api_log_units():
        return jsonify({"units": log_units()})

    @app.get("/api/v1/logs")
    def api_logs():
        allowed = {u["unit"] for u in log_units()}
        chosen = [u for u in request.args.get("units", "").split(",") if u]
        if not chosen or any(u not in allowed for u in chosen):
            abort(400, description="Servizio non consentito")
        try:
            entries = logs_mod.read(chosen, request.args.get("since", "1h"), request.args.get("priority", "info"),
                                    request.args.get("grep", "")[:200], int(request.args.get("lines", 500)))
        except logs_mod.LogError as exc:
            return jsonify({"error": i18n.translate_stored(str(exc), current_language()), "entries": []}), 200
        return jsonify({"entries": entries})

    # ---------------------------------------------------------- aiuto in linea
    from .. import help as help_mod

    @app.get("/api/v1/help/<name>")
    def api_help(name: str):
        lang = request.args.get("lang") or current_language()
        try:
            return jsonify(help_mod.page(lang, name))
        except help_mod.HelpError:
            abort(404, description="Pagina della guida non trovata")

    @app.get("/api/v1/heartbeat")
    def api_heartbeat():
        with db.connect(cfg.database) as conn:
            return jsonify(db.state_get(conn, "heartbeat:last") or {})

    @app.post("/api/v1/heartbeat/test")
    def api_heartbeat_test():
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
            if not values["heartbeat.url"]:
                abort(400, description="URL di heartbeat non configurato")
            ok, err = heartbeat.ping(conn, {**values, "heartbeat.enabled": True}, ok=True, message="ping di prova dalla dashboard")
        return jsonify({"ok": ok, "error": err})

    @app.get("/api/v1/network")
    def api_network():
        with db.connect(cfg.database) as conn:
            return jsonify({
                "speedtest": history.latest_speedtest(conn),
                "speedtest_alert": db.state_get(conn, "alert:speedtest"),
                "public_ip": db.state_get(conn, "publicip:current"),
                "public_ip_history": history.public_ip_history(conn),
                "backup": db.state_get(conn, "backup:last"),
                "connectivity": i18n.translate_fields(db.state_get(conn, "connectivity:last"), current_language()),
            })

    return app
