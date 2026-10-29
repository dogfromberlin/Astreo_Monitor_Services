# Metriche e temperature

Job: `astreo_monitor.jobs.metrics` — timer `astreo-metrics.timer`, ogni 5 minuti.

## Cosa registra

Tabella `system_metrics`, una riga per esecuzione:

| Campo | Significato |
|---|---|
| `cpu_pct` | CPU occupata, **media esatta** dei 5 minuti trascorsi |
| `load1`, `load5`, `load15` | Load average |
| `mem_used_pct`, `mem_used_mb` | Memoria realmente usata (esclusa la cache) |
| `swap_used_pct` | Swap |
| `disk_used_pct` | Disco `root_disk` (default `/`) |
| `source` | `v2` per i nuovi dati, `legacy` per lo storico importato dalla 1.x |

Tabella `system_temperature`: una riga per sensore (`adapter`, `device`, `temperature`),
con gli stessi nomi della 1.x, così lo storico resta continuo.

### Come si calcola la CPU
A ogni esecuzione si salvano i contatori cumulativi della CPU (`cpu_times`) in
`monitor_state`. All'esecuzione successiva la percentuale è calcolata sulla
differenza: tempo occupato / tempo totale dell'intervallo. Così il valore
rappresenta tutti i 5 minuti, non un istante di mezzo secondo come nella 1.x.
Se il confronto non è possibile (primo avvio, riavvio del server, intervallo
sotto i 30 secondi o sopra l'ora), si misura un campione di 5 secondi.

### Temperature
Lette con `sensors -j` (pacchetto `lm-sensors`). Se il comando manca o fallisce si
usa psutil (in quel caso i nomi dei sensori cambiano).

## Allarmi

| Controllo | Valore | Soglie (`[metrics]`) |
|---|---|---|
| Temperatura | massima tra tutti i sensori | `temp_warning` 85, `temp_alert` 95 °C |
| Disco | `root_disk` | `disk_warning` 85, `disk_alert` 95 % |

Email al cambio di stato e promemoria ogni `reminder_hours` (vedi [notifiche.md](notifiche.md)).
`notify = false` registra lo stato senza inviare email.

## Comandi (finestra SSH su astreo)

```bash
cd ~/Astreo_Monitor_Services
# prova senza scrivere nulla
.venv/bin/python -m astreo_monitor.jobs.metrics --config /etc/astreo-monitor/config.ini --dry-run
# esecuzione immediata tramite systemd
sudo systemctl start astreo-metrics.service
journalctl -u astreo-metrics.service -n 20 --no-pager
systemctl list-timers astreo-metrics.timer --no-pager
```

Per cambiare frequenza: modificare `OnCalendar=` in
`/etc/systemd/system/astreo-metrics.timer` (es. `*:0/2` = ogni 2 minuti), poi
`sudo systemctl daemon-reload && sudo systemctl restart astreo-metrics.timer`.
