# UPS e alimentazione

<a id="come-funziona"></a>
## Come funziona

Astreo **osserva** gli UPS e avvisa; **non spegne nulla** da solo. Legge ogni UPS una volta al minuto da una di
queste fonti, e traduce i dati in un modello unico (stato, carica, autonomia, carico, tensioni, temperatura, modello):

| Fonte | Per chi | Porta |
|---|---|---|
| **NUT** (Network UPS Tools) | quasi tutte le marche: APC, Eaton, CyberPower, Riello, Vertiv, Tripp Lite, Salicru… L'UPS può essere collegato via USB ad astreo, a un NAS Synology o QNAP (che hanno già un server NUT) o a qualsiasi PC con NUT | 3493 |
| **apcupsd** | UPS APC gestiti con il programma storico di APC | 3551 |
| **SNMP** | UPS con scheda di rete (da una prossima versione) | 161 |

<a id="aggiungere"></a>
## Aggiungere un UPS

In **Alimentazione → Aggiungi un UPS**: nome, fonte, indirizzo del server NUT o apcupsd (127.0.0.1 se l'UPS è
collegato ad astreo) e, per NUT, il nome dell'UPS su quel server: **Cerca** lo elenca da solo. **Prova** fa una
lettura prima di salvare. Su un NAS Synology il server NUT si attiva in *Pannello di controllo → Hardware e
alimentazione → UPS → Abilita server di rete UPS*, aggiungendo l'IP di astreo ai dispositivi autorizzati; il nome
dell'UPS è `ups`.

<a id="avvisi"></a>
## Avvisi

Evento **UPS e alimentazione** (Impostazioni → Notifiche): **blackout** (UPS a batteria) subito, **batteria
scarica**, **corrente tornata** con la durata del blackout, **batteria da sostituire**, **sovraccarico**, UPS
**non raggiungibile** (dopo 3 letture fallite di fila). Valgono regole, silenzi e pulsanti di Telegram come per gli
altri avvisi; blackout e ritorno della corrente restano anche negli eventi.

<a id="prova"></a>
## Provare senza un UPS

NUT ha un driver di simulazione, **dummy-ups**, che legge i valori da un file. Su astreo (finestra SSH):
```bash
cd ~ && sudo apt install -y nut-server
printf 'ups.status: OL\nbattery.charge: 100\nbattery.runtime: 1800\nups.load: 20\ninput.voltage: 230\noutput.voltage: 230\ndevice.mfr: Simulato\ndevice.model: dummy-ups\n' | sudo tee /etc/nut/finto.dev
printf '[finto]\n  driver = dummy-ups\n  port = finto.dev\n  desc = "UPS di prova"\n' | sudo tee -a /etc/nut/ups.conf
sudo sed -i 's/^MODE=.*/MODE=netserver/' /etc/nut/nut.conf && echo 'LISTEN 127.0.0.1 3493' | sudo tee -a /etc/nut/upsd.conf
sudo systemctl restart nut.target && sleep 3 && upsc finto@localhost
```
Poi in **Alimentazione** aggiungi l'UPS con fonte NUT, indirizzo `127.0.0.1`, nome `finto`. Per simulare un
blackout cambia la prima riga del file in `ups.status: OB DISCHRG` (e `battery.charge` a 80); per la batteria scarica
`OB LB`; per tornare alla normalità `OL`:
```bash
sudo sed -i 's/^ups.status:.*/ups.status: OB DISCHRG/' /etc/nut/finto.dev
```
