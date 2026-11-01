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
| **Dispositivi e servizi** | Controlli ping, porta TCP e pagina web di altri dispositivi (router, NAS, siti…) con storico e avvisi ([controlli.md](docs/controlli.md)) |
| **Connessione** | Ping verso router e Internet ogni minuto (interruzioni, disponibilità), speedtest periodico con soglie, cambi di IP pubblico |
| **Salute** | Stato SMART dei dischi, aggiornamenti di sicurezza in sospeso e riavvii richiesti, scadenze di certificati e token |
| **Sicurezza dei dati** | Backup notturno del database (con copia facoltativa su un repository GitHub privato) e **verifica mensile del ripristino** |
| **Avvisi** | Email, Telegram, WhatsApp (CallMeBot), ntfy, Gotify, Discord, webhook; regole per controllo (solo se peggiora / a ogni cambio, promemoria, rientro), fascia di silenzio, heartbeat esterno (healthchecks.io) |
| **Bot Telegram** | `/stato`, `/connessione`, `/speedtest`, `/servizi`, `/controlli`, `/aiuto` (anche in inglese) |
| **Moduli** | Container Docker e Pi-hole (v6): compaiono solo se presenti sul server |
| **Utenti** | Amministratore e un utente facoltativo in sola lettura ([utenti.md](docs/utenti.md)) |
| **Terminale web** | Shell nel browser protetta da una password separata (solo HTTPS) |
| **Riepilogo settimanale** | Ogni lunedì mattina |
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
Dettagli: [docs/installazione-guidata.md](docs/installazione-guidata.md).

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

| Argomento | Documento |
|---|---|
| Installazione e aggiornamento | [installazione-guidata.md](docs/installazione-guidata.md) |
| Architettura e configurazione | [architettura.md](docs/architettura.md), [configurazione.md](docs/configurazione.md) |
| Dashboard e API | [dashboard-e-api.md](docs/dashboard-e-api.md), [impostazioni.md](docs/impostazioni.md) |
| Metriche, servizi, connessione | [metriche-e-temperature.md](docs/metriche-e-temperature.md), [servizi.md](docs/servizi.md), [connessione.md](docs/connessione.md), [speedtest.md](docs/speedtest.md), [ip-pubblico.md](docs/ip-pubblico.md) |
| Avvisi | [notifiche.md](docs/notifiche.md), [heartbeat.md](docs/heartbeat.md) |
| Salute e scadenze | [salute-del-sistema.md](docs/salute-del-sistema.md), [scadenze.md](docs/scadenze.md) |
| Database e backup | [database.md](docs/database.md), [backup-database.md](docs/backup-database.md) |
| Moduli ed eventi | [moduli.md](docs/moduli.md), [eventi.md](docs/eventi.md) |
| HTTPS e terminale | [certificato.md](docs/certificato.md), [terminale.md](docs/terminale.md) |
| Verifiche, operatività, traduzioni | [verifiche.md](docs/verifiche.md), [operativita.md](docs/operativita.md), [traduzioni.md](docs/traduzioni.md) |

## Sviluppo

```bash
bash scripts/verifica.sh        # pyflakes, sintassi JavaScript, circa 150 test
```
I test girano su SQLite in locale e su SQLite, PostgreSQL e SQL Server su GitHub Actions. Le modifiche allo
schema passano dalle migrazioni Alembic (`astreo_monitor/migrations/`). Come contribuire:
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licenza

[MIT](LICENSE) © 2026 Marco (dogfromberlin)
