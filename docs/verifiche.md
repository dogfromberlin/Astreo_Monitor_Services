# Verifiche e diagnosi

Tre strumenti, nati dagli intoppi delle installazioni precedenti (script SQL non eseguiti, unit
systemd non copiate, `sed` senza permessi, `http2` non supportato, dashboard non riavviata).

| Strumento | Quando | Cosa controlla |
|---|---|---|
| `bash scripts/verifica.sh` | dopo aver estratto un pacchetto, **prima** di installarlo | codice Python, JavaScript, test automatici, file di installazione |
| `sudo .venv/bin/python -m astreo_monitor.doctor` | **dopo** l'installazione (e quando qualcosa non torna) | config, database, dashboard, servizi systemd, file installati, dati recenti |
| Banner nella dashboard | sempre | database incompleto, pagina di una versione diversa dal server |

A questi si aggiunge **GitHub Actions**: a ogni push le stesse verifiche girano su GitHub; l'esito
compare nella scheda *Actions* del repository e accanto a ogni commit (✔ o ✘).

## Verifica del pacchetto

**SSH**
```bash
cd ~/Astreo_Monitor_Services
bash scripts/verifica.sh
```
La prima volta installa nel venv `pytest` e `pyflakes` (`requirements-dev.txt`). Termina con
**VERIFICHE SUPERATE** oppure **VERIFICHE FALLITE**: in questo caso non installare e segnala l'errore.

I test in `tests/test_installazione.py` contengono una regola per ogni errore già incontrato, ad esempio:

| Regola | Errore evitato |
|---|---|
| niente `http2 on;` nei file nginx | nginx 1.24 non lo riconosce e il reload fallisce |
| `sed -i` su `/etc` sempre con `sudo` nella documentazione | la modifica non avviene e non te ne accorgi |
| niente `ReadWritePaths=/var/lib/...` nelle unit | servizio che non parte (226/NAMESPACE) |
| `AmbientCapabilities=CAP_NET_RAW` per il ping | connessione sempre DOWN |
| `data-view` solo sulle viste | schermata nera passando da una sezione all'altra |
| niente `GO` dentro i commenti SQL | script interrotto a metà in SSMS |
| ogni tabella attesa creata dallo script indicato | indicazioni sbagliate del controllo dello schema |

## Diagnosi dell'installazione

**SSH**
```bash
cd ~/Astreo_Monitor_Services
sudo .venv/bin/python -m astreo_monitor.doctor
```
Per ogni voce: ✔ ok, ⚠ da controllare, ✘ errore, · non verificabile. Sotto ogni problema compare il
comando per correggerlo. Controlla tra l'altro:

- **configurazione**: permessi, `[web]` dietro nginx (`host`, `trusted_proxy`), terminale;
- **database**: connessione, tabelle, colonne, procedure e permessi attesi, con lo script da eseguire;
- **dashboard**: risponde in HTTPS con il certificato della CA e **esegue la stessa versione del codice**
  (altrimenti va riavviata);
- **servizi systemd**: ogni unit del progetto è installata, **identica** a quella del progetto, caricata
  (`daemon-reload`), abilitata e attiva; `ttyd.service` del pacchetto spento;
- **file installati**: script SMART, regola polkit, siti nginx;
- **dati recenti**: ogni job ha scritto da poco (metriche, connessione, IP, scadenze, backup, salute).

Senza `sudo` alcuni file riservati risultano *non verificabili*. Codice di uscita 0 = nessun errore.

Solo lo schema del database: `.venv/bin/python -m astreo_monitor.schema`
