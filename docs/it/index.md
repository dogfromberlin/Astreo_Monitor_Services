# Astreo Monitor — guida

Monitoraggio self-hosted per un server Linux di casa o di un piccolo ufficio: dashboard web, avvisi,
backup del database e controlli di altri dispositivi. Questa guida è anche l'**aiuto in linea** della
dashboard (icona **?** nelle sezioni).

<a id="pagine"></a>
## Pagine

| Pagina | Contenuto |
|---|---|
| [Installazione e aggiornamento](installation.md) | requisiti, `install.sh`, `update.sh`, HTTPS, file generati dai modelli |
| [Configurazione e utenti](configuration.md) | `config.ini`, password, utente in sola lettura |
| [La dashboard](dashboard.md) | viste, impostazioni, lingue, smartphone |
| [Server](server.md) | risorse, temperature, processi, servizi, eventi sui grafici |
| [Connessione](connection.md) | controllo continuo, speedtest, IP pubblico |
| [Dispositivi e servizi](devices.md) | controlli ping, porta TCP e pagina web |
| [Notifiche](notifications.md) | canali, regole di avviso, fascia di silenzio, heartbeat, bot Telegram, riepilogo |
| [Salute del sistema](health.md) | dischi (SMART), aggiornamenti, scadenze |
| [Backup](backup.md) | backup notturno, copie con rclone e GitHub, verifica e ripristino |
| [Database](database.md) | SQL Server, PostgreSQL, SQLite, migrazioni, retention |
| [Moduli](modules.md) | Docker e Pi-hole |
| [Integrazioni e log](integrations.md) | Prometheus, Home Assistant, vista Log |
| [HTTPS e terminale](https-terminal.md) | certificato con CA privata, terminale web |
| [Operatività e diagnosi](operations.md) | diagnosi, journal, problemi frequenti, disinstallazione |
| [Sviluppo](development.md) | architettura, test, traduzioni, come contribuire |

<a id="concetti"></a>
## Concetti di base

| Concetto | Significato |
|---|---|
| **Job** | attività periodiche (metriche, speedtest, backup…) eseguite da timer systemd |
| **Stati** | `OK`, `WARNING`, `ALERT` o `DOWN`; gli avvisi partono ai cambi di stato, secondo le regole |
| **Evento** | ciò che è successo (riavvio, interruzione, servizio fermo…), segnato sui grafici |
| **Moduli** | sezioni facoltative che compaiono solo se il servizio è presente (Docker, Pi-hole) |
