# Connected servers (agents)

One dashboard for several servers: this is the **central server**, the other Linux and Windows servers send their
data through a **lightweight agent**. Agents only send: they open no ports and cannot read anything from the
central server. With the central server alone, the dashboard stays as it always was.

<a id="panoramica"></a>
## Overview and chosen server

With at least one connected server, the **Server** view opens on the **list of servers**: one card per server with
state (green, yellow if it has stopped services or an almost full disk, red if it does not respond), CPU, memory,
fullest disk, services (stopped ones first) and last data received; the same cards are in the Overview. A click
opens the server **detail** (address `#server/<number>`, back to the list from the *Server › name* breadcrumb): its
resources, its history with events (reboots, stopped services), its services, its disks and its
[maintenance](#salute). The central server's maintenance and checks, modules, processes and sensors belong to the
central server only and stay hidden on the other servers. A service
removed from the checked services disappears immediately, without waiting for the next data from the agent.

| Data | Linux | Windows |
|---|---|---|
| CPU, memory, swap / page file, uptime | every 5 minutes | every 5 minutes |
| Disks (all fixed ones; the alert considers the fullest) | mount points | drives C:, D: … |
| Load average | yes | does not exist on Windows |
| Temperatures | yes (`lm-sensors`) | not available |
| Chosen services | systemd, on every change | Windows services, on every change |
| Reboots | yes | yes |
| Disk health (4.2) | SMART, if `smartmontools` is installed; every 6 hours | health status of the physical disks; every 6 hours |
| Updates and reboot required (4.2) | `apt`; every 6 hours | Windows Update; every 6 hours |
| Docker containers (4.2) | if Docker is present; every 5 minutes | if Docker is present; every 5 minutes |

<a id="salute"></a>
### Maintenance of a connected server

With a 4.2 agent the server detail has the **Maintenance** panel: health of each disk (temperature and wear when the
disk provides them), available and security updates, reboot required, Docker containers. The same data appears in
*To check* and raises the *Disk health*, *System updates* and *Docker containers* alerts, with the rules in
[Notifications](notifications.md#regole). On Linux SMART needs the `smartmontools` package (`sudo apt install
smartmontools`). On Windows the update search can take a few minutes: this is why the 4.2 agent's scheduled task has
a 15-minute limit instead of 2.

<a id="impostazioni-server"></a>
## Settings of a server

**Settings of this server** in the server detail, or **Thresholds and alerts** in **Settings → Connected
servers**. Empty fields use the general settings (shown in grey).

| Setting | Meaning |
|---|---|
| Alert when unreachable | when off, a switched-off server shows as grey information (*off*) and sends no alerts: for computers switched off on purpose |
| Unreachable after (minutes) | minutes without data before it counts as unreachable (general: in *Connected servers*) |
| Disk, temperature, CPU and memory thresholds | warning and alert for this server; they apply to the Overview, *To check* and alerts (CPU and memory only if their [alerts](notifications.md#cpu-memoria) are on) |

The central server only has the thresholds. To avoid alerts about short problems there is also **Alert after** in
the [alert rules](notifications.md#regole).

<a id="comandi"></a>
## Commands to services

Since 4.3 the checked services of a connected server can be **started, stopped and restarted** from the dashboard
(**…** button on the right of each service in the server detail; **Start** also in *To check* for a stopped service). Two
consents are needed:

| Where | How |
|---|---|
| on the central server | **Settings of this server → Allow start, stop and restart** |
| on the connected server | agent installed with `-AllowCommands` (Windows) or `--allow-commands` (Linux) |

How it works: no port is opened on the connected server, the command travels in the answer to the data sent and
starts **within a minute**; the result comes back with the next data and stays as an event in the server history
(e.g. *Servizio Spooler riavviato dalla dashboard (admin)*). Every command is **signed** with a key the central server
keeps in a file (not in the database) and that the agent received at installation; it is valid for 10 minutes, bound
to that agent, runs only once and only concerns the checked services. Without the local consent the agent refuses
any command, even a signed one. The read-only user does not see the buttons.

<a id="aggiornare-dashboard"></a>
### Updating the agent from the dashboard (Windows)

With **Allow updating the agent** on and the agent installed with `-AllowUpdate`, when the agent version differs from
the central one the server detail shows **Update agent to …**. The agent receives a signed command, downloads its own
files from the central server, checks signature, hashes and syntax, keeps a copy of the previous ones (`.bak` in
`C:\ProgramData\AstreoAgent`) and from the next round works with the new version; the result stays in the history.
For Linux agents, for now: `sudo bash install.sh --agent … --update` on the connected server.

The installation command shown by **New token** already contains `-AllowCommands` / `-AllowUpdate` if the two switches
of the server are on on the central server.

To give the permission to an agent already installed: generate a **New token** and repeat the installation adding
the option (steps below).

<a id="discontinui"></a>
## On-demand services and newly added services

An **on-demand** service runs only when needed: when stopped it is *idle* (grey), with no alerts and no entry in *To
check*; when running it is green. Start and stop stay in the history as information events. It is chosen when the
service is added: in **Settings → Connected servers** (and in *Add a server*) each service has its own **on demand**
box, which can be changed later in the same row with **Save**; for the central server there is the **On demand**
column in **Settings → Services**. Removing the tick brings the normal check back immediately.

A newly added service shows straight away as *waiting for the first check*: the agent checks it at its next contact,
within a minute. If after 5 minutes it has still not reported its state it becomes *not detected*; if there is no
service with that name on that computer it shows *does not exist on this server* (check the name: on Windows it is the
service name, e.g. `Spooler`, not the display name). **Refresh** in the Services panel makes the agent check all the
services again straight away. Windows Firewall and Defender are *protected*: Windows does not let them be stopped or
restarted, so they have no command buttons.

<a id="aggiungere"></a>
## Adding a server

1. **Settings → Connected servers → Add a server**: name, system, services to check (editable later).
2. The **installation command** appears, with the token (shown only once) and the fingerprint of the central CA.
3. Run it on the new server, as shown below. Within a couple of minutes the server appears in the overview.

The new server must reach the central server on the dashboard port (5443), on the same network or through a VPN.

<a id="linux"></a>
## Linux agent

In the dashboard: **Settings → Connected servers → Add a server**, system *Linux*; copy the command shown.
Then on the server to connect (Ubuntu or Debian with systemd), as a user with `sudo`:
```bash
git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git
cd Astreo_Monitor_Services
sudo bash install.sh --agent https://CENTRAL:5443 --token agt_… --ca-sha256 …
```
The installer downloads the central CA and verifies its fingerprint, stores configuration and token in
`/etc/astreo-agent/` (root only), tests the connection and enables `astreo-agent.timer` (every minute). Update:
`sudo bash update.sh` in the same folder. Test without sending anything:
`sudo .venv/bin/python -m astreo_monitor.agent.run --dry-run`.

<a id="windows"></a>
## Windows agent

Windows 10/11 or Windows Server 2016 and later, with PowerShell 5.1 (already present).

1. In the dashboard: **Settings → Connected servers → Add a server**, system *Windows*; copy the command shown
   (it contains the token and the CA fingerprint).
2. On the Windows server open https://github.com/dogfromberlin/Astreo_Monitor_Services/releases and download the zip
   of the latest version.
3. Right-click the zip → **Extract all…** → folder `C:\AstreoAgentSetup`.
4. **Start** → type `PowerShell` → right-click **Windows PowerShell** → **Run as administrator**.
5. In the window (the second command removes the block Windows puts on downloaded files), then the copied command:
```powershell
cd C:\AstreoAgentSetup
Get-ChildItem -Recurse | Unblock-File
powershell -ExecutionPolicy Bypass -File .\agent\windows\install-agent.ps1 -Central https://CENTRAL:5443 -Token agt_… -CaSha256 …
```
6. *Connection to the central server: OK* must appear. Check: `Get-ScheduledTask -TaskName 'Astreo Monitor Agent'`
   (state *Ready*) and, after a couple of minutes, `Get-Content C:\ProgramData\AstreoAgent\agent.log -Tail 5`.

To **update** the agent or use a **new token**: download the new zip, generate the command from the dashboard
(**New token**) and repeat steps 3–5; the installation replaces the previous one.
The script verifies the CA, stores configuration and queue in `C:\ProgramData\AstreoAgent\` (SYSTEM and
administrators only), tests the connection and creates the scheduled task **Astreo Monitor Agent** (every minute,
as SYSTEM). The log is `C:\ProgramData\AstreoAgent\agent.log`. To remove it: the same script with `-Uninstall`.

<a id="sicurezza"></a>
## Security

| Protection | How |
|---|---|
| One token per server | generated by the dashboard, only its fingerprint in the database; **New token** invalidates the previous one immediately |
| Send only | the agent reads nothing from the central server: it only receives the list of its own services to check |
| Certificate | the agent verifies the central server with its CA, without installing it in the system |
| Validation | every value is checked; an invalid item is discarded on its own, the rest of the delivery accepted |
| Limits | at most 1 MB and 30 deliveries per minute per agent |

<a id="avvisi"></a>
## Alerts and queue

Every minute the central server checks the connected servers: **unreachable** if an agent has sent no data for
10 minutes (editable in **Settings → Connected servers**), disk and temperature with the central thresholds, stopped services.
Alerts use the usual rules and channels (event *Connected servers*, and *Disk*, *Temperature*, *Services* for the
others), with the server name in the subject. The bot shows the connected servers in `/status`.

If the central server does not respond, the agent keeps the data in a queue and sends it in order as soon as it is
reachable again; data older than 24 hours is discarded.

<a id="problemi"></a>
## Common problems

| Symptom | Likely cause |
|---|---|
| *the CA fingerprint does not match* | wrong address, or someone is in between: do not continue |
| *central certificate not valid for the address used* | use an IP or a name present in the central certificate |
| *token rejected* | wrong or regenerated token: **New token** and reinstall with it |
| the server stays *waiting for the first delivery* | timer or scheduled task stopped, or central server unreachable: see the agent log |
