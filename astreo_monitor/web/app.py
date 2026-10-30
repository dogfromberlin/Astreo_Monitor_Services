"""Applicazione Flask: dashboard (/) e API REST (/api/v1/...)."""
from __future__ import annotations

import datetime as dt
import logging
import secrets
import time
from urllib.parse import urlparse

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .. import __version__, db, notifier, services_store
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
PUBLIC_ENDPOINTS = {"api_health", "static", "favicon", "manifest", "terminal.lock"}
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
    # Chiave di firma della sessione (sblocco del terminale): nuova a ogni avvio,
    # quindi un riavvio della dashboard richiude il terminale.
    app.secret_key = secrets.token_bytes(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_NAME="astreo_session",
                      SESSION_COOKIE_SECURE=bool(cfg.web.trusted_proxy))

    # ------------------------------------------------------------ sicurezza
    @app.before_request
    def require_auth():
        if request.endpoint in PUBLIC_ENDPOINTS or request.path.startswith("/api/netpulse/"):
            return None  # /api/netpulse usa il proprio token (widget Windows)
        auth = request.authorization
        if (
            auth
            and cfg.web.password_hash
            and auth.username == cfg.web.username
            and check_password_hash(cfg.web.password_hash, auth.password or "")
        ):
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
            return jsonify({"error": exc.name, "detail": exc.description}), exc.code
        return exc

    @app.errorhandler(settings_mod.SettingsError)
    def settings_error(exc):
        return jsonify({"error": "Valore non valido", "detail": str(exc)}), 400

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
        return render_template("index.html", version=__version__)

    @app.get("/astreomonitor")  # vecchio indirizzo, mantenuto per i preferiti
    def legacy_dashboard():
        return redirect(url_for("dashboard"), code=301)

    @app.get("/favicon.ico")
    def favicon():
        return app.send_static_file("favicon.ico")

    @app.get("/manifest.webmanifest")
    def manifest():
        resp = app.send_static_file("manifest.webmanifest")
        resp.headers["Content-Type"] = "application/manifest+json"
        return resp

    # ------------------------------------------------------ API: tempo reale
    @app.get("/api/v1/health")
    def api_health():
        ok = db.ping(cfg.database)
        return jsonify({"status": "ok", "version": __version__, "database": ok,
                        "time": dt.datetime.now().isoformat(timespec="seconds")})

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
            return jsonify(settings_mod.public_view(cfg, settings_mod.load(conn, cfg)))

    @app.put("/api/v1/settings")
    def api_settings_update():
        with db.connect(cfg.database) as conn:
            values = settings_mod.save(conn, cfg, body())
            log.info("Impostazioni aggiornate da %s", request.remote_addr)
            return jsonify(settings_mod.public_view(cfg, values))

    @app.post("/api/v1/notify/test")
    def api_notify_test():
        channel = body().get("channel")
        if channel not in settings_mod.CHANNELS:
            abort(400, description="Canale non valido")
        with db.connect(cfg.database) as conn:
            values = settings_mod.load(conn, cfg)
            ok, err = notifier.send_channel(
                conn, cfg, values, channel, "test", "Messaggio di prova",
                f"Messaggio di prova inviato dalla dashboard di Astreo Monitor {__version__} "
                f"alle {dt.datetime.now():%d/%m/%Y %H:%M}.")
        return jsonify({"ok": ok, "error": err})

    @app.get("/api/v1/notify/log")
    def api_notify_log():
        with db.connect(cfg.database) as conn:
            rows = db.query(conn, "SELECT TOP 30 [timestamp], channel, source, subject, ok, error, status "
                                  "FROM notification_log ORDER BY [timestamp] DESC")
            pending = db.query_one(conn, "SELECT COUNT(*) AS n FROM notification_queue WHERE sent_at IS NULL")["n"]
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

    @app.get("/api/v1/network")
    def api_network():
        with db.connect(cfg.database) as conn:
            return jsonify({
                "speedtest": history.latest_speedtest(conn),
                "speedtest_alert": db.state_get(conn, "alert:speedtest"),
                "public_ip": db.state_get(conn, "publicip:current"),
                "public_ip_history": history.public_ip_history(conn),
                "backup": db.state_get(conn, "backup:last"),
            })

    return app
