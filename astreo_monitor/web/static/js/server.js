/* Astreo Monitor - vista Server: risorse in tempo reale, servizi, storico. */
(() => {
  "use strict";
  const { t, $, $$, api, el, row, fmtNum, fmtGB, fmtTime, fmtDateTime, fmtUptime, level, C, PALETTE, drawChart, ds, every } = window.AM;
  window.AM.setGauge = (...a) => setGauge(...a);
  const REFRESH = { system: 10_000, processes: 10_000, services: 60_000, temps: 60_000, network: 300_000, history: 300_000 };
  const state = { range: "24h", custom: null };
  const remote = () => (window.AM.host || 1) !== 1;            // 4.0: server collegato scelto nella panoramica
  const hostQ = () => (remote() ? `&host=${window.AM.host}` : "");

  function setGauge(id, value, cls, sub) {
    const g = $(id);
    g.classList.remove("ok", "warn", "alert");
    if (cls) g.classList.add(cls);
    g.querySelector(".value span").textContent = fmtNum(value, value >= 100 ? 0 : 1);
    g.querySelector(".bar i").style.width = `${Math.max(0, Math.min(100, value))}%`;
    if (sub !== undefined) g.querySelector(".sub").textContent = sub;
  }

  // --------------------------------------------------------- tempo reale
  async function loadSystem() {
    try {
      const s = await api("/api/v1/system");
      $("#hostname").textContent = s.hostname;
      $("#uptime").textContent = fmtUptime(s.uptime.uptime_s);
      $("#last-update").textContent = fmtTime();
      if (remote()) return;                                    // la testata resta del centrale
      setGauge("#g-cpu", s.cpu_pct, level(s.cpu_pct, 70, 90), t("load {p0} / {p1} / {p2} su {p3} core", { p0: s.load.load1, p1: s.load.load5, p2: s.load.load15, p3: s.load.cpu_count }));
      const m = s.memory;
      setGauge("#g-mem", m.used_pct, level(m.used_pct, 80, 92), t("{p0} di {p1}, swap {p2}%", { p0: fmtGB(m.used_mb), p1: fmtGB(m.total_mb), p2: fmtNum(m.swap_used_pct) }));
      const root = s.disks.find((d) => d.mountpoint === "/") || {};
      setGauge("#g-disk", s.root_disk_pct, level(s.root_disk_pct, 85, 95), root.free_mb !== undefined ? t("{p0} liberi", { p0: fmtGB(root.free_mb) }) : "");
      const tb = $("#disks tbody");
      tb.replaceChildren(...s.disks.map((d) => row([
        { text: d.mountpoint, title: `${d.device} (${d.fstype})` },
        { text: fmtGB(d.used_mb), cls: "num" },
        { text: fmtGB(d.free_mb), cls: "num" },
        { text: fmtNum(d.used_pct), cls: `num ${level(d.used_pct, 85, 95)}` },
      ])));
    } catch (e) { console.error("system", e); }
  }

  async function loadProcesses() {
    if (window.AM.IS_VIEWER) return;              // processi non visibili all'utente in sola lettura
    try {
      const list = await api("/api/v1/processes?limit=15");
      $("#processes tbody").replaceChildren(...list.map((p) => row([
        { text: p.pid, cls: "num", label: "PID" }, { text: p.user || "", label: t("Utente") },
        { text: fmtNum(p.cpu_pct), cls: "num", label: "CPU %" }, { text: fmtNum(p.mem_pct), cls: "num", label: "RAM %" },
        { text: p.rss_mb, cls: "num", label: "RSS MB" }, { text: p.command, cls: "cmd", title: p.command, label: t("Comando") },
      ])));
    } catch (e) { console.error("processes", e); }
  }

  async function loadTemperatures() {
    if (remote()) return;
    try {
      const temp = await api("/api/v1/temperatures");
      state.temps = { warning: temp.warning, alert: temp.alert };
      const sensors = temp.sensors || [];
      $("#temperatures tbody").replaceChildren(...sensors.map((s) => row([
        { text: `${s.device}`, title: s.adapter },
        { text: fmtNum(s.value), cls: `num ${level(s.value, temp.warning, temp.alert)}` },
        { text: s.high ? fmtNum(s.high, 0) : "–", cls: "num" },
      ])));
      if (sensors.length) {
        const hot = sensors.reduce((a, b) => (b.value > a.value ? b : a));
        setGauge("#g-temp", hot.value, level(hot.value, temp.warning, temp.alert), t("{p0}, soglia {p1} °C", { p0: hot.device, p1: temp.warning }));
      }
    } catch (e) { console.error("temperatures", e); }
  }

  async function loadServices() {
    try {
      const list = await api("/api/v1/services");
      const leds = list.map((s) => {
        const li = el("li");
        li.append(el("span", { class: `led ${s.up ? "up" : "down"}`, "aria-hidden": "true" }), el("span", { class: "svc-label" }, s.label));
        li.title = `${s.label} — ${s.unit}: ${s.state}`;
        return li;
      });
      void leds;                                              // 4.1: niente più fila di LED in testata
      if (remote()) return;
      $("#services").replaceChildren(...list.map((s) => window.AM.serviceRow
        ? window.AM.serviceRow(s, { onOpen: () => openService(s) })          // 4.3: stesso elenco a righe dei server collegati
        : el("li", {}, s.label)));
    } catch (e) { console.error("services", e); }
  }

  async function openService(s) {
    if (window.AM.IS_VIEWER) return;              // dettaglio (systemctl status) non visibile in sola lettura
    const dlg = $("#service-dialog");
    $("#service-dialog-title").textContent = `${s.label} (${s.unit})`;
    $("#service-dialog-body").textContent = "Caricamento…";
    dlg.showModal();
    try {
      const d = await api(`/api/v1/services/${encodeURIComponent(s.unit)}`);
      $("#service-dialog-body").textContent = d.detail || t("(nessun output)");
    } catch (e) { $("#service-dialog-body").textContent = `Errore: ${e.message}`; }
  }

  async function loadNetwork() {
    try {
      const n = await api("/api/v1/network");
      if (n.public_ip && n.public_ip.ip) {
        $("#public-ip").textContent = n.public_ip.ip;
        $("#public-ip-since").textContent = t("dal {p0}", { p0: fmtDateTime(n.public_ip.since) });
      }
      if (n.speedtest) {
        const st = n.speedtest;
        $("#speed-latest").textContent = `↓ ${fmtNum(st.download_mbps, 0)}  ↑ ${fmtNum(st.upload_mbps, 0)} Mbps`;
        $("#speed-latest-when").textContent = t("{p0} alle {p1}", { p0: st.status, p1: fmtDateTime(st.timestamp) });
      }
      if (n.backup && $("#backup-latest")) {
        const b = n.backup;
        const total = (b.databases || []).reduce((a, d) => a + d.zst_bytes, 0);
        const el = $("#backup-latest");
        el.textContent = b.status === "OK" ? `${(b.databases || []).length} DB, ${fmtNum(total / 1048576, 1)} MB` : t("Fallito");
        el.style.color = b.status === "OK" ? "" : C("--alert");
        $("#backup-latest-when").textContent = t("{p0} alle {p1}", { p0: b.status, p1: fmtDateTime(b.time) });
        if (b.errors && b.errors.length) el.title = b.errors.join("\n");
      }
      $("#ip-history tbody").replaceChildren(...(n.public_ip_history || []).map((h) => row([
        { text: fmtDateTime(h.timestamp) }, { text: h.ip }, { text: h.previous_ip || "–" },
      ])));
    } catch (e) { console.error("network", e); }
  }

  function periodQuery() {
    if (state.custom) return `from=${encodeURIComponent(state.custom.from)}&to=${encodeURIComponent(state.custom.to)}`;
    return `range=${state.range}`;
  }

  async function loadHistory() {
    const q = periodQuery() + hostQ();
    const err = $("#history-error");
    err.hidden = true;
    try {
      const [m, tm, s, evs] = await Promise.all([
        api(`/api/v1/history/metrics?${q}`),
        api(`/api/v1/history/temperatures?${q}`),
        remote() ? Promise.resolve({ labels: [], download: [], upload: [] }) : api(`/api/v1/history/speedtest?${q}`),
        window.AM.loadEvents(q),
      ]);
      const L = (arr) => arr.map(fmtDateTime);
      const meta = (arr) => ({ times: arr.map((x) => Date.parse(x)), events: evs });
      window.AM.renderEvents($("#server-events"), evs);
      drawChart("chart-cpu", L(m.labels), [
        ds("CPU % media", m.cpu, C("--ok")),
        ds("CPU % picco", m.cpu_max, C("--warn"), { borderDash: [4, 3] }),
        ds("Load 1 min", m.load1, C("--accent2"), { yAxisID: "y1" }),
      ], { max: 100, extra: { y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } }, meta(m.labels));
      drawChart("chart-mem", L(m.labels), [ds("RAM %", m.mem, C("--accent2")), ds(t("Disco / %"), m.disk, C("--sage"))], { max: 100 }, meta(m.labels));
      drawChart("chart-temp", L(tm.labels), Object.entries(tm.series).map(([name, values], i) => ds(name, values, PALETTE[i % PALETTE.length])), { beginAtZero: false }, meta(tm.labels));
      drawChart("chart-speed", L(s.labels), [
        ds(t("Download Mbps"), s.download, C("--ok"), { pointRadius: 2, tension: 0 }),
        ds(t("Upload Mbps"), s.upload, C("--accent2"), { pointRadius: 2, tension: 0 }),
      ], {}, meta(s.labels));
    } catch (e) {
      err.textContent = t("Storico non disponibile: {p0}", { p0: e.message });
      err.hidden = false;
    }
  }

  // -------------------------------------------------------------- eventi
  const periodButtons = $$('[data-view="server"] .period button');
  periodButtons.forEach((b) => b.addEventListener("click", () => {
    periodButtons.forEach((x) => x.classList.toggle("active", x === b));
    state.range = b.dataset.range;
    state.custom = null;
    loadHistory();
  }));
  $("#custom-range").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    if (f.get("from") >= f.get("to")) {
      $("#history-error").textContent = t("La data di fine deve essere successiva a quella di inizio.");
      $("#history-error").hidden = false;
      return;
    }
    periodButtons.forEach((x) => x.classList.remove("active"));
    state.custom = { from: f.get("from"), to: f.get("to") };
    loadHistory();
  });
  $("#services-refresh").addEventListener("click", () => {
    if (remote() && window.AM.refreshRemoteServices) window.AM.refreshRemoteServices();   // 4.3: chiede all'agente
    else loadServices();
  });

  // --------------------------------------------- controlli e scadenze
  const STATUS_CLS = { OK: "up", WARNING: "warn", ALERT: "down", DOWN: "down", UNKNOWN: "" };
  function check(label, status, value, sub) {
    const li = el("li", { class: `check ${STATUS_CLS[status] ?? ""}` });
    li.append(el("span", { class: `led ${STATUS_CLS[status] ?? ""}`, "aria-hidden": "true" }));
    const box = el("div");
    box.append(el("strong", {}, label), el("span", { class: "check-value" }, value));
    if (sub) box.append(el("small", { class: "block" }, sub));
    li.append(box);
    return li;
  }
  async function loadChecks() {
    const items = [];
    try {
      const [n, e, h, hc] = await Promise.all([api("/api/v1/network"), api("/api/v1/expiry"), api("/api/v1/heartbeat"),
                                                api("/api/v1/health-checks")]);
      const c = n.connectivity;
      items.push(c ? check(t("Connessione (ping)"), c.status, c.status === "OK" ? t("regolare") : c.status === "DOWN" ? t("assente") : t("degradata"),
                           `${c.text} — ${fmtDateTime(c.time)}`)
                   : check(t("Connessione (ping)"), "UNKNOWN", t("nessun dato"), t("il controllo continuo non ha ancora registrato misure")));
      items.push(h && h.time ? check(t("Heartbeat esterno"), h.ok ? "OK" : "ALERT", h.ok ? "inviato" : t("non inviato"),
                                     (h.ok ? "" : `${h.error} — `) + t("ultimo alle {p0}", { p0: fmtDateTime(h.time) }))
                             : check(t("Heartbeat esterno"), "UNKNOWN", t("non configurato"), t("Impostazioni → Notifiche → Heartbeat esterno")));
      (e.items || []).forEach((it) => items.push(check(it.name, it.status,
        it.note || (it.days === null ? t("non verificabile") : t("{p0} giorni", { p0: Math.floor(it.days) })),
        it.error || (it.expires ? t("scade il {p0}", { p0: new Date(it.expires).toLocaleDateString(window.AM.LOCALE) }) : ""))));
      if (!(e.items || []).length) items.push(check(t("Scadenze"), "UNKNOWN", t("nessun dato"), t("il controllo gira ogni giorno alle 09:00")));
      const health = hc.health || {};
      (health.disks || []).forEach((d) => items.push(check(t("Disco {p0}", { p0: d.device }), d.status,
        d.status === "OK" ? t("in salute") : d.status === "UNKNOWN" ? t("non verificabile") : d.status.toLowerCase(),
        [d.model, d.temperature != null ? `${d.temperature} °C` : null, d.wear_used_pct != null ? t("usura {p0}%", { p0: d.wear_used_pct }) : null,
         ...(d.reasons || [])].filter(Boolean).join(" — "))));
      if (!(health.disks || []).length) items.push(check(t("Dischi (SMART)"), "UNKNOWN", t("nessun dato"), t("astreo-smart-collect.timer attivo?")));
      const u = health.updates;
      if (u) items.push(check(t("Aggiornamenti"), u.status, u.status === "OK" ? t("nessuno urgente") : t("{p0} di sicurezza", { p0: (u.security || []).length }),
        t("{p0} in sospeso{p1}", { p0: u.total, p1: u.reboot && u.reboot.required ? " — riavvio richiesto" : "" })));
      const rt = hc.restoretest;
      items.push(rt ? check(t("Verifica ripristino"), rt.status, rt.status === "OK" ? t("riuscita") : t("fallita"),
                            `${(rt.results || []).map((r) => `${r.database}: ${r.status === "OK" ? `${r.rows} righe` : r.error}`).join(" — ")} — ${fmtDateTime(rt.time)}`)
                    : check(t("Verifica ripristino"), "UNKNOWN", t("mai eseguita"), t("una volta al mese, la prima domenica")));
      $("#checks").replaceChildren(...items);
    } catch (err) { console.error("checks", err); }
  }

  // -------------------------------------------------------------- avvio
  document.addEventListener("DOMContentLoaded", () => {
    every(REFRESH.system, loadSystem, "server");
    every(REFRESH.services, loadServices, "server");
    every(REFRESH.network, loadNetwork, "connessione");   // 4.1: IP pubblico e speedtest stanno in Rete e connessione
    window.AM.onView("connessione", loadNetwork);
    every(REFRESH.processes, loadProcesses, "server");
    every(60_000, loadChecks, "server");
    every(REFRESH.temps, loadTemperatures, "server");
    every(REFRESH.history, loadHistory, "server");
    document.addEventListener("services-changed", loadServices);
    window.AM.onView("server", () => { loadSystem(); loadServices(); loadProcesses(); loadTemperatures(); loadHistory(); loadChecks(); });
    document.addEventListener("host-changed", () => { loadSystem(); loadServices(); loadTemperatures(); loadHistory(); });
  });
})();
