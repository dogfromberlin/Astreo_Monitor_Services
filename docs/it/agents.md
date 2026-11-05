# Server collegati (agenti)

Una sola dashboard per più server: questo è il **server centrale**, gli altri server Linux e Windows inviano i
loro dati con un **agente leggero**. Gli agenti inviano soltanto: non aprono porte e non possono leggere nulla dal
centrale. Con il solo centrale la dashboard resta quella di sempre.

<a id="panoramica"></a>
## Panoramica e server scelto

Con almeno un server collegato, la vista **Server** si apre sull'**elenco dei server**: una scheda per server con
stato (verde, giallo se ha servizi fermi o il disco quasi pieno, rosso se non risponde), CPU, memoria, disco più
pieno, servizi (prima quelli fermi) e ultimo invio; le stesse schede sono nella Panoramica. Un clic apre il
**dettaglio** del server (indirizzo `#server/<numero>`, si torna all'elenco dal percorso *Server › nome*): le sue
risorse, il suo storico con gli eventi (riavvii, servizi fermi), i suoi servizi e i suoi dischi. Manutenzione e
controlli, moduli, processi e sensori sono del solo centrale e restano nascosti negli altri server. Un servizio tolto
dai servizi controllati sparisce subito, senza aspettare il prossimo invio dell'agente.

| Dato | Linux | Windows |
|---|---|---|
| CPU, memoria, swap / file di paging, uptime | ogni 5 minuti | ogni 5 minuti |
| Dischi (tutti quelli fissi; l'avviso considera il più pieno) | punti di montaggio | unità C:, D: … |
| Load average | sì | non esiste su Windows |
| Temperature | sì (`lm-sensors`) | non disponibili |
| Servizi scelti | systemd, a ogni cambio | servizi di Windows, a ogni cambio |
| Riavvii | sì | sì |

<a id="impostazioni-server"></a>
## Impostazioni di un server

**Impostazioni di questo server** nel dettaglio del server, oppure **Soglie e avvisi** in **Impostazioni → Server
collegati**. I campi vuoti usano le impostazioni generali (mostrate in grigio).

| Impostazione | Significato |
|---|---|
| Avvisa se non raggiungibile | disattivato, un server spento compare come informazione grigia (*spento*) e non manda avvisi: per i computer che si spengono volutamente |
| Non raggiungibile dopo (minuti) | minuti senza dati prima di considerarlo non raggiungibile (generale: in *Server collegati*) |
| Soglie di disco e temperatura | avviso e allarme per questo server; valgono per Panoramica, *Da controllare* e avvisi |

Il server centrale ha solo le soglie. Per non ricevere avvisi su problemi brevi c'è anche **Avvisa dopo** nelle
[regole di avviso](notifications.md#regole).

<a id="aggiungere"></a>
## Aggiungere un server

1. **Impostazioni → Server collegati → Aggiungi un server**: nome, sistema, servizi da controllare (modificabili poi).
2. Compare il **comando d'installazione** con il token (mostrato una sola volta) e l'impronta della CA del centrale.
3. Eseguilo sul nuovo server, come indicato sotto. Entro un paio di minuti il server compare nella panoramica.

Il nuovo server deve raggiungere il centrale sulla porta della dashboard (5443), nella stessa rete o tramite VPN.

<a id="linux"></a>
## Agente Linux

Nella dashboard: **Impostazioni → Server collegati → Aggiungi un server**, sistema *Linux*; copia il comando mostrato.
Poi sul server da collegare (Ubuntu o Debian con systemd), come utente con `sudo`:
```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh --agent https://CENTRALE:5443 --token agt_… --ca-sha256 …
```
L'installatore scarica la CA del centrale e ne verifica l'impronta, salva configurazione e token in
`/etc/astreo-agent/` (solo root), prova il collegamento e attiva `astreo-agent.timer` (ogni minuto). Aggiornamento:
`sudo bash update.sh` nella stessa cartella. Prova senza inviare nulla:
`sudo .venv/bin/python -m astreo_monitor.agent.run --dry-run`.

<a id="windows"></a>
## Agente Windows

Windows 10/11 o Windows Server 2016 e successivi, con PowerShell 5.1 (già presente).

1. Nella dashboard: **Impostazioni → Server collegati → Aggiungi un server**, sistema *Windows*; copia il comando
   mostrato (contiene token e impronta della CA).
2. Sul server Windows apri https://github.com/dogfromberlin/Astreo_Monitor_Services/releases e scarica lo zip
   dell'ultima versione.
3. Tasto destro sullo zip → **Estrai tutto…** → cartella `C:\AstreoAgentSetup`.
4. **Start** → scrivi `PowerShell` → tasto destro su **Windows PowerShell** → **Esegui come amministratore**.
5. Nella finestra (il secondo comando toglie il blocco che Windows mette sui file scaricati), poi il comando copiato:
```powershell
cd C:\AstreoAgentSetup
Get-ChildItem -Recurse | Unblock-File
powershell -ExecutionPolicy Bypass -File .\agent\windows\install-agent.ps1 -Central https://CENTRALE:5443 -Token agt_… -CaSha256 …
```
6. Deve comparire *Collegamento al server centrale: OK*. Controllo: `Get-ScheduledTask -TaskName 'Astreo Monitor Agent'`
   (stato *Ready*) e, dopo un paio di minuti, `Get-Content C:\ProgramData\AstreoAgent\agent.log -Tail 5`.

Per **aggiornare** l'agente o usare un **nuovo token**: scarica il nuovo zip, genera il comando dalla dashboard
(**Nuovo token**) e ripeti i passi 3–5; l'installazione sostituisce quella precedente.
Lo script verifica la CA, salva configurazione e coda in `C:\ProgramData\AstreoAgent\` (solo SYSTEM e
amministratori), prova il collegamento e crea l'attività pianificata **Astreo Monitor Agent** (ogni minuto, come
SYSTEM). Il registro è `C:\ProgramData\AstreoAgent\agent.log`. Per rimuoverlo: lo stesso script con `-Uninstall`.

<a id="sicurezza"></a>
## Sicurezza

| Protezione | Come |
|---|---|
| Un token per server | generato dalla dashboard, nel database solo la sua impronta; **Nuovo token** invalida subito il precedente |
| Solo invio | l'agente non legge nulla dal centrale: riceve solo l'elenco dei propri servizi da controllare |
| Certificato | l'agente verifica il centrale con la sua CA, senza installarla nel sistema |
| Validazione | ogni valore è controllato; un elemento non valido viene scartato da solo, il resto dell'invio accettato |
| Limiti | al massimo 1 MB e 30 invii al minuto per agente |

<a id="avvisi"></a>
## Avvisi e coda

Ogni minuto il centrale controlla i server collegati: **non raggiungibile** se un agente non invia dati da
10 minuti (modificabile in **Impostazioni → Server collegati**), disco e temperatura con le soglie del centrale, servizi fermi.
Gli avvisi usano regole e canali di sempre (evento *Server collegati*, e *Disco*, *Temperatura*, *Servizi* per gli
altri), con il nome del server nell'oggetto. Il bot mostra i server collegati in `/stato`.

Se il centrale non risponde, l'agente conserva i dati in coda e li invia in ordine appena torna raggiungibile;
i dati più vecchi di 24 ore vengono scartati.

<a id="problemi"></a>
## Problemi frequenti

| Sintomo | Causa probabile |
|---|---|
| *l'impronta della CA non coincide* | indirizzo sbagliato, oppure qualcuno si interpone: non proseguire |
| *certificato del centrale non valido per l'indirizzo usato* | usa un IP o un nome presenti nel certificato del centrale |
| *token rifiutato* | token sbagliato o rigenerato: **Nuovo token** e reinstalla con quello |
| il server resta *in attesa del primo invio* | timer o attività pianificata fermi, oppure centrale non raggiungibile: vedi il registro dell'agente |
