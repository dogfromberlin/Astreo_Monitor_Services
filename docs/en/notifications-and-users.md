# Notification channels and dashboard users

## Channels

Email, Telegram, WhatsApp (CallMeBot), **ntfy**, **Gotify**, **Discord** and a generic **webhook**. Each one is
enabled and tested in **Settings → Notifications**; the table *Which alerts on which channels* decides which
events go where.

| Channel | What you need |
|---|---|
| ntfy | server (`https://ntfy.sh` or your own) and a **topic**; optional access token. On public ntfy.sh the topic is the only protection: make it long and hard to guess |
| Gotify | server address and an **application token** (Gotify → Apps → Create application) |
| Discord | channel **webhook URL** (Channel settings → Integrations → Webhooks → New webhook → Copy URL) |
| Webhook | a URL receiving a JSON `POST` with `source`, `subject`, `body`, `host`, `time`, `version`; optional secret sent as `Authorization: Bearer …` |

## Users

| User | Access |
|---|---|
| Administrator (`[web] username`) | everything |
| Read-only (`[web] viewer_username`, optional) | **Server** and **Connection** views only: no Settings, Terminal, process list, service details, notification log or changes |

```bash
sudo .venv/bin/python -m astreo_monitor.users list
sudo .venv/bin/python -m astreo_monitor.users password             # change the administrator password
sudo .venv/bin/python -m astreo_monitor.users viewer family        # create / update the read-only user
sudo .venv/bin/python -m astreo_monitor.users viewer --remove
```
