# Servizi

Mostra lo stato dei servizi systemd elencati in `[services]`. Solo questi possono
essere interrogati: la 1.x accettava qualsiasi nome di unit.

## Configurazione

```ini
[services]
# chiave = unit systemd | etichetta
openvpn = openvpn | OpenVPN
mssql = mssql-server.service | SQL Server
```
La chiave compare nell'URL (`/api/v1/services/mssql`), l'etichetta in dashboard.

Per aggiungere un servizio (finestra SSH su astreo):
```bash
systemctl list-units --type=service --no-pager | grep -i nome   # trova il nome esatto della unit
nano /etc/astreo-monitor/config.ini                              # aggiungi la riga in [services]
sudo systemctl restart astreo-monitor-web.service
```

## Come funziona

- Elenco: una sola chiamata `systemctl is-active unit1 unit2 ...` (la 1.x ne faceva due per servizio).
- Dettaglio: `systemctl status <unit> --no-pager -l -n 30`, eseguito come utente `<utente>`.
- Stati: `active` = acceso (LED verde); `inactive`, `failed`, `activating`, `unknown` = LED rosso lampeggiante.

## Note

- Se le righe di log nel dettaglio non compaiono, l'utente `<utente>` non può leggere il
  journal di quel servizio. Si risolve aggiungendolo al gruppo `systemd-journal`:
  ```bash
  sudo usermod -aG systemd-journal <utente>
  sudo systemctl restart astreo-monitor-web.service
  ```
- Per OpenVPN la unit reale potrebbe essere `openvpn@server` o `openvpn-server@server`:
  verificarla con `systemctl list-units --no-pager | grep -i openvpn`.
