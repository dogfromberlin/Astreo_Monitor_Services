# Controlli di altri dispositivi e servizi

Astreo può controllare anche altri dispositivi e servizi della rete o di Internet: router, NAS, stampanti,
telecamere, siti web, servizi su altri computer.

| Tipo | Cosa verifica | Esempi |
|---|---|---|
| **Ping** | che il dispositivo risponda in rete (3 pacchetti) | router, NAS, stampante |
| **Porta TCP** | che un servizio sia in ascolto su una porta | SMB 445, SSH 22, un database |
| **Pagina web** | che l'indirizzo risponda con un codice atteso (predefinito 200-399), facoltativamente che contenga un testo, e che il certificato HTTPS non sia in scadenza | sito, pannello del router, Home Assistant |

## Configurazione

**Impostazioni → Dispositivi**: nome, tipo, host o indirizzo, porta (TCP), ogni quanti secondi (minimo 30),
attesa massima, fallimenti consecutivi prima dell'avviso, e per le pagine web codici attesi, testo da cercare,
verifica del certificato e giorni di preavviso. **Prova ora** esegue il controllo senza salvarlo.

## Stati

| Stato | Quando |
|---|---|
| OK | il controllo riesce |
| WARNING | riesce, ma con un'anomalia: certificato in scadenza, metà dei ping persi |
| DOWN | fallisce per il numero di volte consecutive indicato (predefinito 2: un singolo ping perso non è un guasto) |

## Dove si vedono

- **Server → Dispositivi e servizi**: stato, latenza, disponibilità delle ultime 24 ore; un clic apre lo storico
  di latenza e raggiungibilità (24 ore, 7 o 30 giorni).
- **Eventi sui grafici**: ogni passaggio a DOWN e ritorno.
- **Avvisi**: evento *Dispositivi e servizi* (regola e canali in **Impostazioni → Notifiche**; predefinito: a ogni
  cambio, con avviso di rientro).
- **Bot Telegram**: `/controlli`. **Riepilogo settimanale**: disponibilità di ciascun controllo.

Job: `astreo_monitor.jobs.checks`, timer `astreo-checks.timer` (ogni minuto; ciascun controllo col suo
intervallo). Risultati conservati come il controllo della connessione (`[retention] connectivity_days`, 90 giorni).
