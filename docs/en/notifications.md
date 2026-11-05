# Notifications

<a id="canali"></a>
## Channels

| Channel | What you need |
|---|---|
| **Email** | SMTP server, port, security (SSL 465 / STARTTLS 587), user and password; with Gmail an *app password* |
| **Telegram** (recommended) | a bot token (from **@BotFather**, command `/newbot`) and the Chat ID |
| **WhatsApp** | through the free CallMeBot service: number with country code without `+` and API key; no service guarantees |
| **ntfy** | server (`https://ntfy.sh` or your own) and topic; optional token. On public ntfy.sh the topic is the only protection: make it long |
| **Gotify** | server address and an application token |
| **Discord** | the channel's webhook URL |
| **Webhook** | a URL receiving a JSON `POST` (`source`, `subject`, `body`, `host`, `time`, `version`); optional secret as `Authorization: Bearer` |

Each channel is enabled and tested from **Settings → Notifications** (**Send test**). Tokens, passwords and
webhook URLs are secrets: they are never shown.

<a id="telegram"></a>
## Setting up Telegram

1. In Telegram open **@BotFather**, send `/newbot`, choose name and username: you get the **token**.
2. Send any message to the new bot (a bot cannot write to you first); for a group, add the bot to the group and
   send `/start@botname`.
3. Get the **Chat ID** (on the server):
   ```bash
   read -rsp 'Bot token: ' T; echo
   curl -s "https://api.telegram.org/bot$T/getUpdates" | python3 -c "import json,sys; [print(u[k]['chat']['id'], u[k]['chat'].get('title') or u[k]['chat'].get('first_name','')) for u in json.load(sys.stdin)['result'] for k in ('message','my_chat_member') if k in u]"
   unset T
   ```
   For a group the Chat ID is negative.
4. **Settings → Notifications**: token, Chat ID, enable, **Save notifications**, **Send test**.

<a id="instradamento"></a>
## Which alerts on which channels

The table at the bottom of the Notifications tab decides, for each event (connection, speedtest, temperature,
disk, services, backup, public IP, expirations, disks, updates, restore check, devices, Docker, Pi-hole, weekly
summary), which channels it goes to.

<a id="regole"></a>
## Alert rules

For each monitor:

| Option | Meaning |
|---|---|
| **Only if it gets worse** | alerts for OK → WARNING → ALERT/DOWN; no alert if it stays the same or improves |
| **On every change** | alerts on every state change |
| **Recovery alert** | alerts also when it goes back to OK |
| **Reminder (hours)** | repeats the alert if the situation stays abnormal for the given hours (0 = never) |
| **Alert after (min)** | the alert is sent only if the problem lasts at least these minutes in a row (0 = immediately) |

With **Alert after**, a problem that clears before the given time sends nothing, neither the alert nor the
recovery: useful for short line outages (Connection at 3 minutes) or for a service that restarts by itself. The
dashboard and the history still show every problem, even a one-minute one, and count it in the availability. The
reminder starts only after the first alert has been sent.

<a id="cpu-memoria"></a>
## CPU and memory alerts

Off by default: they are turned on in **Settings → Notifications → CPU and memory alerts**. General thresholds (CPU
warning 90%, alert 98%; memory warning 90%, alert 97%) apply to all servers; each server can have its own in
**Settings of this server** ([connected servers](agents.md#impostazioni-server)).

CPU and memory are measured every 5 minutes, on the central server and on the agents. The *CPU* and *Memory* rules
have **Alert after** 15 and 10 minutes by default: the alert is sent only for a sustained load, not for the peaks
of updates or backups. For the central server the alert also lists the three processes using the most CPU or
memory. With the alerts on, a load above the thresholds also appears in *To check*.

<a id="silenzio"></a>
## Quiet hours

Start, end and delivery time (e.g. 23:00–07:00, delivery at 08:00). Alerts raised during quiet hours are held and
delivered at the set time, **one message per channel**, with the detection time. Test messages are never held.
The delivery log shows the *Queued* alerts.

<a id="heartbeat"></a>
## External heartbeat

Astreo cannot warn you if it is off or offline. The heartbeat solves this: every 5 minutes it tells an external
service it is alive (e.g. **healthchecks.io**, free); if the signals stop, the external service alerts you. On
healthchecks.io: create a check with period 5 minutes and grace 10, copy the *ping URL* into
**Settings → Notifications → External heartbeat**, enable and **Send test ping**.

<a id="bot"></a>
## Telegram bot commands

With **Reply to commands** enabled, the bot answers **only** in the configured chat (commands from other chats are
ignored and logged):

| Command | Reply |
|---|---|
| `/status` · `/stato` | CPU, RAM, disk, temperature, connection, stopped services, active alarms |
| `/connection` · `/connessione` | ping, availability over the last 24 hours, last speedtest |
| `/speedtest` | runs a speedtest and sends the result |
| `/services` · `/servizi` | state of the monitored services |
| `/checks` · `/controlli` | disks, updates, expirations, backup, restore, heartbeat, devices |
| `/help` · `/aiuto` | list of commands |

<a id="riepilogo"></a>
## Weekly summary

Every Monday at 08:00, on the channels chosen for *Weekly summary*: availability and outages, speedtest,
resources, alerts sent, devices, backup and restore check, disks, updates, expirations.
**Send the weekly summary now** sends it immediately, as a test.
