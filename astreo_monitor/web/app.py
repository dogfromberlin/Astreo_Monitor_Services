"""Applicazione Flask: dashboard (/) e API REST (/api/v1/...)."""
from __future__ import annotations

import datetime as dt
import logging
import time

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .. import __version__, db
from ..collectors import sensors, services, system
from ..config import Config
from . import history

log = logging.getLogger("web")

RANGES = {"24h": dt.timedelta(hours=24), "7d": dt.timedelta(days=7), "30d": dt.timedelta(days=30),
          "90d": dt.timedelta(days=90), "365d": dt.timedelta(days=365)}
MAX_SPAN = dt.timedelta(days=400)
PUBLIC_ENDPOINTS = {"api_health", "static", "favicon"}


def parse_period() -> tuple[dt.datetime, dt.datetime]:
    """Periodo da ?range=24h|7d|30d|90d|365d oppure ?from=...&to=... (ISO 8601)."""
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


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.json.ensure_ascii = False
    services_by_key = {s.key: s for s in cfg.web.services}

    # ------------------------------------------------------------------ auth
    @app.before_request
    def require_auth():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
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
        resp.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else resp.headers.get("Cache-Control", "")
        return resp

    # ---------------------------------------------------------------- errori
    @app.errorhandler(HTTPException)
    def http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.name, "detail": exc.description}), exc.code
        return exc

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

    # ------------------------------------------------------------------- API
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

    @app.get("/api/v1/services")
    def api_services():
        return jsonify(services.statuses(cfg.web.services))

    @app.get("/api/v1/services/<key>")
    def api_service_detail(key: str):
        svc = services_by_key.get(key)
        if not svc:
            abort(404, description=f"Servizio '{key}' non presente nella configurazione")
        state = services.statuses([svc])[0]
        state["detail"] = services.detail(svc)
        return jsonify(state)

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
            return jsonify(history.speedtests(conn, start, end))

    @app.get("/api/v1/network")
    def api_network():
        """Ultimo speedtest, IP pubblico attuale e storico variazioni."""
        with db.connect(cfg.database) as conn:
            return jsonify({
                "speedtest": history.latest_speedtest(conn),
                "speedtest_alert": db.state_get(conn, "alert:speedtest"),
                "public_ip": db.state_get(conn, "publicip:current"),
                "public_ip_history": history.public_ip_history(conn),
                "thresholds": {
                    "download_warning": cfg.speedtest.download_warning, "download_alert": cfg.speedtest.download_alert,
                    "upload_warning": cfg.speedtest.upload_warning, "upload_alert": cfg.speedtest.upload_alert,
                },
            })

    return app
