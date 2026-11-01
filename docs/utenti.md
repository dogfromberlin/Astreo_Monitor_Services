# Utenti della dashboard

| Utente | Accesso |
|---|---|
| **Amministratore** (`[web] username`) | tutto |
| **Sola lettura** (`[web] viewer_username`, facoltativo) | viste **Server** e **Connessione**; niente Impostazioni, Terminale, elenco dei processi, dettaglio dei servizi (`systemctl status`), registro delle notifiche, né qualsiasi modifica |

Utile per mostrare la dashboard a qualcuno o su uno schermo, senza dare accesso a configurazione e comandi.

## Comandi

**SSH**, dalla cartella del progetto:
```bash
sudo .venv/bin/python -m astreo_monitor.users list                  # mostra gli utenti
sudo .venv/bin/python -m astreo_monitor.users password              # cambia la password dell'amministratore
sudo .venv/bin/python -m astreo_monitor.users viewer famiglia       # crea o aggiorna l'utente in sola lettura
sudo .venv/bin/python -m astreo_monitor.users viewer --remove       # lo elimina
```
Le password sono chieste a terminale e salvate solo come hash nel config, che resta con i suoi permessi.
La dashboard viene riavviata in automatico.
