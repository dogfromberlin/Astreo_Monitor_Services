/* Astreo Monitor - vista Server: risorse in tempo reale, servizi, storico. */
(() => {
  "use strict";
  const { $, $$, api, el, row, fmtNum, fmtGB, fmtTime, fmtDateTime, fmtUptime, level, C, PALETTE, drawChart, ds, every } = window.AM;
  const REFRESH = { system: 10_000, processes: 10_000, services: 60_000, temps: 60_000, network: 300_000, history: 300_000 };
  const state = { range: "24h", custom: null };

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
      setGauge("#g-cpu", s.cpu_pct, level(s.cpu_pct, 70, 90), `load ${s.load.load1} / ${s.load.load5} / ${s.load.load15} su ${s.load.cpu_count} core`);
      const m = s.memory;
      setGauge("#g-mem", m.used_pct, level(m.used_pct, 80, 92), `${fmtGB(m.used_mb)} di ${fmtGB(m.total_mb)}, swap ${fmtNum(m.swap_used_pct)}%`);
      const root = s.disks.find((d) => d.mountpoint === "/") || {};
      setGauge("#g-disk", s.root_disk_pct, level(s.root_disk_pct, 85, 95), root.free_mb !== undefined ? `${fmtGB(root.free_mb)} liberi` : "");
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
    try {
      const list = await api("/api/v1/processes?limit=15");
      $("#processes tbody").replaceChildren(...list.map((p) => row([
        { text: p.pid, cls: "num" }, { text: p.user || "" },
        { text: fmtNum(p.cpu_pct), cls: "num" }, { text: fmtNum(p.mem_pct), cls: "num" },
        { text: p.rss_mb, cls: "num" }, { text: p.command, cls: "cmd", title: p.command },
      ])));
    } catch (e) { console.error("processes", e); }
  }

  async function loadTemperatures() {
    try {
      const t = await api("/api/v1/temperatures");
      state.temps = { warning: t.warning, alert: t.alert };
      const sensors = t.sensors || [];
      $("#temperatures tbody").replaceChildren(...sensors.map((s) => row([
        { text: `${s.device}`, title: s.adapter },
        { text: fmtNum(s.value), cls: `num ${level(s.value, t.warning, t.alert)}` },
        { text: s.high ? fmtNum(s.high, 0) : "–", cls: "num" },
      ])));
      if (sensors.length) {
        const hot = sensors.reduce((a, b) => (b.value > a.value ? b : a));
        setGauge("#g-temp", hot.value, level(hot.value, t.warning, t.alert), `${hot.device}, soglia ${t.warning} °C`);
      }
    } catch (e) { console.error("temperatures", e); }
  }

  async function loadServices() {
    try {
      const list = await api("/api/v1/services");
      const leds = list.map((s) => {
        const li = el("li");
        li.append(el("span", { class: `led ${s.up ? "up" : "down"}`, "aria-hidden": "true" }), el("span", {}, s.label));
        li.title = `${s.unit}: ${s.state}`;
        return li;
      });
      $("#leds").replaceChildren(...leds);
      $("#services").replaceChildren(...list.map((s) => {
        const li = el("li", { class: s.up ? "up" : "down" });
        const b = el("button", { type: "button" });
        b.append(el("span", { class: `led ${s.up ? "up" : "down"}`, "aria-hidden": "true" }), el("span", {}, s.label), el("span", { class: "state" }, s.state));
        b.addEventListener("click", () => openService(s));
        li.appendChild(b);
        return li;
      }));
    } catch (e) { console.error("services", e); }
  }

  async function openService(s) {
    const dlg = $("#service-dialog");
    $("#service-dialog-title").textContent = `${s.label} (${s.unit})`;
    $("#service-dialog-body").textContent = "Caricamento…";
    dlg.showModal();
    try {
      const d = await api(`/api/v1/services/${encodeURIComponent(s.unit)}`);
      $("#service-dialog-body").textContent = d.detail || "(nessun output)";
    } catch (e) { $("#service-dialog-body").textContent = `Errore: ${e.message}`; }
  }

  async function loadNetwork() {
    try {
      const n = await api("/api/v1/network");
      if (n.public_ip && n.public_ip.ip) {
        $("#public-ip").textContent = n.public_ip.ip;
        $("#public-ip-since").textContent = `dal ${fmtDateTime(n.public_ip.since)}`;
      }
      if (n.speedtest) {
        const st = n.speedtest;
        $("#speed-latest").textContent = `↓ ${fmtNum(st.download_mbps, 0)}  ↑ ${fmtNum(st.upload_mbps, 0)} Mbps`;
        $("#speed-latest-when").textContent = `${st.status} alle ${fmtDateTime(st.timestamp)}`;
      }
      if (n.backup) {
        const b = n.backup;
        const total = (b.databases || []).reduce((a, d) => a + d.zst_bytes, 0);
        const el = $("#backup-latest");
        el.textContent = b.status === "OK" ? `${(b.databases || []).length} DB, ${fmtNum(total / 1048576, 1)} MB` : "Fallito";
        el.style.color = b.status === "OK" ? "" : C("--alert");
        $("#backup-latest-when").textContent = `${b.status} alle ${fmtDateTime(b.time)}`;
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
    const q = periodQuery();
    const err = $("#history-error");
    err.hidden = true;
    try {
      const [m, t, s] = await Promise.all([
        api(`/api/v1/history/metrics?${q}`),
        api(`/api/v1/history/temperatures?${q}`),
        api(`/api/v1/history/speedtest?${q}`),
      ]);
      const L = (arr) => arr.map(fmtDateTime);
      drawChart("chart-cpu", L(m.labels), [
        ds("CPU % media", m.cpu, C("--ok")),
        ds("CPU % picco", m.cpu_max, C("--warn"), { borderDash: [4, 3] }),
        ds("Load 1 min", m.load1, "#7fb2e5", { yAxisID: "y1" }),
      ], { max: 100, extra: { y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } });
      drawChart("chart-mem", L(m.labels), [ds("RAM %", m.mem, "#7fb2e5"), ds("Disco / %", m.disk, C("--sage"))], { max: 100 });
      drawChart("chart-temp", L(t.labels), Object.entries(t.series).map(([name, values], i) => ds(name, values, PALETTE[i % PALETTE.length])), { beginAtZero: false });
      drawChart("chart-speed", L(s.labels), [
        ds("Download Mbps", s.download, C("--ok"), { pointRadius: 2, tension: 0 }),
        ds("Upload Mbps", s.upload, "#7fb2e5", { pointRadius: 2, tension: 0 }),
      ]);
    } catch (e) {
      err.textContent = `Storico non disponibile: ${e.message}`;
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
      $("#history-error").textContent = "La data di fine deve essere successiva a quella di inizio.";
      $("#history-error").hidden = false;
      return;
    }
    periodButtons.forEach((x) => x.classList.remove("active"));
    state.custom = { from: f.get("from"), to: f.get("to") };
    loadHistory();
  });
  $("#services-refresh").addEventListener("click", loadServices);

  // -------------------------------------------------------------- avvio
  document.addEventListener("DOMContentLoaded", () => {
    every(REFRESH.system, loadSystem);                 // la testata usa hostname e uptime
    every(REFRESH.services, loadServices);             // LED nella testata, sempre aggiornati
    every(REFRESH.network, loadNetwork);
    every(REFRESH.processes, loadProcesses, "server");
    every(REFRESH.temps, loadTemperatures, "server");
    every(REFRESH.history, loadHistory, "server");
    document.addEventListener("services-changed", loadServices);
    window.AM.onView("server", () => { loadProcesses(); loadTemperatures(); loadHistory(); });
  });
})();
