# UPS and power

<a id="come-funziona"></a>
## How it works

Astreo **watches** UPS units and alerts; it **never shuts anything down** by itself. It reads each UPS once a minute
from one of these sources and translates the data into a single model (status, charge, runtime, load, voltages,
temperature, model):

| Source | For | Port |
|---|---|---|
| **NUT** (Network UPS Tools) | almost every brand: APC, Eaton, CyberPower, Riello, Vertiv, Tripp Lite, Salicru… The UPS can be connected by USB to astreo, to a Synology or QNAP NAS (which already have a NUT server) or to any PC with NUT | 3493 |
| **apcupsd** | APC units managed with APC's classic daemon | 3551 |
| **SNMP** | UPS units with a network card (from a next version) | 161 |

<a id="aggiungere"></a>
## Adding a UPS

In **Power → Add a UPS**: name, source, address of the NUT or apcupsd server (127.0.0.1 if the UPS is connected to
astreo) and, for NUT, the UPS name on that server: **Find** lists it. **Test** reads it before saving. On a Synology
NAS the NUT server is enabled in *Control Panel → Hardware & Power → UPS → Enable UPS network server*, adding the IP
of astreo to the permitted devices; the UPS name is `ups`.

<a id="avvisi"></a>
## Alerts

Event **UPS and power** (Settings → Notifications): **blackout** (UPS on battery) at once, **low battery**, **power
back** with the blackout duration, **battery to replace**, **overload**, UPS **unreachable** (after 3 failed reads in
a row). Rules, mutes and Telegram buttons work as for the other alerts; blackout and power back also stay in the
events.

<a id="prova"></a>
## Trying it without a UPS

NUT has a simulation driver, **dummy-ups**, which reads values from a file. On astreo (SSH window):
```bash
cd ~ && sudo apt install -y nut-server
printf 'ups.status: OL\nbattery.charge: 100\nbattery.runtime: 1800\nups.load: 20\ninput.voltage: 230\noutput.voltage: 230\ndevice.mfr: Simulated\ndevice.model: dummy-ups\n' | sudo tee /etc/nut/fake.dev
printf '[fake]\n  driver = dummy-ups\n  port = fake.dev\n  desc = "Test UPS"\n' | sudo tee -a /etc/nut/ups.conf
sudo sed -i 's/^MODE=.*/MODE=netserver/' /etc/nut/nut.conf && echo 'LISTEN 127.0.0.1 3493' | sudo tee -a /etc/nut/upsd.conf
sudo systemctl restart nut.target && sleep 3 && upsc fake@localhost
```
Then in **Power** add the UPS with source NUT, address `127.0.0.1`, name `fake`. To simulate a blackout change the
first line of the file to `ups.status: OB DISCHRG` (and `battery.charge` to 80); for low battery `OB LB`; back to
normal `OL`:
```bash
sudo sed -i 's/^ups.status:.*/ups.status: OB DISCHRG/' /etc/nut/fake.dev
```
