"""Avvio del web server: python -m astreo_monitor.web [--config FILE] [-v]"""
from __future__ import annotations

import argparse
import logging
import sys

from waitress import serve

from .. import __version__, config as config_mod, logging_setup
from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="astreo_monitor.web", description="Dashboard e API di Astreo Monitor")
    parser.add_argument("-c", "--config", help="File di configurazione")
    parser.add_argument("-p", "--port", type=int, help="Porta (sovrascrive [web] port)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log di debug")
    args = parser.parse_args()

    logging_setup.setup(args.verbose)
    log = logging.getLogger("web")
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        log.error("%s", exc)
        sys.exit(2)
    if not cfg.web.username or not cfg.web.password_hash:
        log.error("[web] username e password_hash sono obbligatori (vedi docs/it/configuration.md)")
        sys.exit(2)

    port = args.port or cfg.web.port
    log.info("Astreo Monitor %s in ascolto su %s:%s (config %s)", __version__, cfg.web.host, port, cfg.path)
    proxy = {}
    if cfg.web.trusted_proxy:
        # dietro nginx: IP reale del client e schema https dagli header del proxy
        proxy = {"trusted_proxy": cfg.web.trusted_proxy, "trusted_proxy_count": 1,
                 "trusted_proxy_headers": {"x-forwarded-for", "x-forwarded-proto", "x-forwarded-host"},
                 "clear_untrusted_proxy_headers": True}
        log.info("Proxy fidato: %s", cfg.web.trusted_proxy)
    serve(create_app(cfg), host=cfg.web.host, port=port, threads=cfg.web.threads, ident="astreo-monitor", **proxy)


if __name__ == "__main__":
    main()
