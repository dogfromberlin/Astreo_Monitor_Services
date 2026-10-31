# Moduli opzionali: Docker e Pi-hole

Un modulo compare nella vista **Server** solo se il servizio è **presente sul server**; anche se
presente, si può nascondere. Stato e visibilità in **Impostazioni → Moduli**.

| Modulo | Rilevamento | Cosa mostra | Avvisi (evento) |
|---|---|---|---|
| **Docker** | comando `docker` installato e daemon raggiungibile dall'utente del servizio | container con stato, immagine, salute, CPU, memoria, riavvii | *Container Docker*: un container con riavvio automatico (`always`, `unless-stopped`, `on-failure`) fermo o in riavvio continuo; WARNING se *unhealthy* |
| **Pi-hole** | API v6 che risponde all'indirizzo configurato | richieste e bloccate di oggi, client attivi, domini in blocco, aggiornamento delle liste, stato del blocco | *Pi-hole*: blocco disattivato (WARNING) o Pi-hole che non risponde (ALERT) |

Il controllo per gli avvisi gira nel job delle metriche, ogni 5 minuti. Regole e canali in
**Impostazioni → Notifiche**.

## Docker

L'utente del servizio (`<utente>`) deve poter usare Docker senza sudo, cioè essere nel gruppo `docker`:
```bash
id <utente> | grep -o docker || sudo usermod -aG docker <utente>
```
Dopo l'aggiunta al gruppo: `sudo systemctl restart astreo-monitor-web.service`.
Se Docker non è installato, o l'utente non ha accesso, la scheda Moduli ne indica il motivo.

## Pi-hole (v6)

Astreo legge le statistiche con una **password per le app**: dedicata, revocabile, diversa dalla
password di amministratore e non soggetta all'autenticazione a due fattori.

1. Apri l'interfaccia di Pi-hole (es. `http://<IP-LAN>:8080/admin`) e accedi.
2. **Impostazioni → Interfaccia web / API**; in alto a destra passa da *Base* a **Esperto**.
3. Premi **Configura password per le app**: Pi-hole ne genera una e la mostra **una sola volta**. Copiala.
4. Premi **Abilita la nuova password per le app**.
5. In Astreo: **Impostazioni → Moduli → Pi-hole**: indirizzo `http://127.0.0.1:8080` (Pi-hole sullo
   stesso server) e password per le app → **Prova la connessione** → **Salva moduli**.

Pi-hole limita il numero di sessioni contemporanee: Astreo riusa la stessa sessione finché è valida e
chiude quella dei controlli periodici a ogni esecuzione.

## Aggiungere un modulo

Il progetto è predisposto per altri moduli: un file in `astreo_monitor/integrations/` con `detect()` e i
dati, una voce in `MODULES` (`integrations/__init__.py`), una sezione nella pagina con
`id="mod-<chiave>" class="panel module" hidden` e un'impostazione `ui.<chiave>`.
