"""Logging unico: tutto su stdout, raccolto da journald quando gira sotto systemd."""
import logging
import sys

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(verbose: bool = False) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Librerie rumorose
    for name in ("urllib3", "waitress.queue"):
        logging.getLogger(name).setLevel(logging.WARNING)
