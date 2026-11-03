# Modules: Docker and Pi-hole

A module appears in the **Server** view only if the service is **present on the server**; it can be hidden
anyway. State, reason for an absence and visibility in **Settings → Modules**.

| Module | Detection | What it shows | Alerts (event) |
|---|---|---|---|
| **Docker** | `docker` command and daemon reachable by the service user | containers: state, image, health, CPU, memory, restarts | *Docker containers*: stopped, unhealthy or restarting containers |
| **Pi-hole** | v6 API at the configured address | today's queries and blocked ones, clients, blocked domains, lists, blocking state | *Pi-hole*: blocking disabled, Pi-hole not responding |

The alert checks run with the metrics job, every 5 minutes.

<a id="docker"></a>
## Docker

The service user must be able to use Docker without sudo (`docker` group):
```bash
id USER | grep -o docker || sudo usermod -aG docker USER
sudo systemctl restart astreo-monitor-web.service
```

<a id="pihole"></a>
## Pi-hole (v6)

Astreo reads the statistics with an **app password**: dedicated, revocable, different from the administrator
password and not subject to two-factor authentication.

1. In the Pi-hole interface: **Settings → Web interface / API**, **Expert** mode.
2. **Configure app password**: it is shown only once; copy it and press **Enable**.
3. In Astreo, **Settings → Modules → Pi-hole**: address (e.g. `http://127.0.0.1:8080`), app password,
   **Test connection**, **Save modules**.
