# Moduli: Docker e Pi-hole

Un modulo compare nella vista **Server** solo se il servizio è **presente sul server**; si può comunque
nascondere. Stato, motivo dell'eventuale assenza e visibilità in **Impostazioni → Moduli**.

| Modulo | Rilevamento | Cosa mostra | Avvisi (evento) |
|---|---|---|---|
| **Docker** | comando `docker` e daemon raggiungibile dall'utente dei servizi | container: stato, immagine, salute, CPU, memoria, riavvii | *Container Docker*: container fermi, non sani o che si riavviano |
| **Pi-hole** | API v6 all'indirizzo configurato | richieste e bloccate di oggi, client, domini in blocco, liste, stato del blocco | *Pi-hole*: blocco disattivato, Pi-hole che non risponde |

I controlli per gli avvisi girano con il job delle metriche, ogni 5 minuti.

<a id="docker"></a>
## Docker

L'utente dei servizi deve poter usare Docker senza sudo (gruppo `docker`):
```bash
id UTENTE | grep -o docker || sudo usermod -aG docker UTENTE
sudo systemctl restart astreo-monitor-web.service
```

<a id="pihole"></a>
## Pi-hole (v6)

Astreo legge le statistiche con una **password per le app**: dedicata, revocabile, diversa dalla password di
amministratore e non soggetta all'autenticazione a due fattori.

1. Nell'interfaccia di Pi-hole: **Impostazioni → Interfaccia web / API**, modalità **Esperto**.
2. **Configura password per le app**: viene mostrata una sola volta; copiala e premi **Abilita**.
3. In Astreo, **Impostazioni → Moduli → Pi-hole**: indirizzo (es. `http://127.0.0.1:8080`), password per le
   app, **Prova la connessione**, **Salva moduli**.
