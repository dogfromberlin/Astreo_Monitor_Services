"""Controllo dello schema del database: tabelle, colonne, procedure e permessi attesi.

Per ogni elemento mancante indica lo script SQL da eseguire. Usato:
  - all'avvio della dashboard (avviso nel journal e banner nella pagina);
  - da /api/v1/health;
  - dal comando di diagnosi: python -m astreo_monitor.doctor
Uso diretto: python -m astreo_monitor.schema [--config FILE]
"""
from __future__ import annotations

import argparse
import sys

from . import db

# tabella -> (colonne indispensabili, script che la crea)
TABLES = {
    "system_metrics": (["timestamp", "cpu_pct", "load1", "mem_used_pct", "disk_used_pct", "source"], "001_install.sql"),
    "speedtest_results": (["timestamp", "download_mbps", "upload_mbps", "latency_ms", "status", "provider"], "001_install.sql"),
    "public_ip_history": (["timestamp", "ip", "previous_ip"], "001_install.sql"),
    "monitor_state": (["key", "value", "updated_at"], "001_install.sql"),
    "system_temperature": (["timestamp", "adapter", "device", "temperature"], "002_switch.sql"),
    "app_settings": (["key", "value", "updated_at"], "005_impostazioni.sql"),
    "monitored_services": (["unit", "label", "enabled", "notify", "sort_order"], "005_impostazioni.sql"),
    "notification_log": (["timestamp", "channel", "source", "subject", "ok", "error"], "005_impostazioni.sql"),
    "notification_queue": (["created_at", "due_at", "source", "channel", "subject", "body", "attempts", "sent_at"], "006_avvisi.sql"),
    "connectivity_samples": (["timestamp", "target", "role", "received", "loss_pct", "rtt_avg_ms"], "007_connessione.sql"),
}
# colonne aggiunte a tabelle esistenti da script successivi
EXTRA_COLUMNS = {("notification_log", "status"): "006_avvisi.sql"}
# procedure in master usate dalla verifica del ripristino
PROCEDURES = {"master.dbo.astreo_restoretest_check": "008_verifica_ripristino.sql",
              "master.dbo.astreo_restoretest_drop": "008_verifica_ripristino.sql"}


def check(conn, backup_databases: list[str] | None = None) -> list[dict]:
    """Ritorna l'elenco dei problemi: [{"item", "problem", "script"}]. Vuoto = schema completo."""
    problems = []
    rows = db.query(conn, "SELECT t.name AS t, c.name AS c FROM sys.tables t JOIN sys.columns c ON c.object_id = t.object_id")
    present: dict[str, set] = {}
    for r in rows:
        present.setdefault(r["t"].lower(), set()).add(r["c"].lower())

    for table, (cols, script) in TABLES.items():
        have = present.get(table)
        if have is None:
            problems.append({"item": table, "problem": "tabella mancante", "script": script})
            continue
        missing = [c for c in cols if c.lower() not in have]
        if missing:
            problems.append({"item": table, "problem": f"colonne mancanti: {', '.join(missing)}", "script": script})
    for (table, col), script in EXTRA_COLUMNS.items():
        if table in present and col not in present[table]:
            problems.append({"item": f"{table}.{col}", "problem": "colonna mancante", "script": script})

    for proc, script in PROCEDURES.items():
        r = db.query_one(conn, "SELECT HAS_PERMS_BY_NAME(%s, 'OBJECT', 'EXECUTE') AS p", (proc,))
        if r["p"] != 1:
            problems.append({"item": proc, "problem": "procedura mancante o senza permesso di esecuzione", "script": script})

    for name in backup_databases or []:
        r = db.query_one(conn, "SELECT HAS_PERMS_BY_NAME(%s, 'DATABASE', 'BACKUP DATABASE') AS p", (name,))
        if r["p"] != 1:
            problems.append({"item": f"backup di {name}", "problem": "permesso BACKUP DATABASE mancante",
                             "script": "004_backup.sql"})
    r = db.query_one(conn, "SELECT HAS_PERMS_BY_NAME('master', 'DATABASE', 'CREATE DATABASE') AS p")
    if r["p"] != 1:
        problems.append({"item": "CREATE DATABASE in master", "problem": "permesso mancante (verifica dei backup)",
                         "script": "004_backup.sql"})
    return problems


def scripts_to_run(problems: list[dict]) -> list[str]:
    return sorted({p["script"] for p in problems})


def main() -> None:
    from . import config as config_mod
    parser = argparse.ArgumentParser(prog="astreo_monitor.schema", description="Controlla lo schema del database")
    parser.add_argument("-c", "--config")
    args = parser.parse_args()
    cfg = config_mod.load(args.config)
    with db.connect(cfg.database) as conn:
        problems = check(conn, cfg.backup.databases if cfg.backup else None)
    if not problems:
        print("Schema del database completo.")
        return
    for p in problems:
        print(f"MANCA  {p['item']}: {p['problem']}  ->  sql/{p['script']}")
    print("\nScript da eseguire come sa, in quest'ordine: " + ", ".join(scripts_to_run(problems)))
    sys.exit(1)


if __name__ == "__main__":
    main()
