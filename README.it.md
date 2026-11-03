# Astreo Monitor

> 🇬🇧 English version: [README.md](README.md)

Monitoraggio self-hosted per un server Linux di casa: dashboard web, avvisi via email / Telegram / WhatsApp,
backup notturno del database con verifica del ripristino, e alcune funzioni che di solito bisogna mettere
insieme a mano.

## Funzioni

| Area | Cosa offre |
|---|---|
| **Server** | CPU, load, memoria, disco, temperature, processi, partizioni; grafici storici con gli **eventi** (riavvii, interruzioni, cambi di IP, servizi fermi, avvisi) sulla linea del tempo |
| **Servizi** | Qualsiasi unit systemd: attivo / fermo, avvisi quando si ferma e quando riparte, avvio e arresto dalla dashboard |
| **Server collegati** | Agenti leggeri per altri server **Linux e Windows** (solo invio, token per server, coda locale): panoramica, storico, servizi, riavvii, avvisi ([guida](docs/it/agents.md)) |
| **Dispositivi e servizi** | Controlli ping, porta TCP e pagina web di altri dispositivi (router, NAS, siti…) con storico e avvisi ([controlli.md](docs/it/devices.md)) |
| **Connessione** | Ping verso router e Internet ogni minuto (interruzioni, disponibilità), speedtest periodico con soglie, cambi di IP pubblico |
| **Salute** | Stato SMART dei dischi, aggiornamenti di sicurezza in sospeso e riavvii richiesti, scadenze di certificati e token |
| **Sicurezza dei dati** | Backup notturno del database con copie verificate su NAS, cartelle di rete o cloud (rclone) e/o su un repository GitHub privato, più la **verifica mensile del ripristino** |
| **Avvisi** | Email, Telegram, WhatsApp (CallMeBot), ntfy, Gotify, Discord, webhook; regole per controllo (solo se peggiora / a ogni cambio, promemoria, rientro), fascia di silenzio, heartbeat esterno (healthchecks.io) |
| **Bot Telegram** | `/stato`, `/connessione`, `/speedtest`, `/servizi`, `/controlli`, `/aiuto` (anche in inglese) |
| **Moduli** | Container Docker e Pi-hole (v6): compaiono solo se presenti sul server |
| **Integrazioni** | `/metrics` per Prometheus e stato JSON per Home Assistant, con token dedicato ([guida](docs/it/integrations.md)) |
| **Log** | Journal dei servizi monitorati nella dashboard, con filtri |
| **Utenti** | Amministratore e un utente facoltativo in sola lettura ([guida](docs/it/configuration.md#utenti)) |
| **Terminale web** | Shell nel browser protetta da una password separata (solo HTTPS) |
| **Riepilogo settimanale** | Ogni lunedì mattina |
| **Aiuto in linea** | icona **?** in ogni sezione: apre la guida al capitolo giusto, nella lingua scelta |
| **Lingue** | Italiano e inglese (dashboard, notifiche, bot, installatore) |

## Requisiti

- Ubuntu o Debian con systemd, Python 3.10+
- Database: **SQLite** (niente da installare), **PostgreSQL** (installato dall'installatore se locale) o **SQL Server** (istanza esistente, va bene Express)
- Facoltativi: nginx per HTTPS (con una CA privata creata con mkcert), Docker, Pi-hole

## Installazione

```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh
```
L'installatore fa alcune domande (lingua, database, HTTPS, terminale, moduli, password), prepara il database,
genera dai modelli le unit systemd e i file di nginx e polkit, avvia i servizi e lancia una diagnosi.
Dettagli: [docs/it/installation.md](docs/it/installation.md).

## Aggiornamento

```bash
sudo bash update.sh                     # da git
sudo bash update.sh /percorso/pacchetto.zip
sudo bash update.sh --enable-https      # aggiunge nginx, certificato e terminale a un'installazione HTTP
```
Codice → librerie → verifiche automatiche (si ferma se falliscono) → file di sistema → migrazione del database →
riavvio → diagnosi.

## Diagnosi

```bash
sudo .venv/bin/python -m astreo_monitor.doctor
```

## Documentazione

Guida completa, in italiano e in inglese: [docs/it/index.md](docs/it/index.md) · [docs/en/index.md](docs/en/index.md).
È anche l'aiuto in linea della dashboard.

## Sviluppo

```bash
bash scripts/verifica.sh        # pyflakes, sintassi JavaScript, circa 150 test
```
I test girano su SQLite in locale e su SQLite, PostgreSQL e SQL Server su GitHub Actions. Le modifiche allo
schema passano dalle migrazioni Alembic (`astreo_monitor/migrations/`). Come contribuire:
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licenza

[MIT](LICENSE) © 2026 Marco (dogfromberlin)
