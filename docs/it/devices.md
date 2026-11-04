# Dispositivi e servizi

Controlli di altri dispositivi e servizi della rete o di Internet: router, NAS, stampanti, telecamere, siti web,
servizi su altri computer.

<a id="tipi"></a>
## Tipi di controllo

| Tipo | Cosa verifica | Esempi |
|---|---|---|
| **Ping** | che il dispositivo risponda in rete (3 pacchetti) | router, NAS, stampante |
| **Porta TCP** | che un servizio sia in ascolto su una porta | SMB 445, SSH 22, un database |
| **Pagina web** | codice di risposta atteso (predefinito 200-399), testo facoltativo nella pagina, scadenza del certificato HTTPS | sito, pannello web, Home Assistant |

<a id="configurazione"></a>
## Configurazione

**Impostazioni → Dispositivi**: nome, tipo, host o indirizzo, porta (TCP), ogni quanti secondi (minimo 30),
attesa massima, **fallimenti consecutivi prima dell'avviso** (predefinito 2: un singolo ping perso non è un
guasto) e, per le pagine web, codici attesi, testo da cercare, verifica del certificato e giorni di preavviso.
**Prova ora** esegue il controllo senza salvarlo.

<a id="stati"></a>
## Stati

| Stato | Quando |
|---|---|
| OK | il controllo riesce |
| WARNING | riesce, ma con un'anomalia: certificato in scadenza, metà dei ping persi |
| DOWN | fallisce per il numero di volte consecutive indicato |

<a id="dove"></a>
## Dove si vedono

- Sezione **Dispositivi**: stato, latenza, disponibilità nelle ultime 24 ore; un clic apre lo storico (24 ore, 7
  o 30 giorni). Un controllo che non risponde compare anche in **Da controllare** nella Panoramica.
- Eventi sui grafici, avvisi (evento **Dispositivi e servizi**), comando `/controlli` del bot, riepilogo settimanale.

`astreo-checks.timer` gira ogni minuto; ciascun controllo segue il suo intervallo. Risultati conservati 90 giorni.
