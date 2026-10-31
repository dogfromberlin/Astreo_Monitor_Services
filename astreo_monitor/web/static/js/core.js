/* Astreo Monitor - funzioni comuni a tutte le viste. */
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  async function api(path, options = {}) {
    const opts = { cache: "no-store", headers: { Accept: "application/json" }, ...options };
    if (opts.json !== undefined) {
      opts.body = JSON.stringify(opts.json);
      opts.headers = { ...opts.headers, "Content-Type": "application/json" };
      delete opts.json;
    }
    const res = await fetch(path, opts);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
    return body;
  }

  const fmtNum = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–"
    : Number(v).toLocaleString("it-IT", { maximumFractionDigits: d, minimumFractionDigits: d }));
  const fmtGB = (mb) => `${fmtNum(mb / 1024, 1)} GB`;
  const fmtTime = (d = new Date()) => d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const fmtDateTime = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "–";
  const fmtFull = (iso) => iso ? new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "–";
  const fmtDuration = (ms) => {
    const m = Math.round(ms / 60000);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), r = m % 60;
    if (h < 48) return r ? `${h} h ${r} min` : `${h} h`;
    return `${Math.floor(h / 24)} g ${h % 24} h`;
  };
  const fmtUptime = (s) => {
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? `${d} g ${h} h` : `${h} h ${m} min`;
  };
  const level = (v, warn, alert) => (v >= alert ? "alert" : v >= warn ? "warn" : "ok");
  const toLocalInput = (d) => {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  function el(tag, attrs = {}, text) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === false || v === null || v === undefined) continue;
      n.setAttribute(k, v === true ? "" : v);
    }
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function row(cells) {
    const tr = document.createElement("tr");
    for (const c of cells) {
      const td = el("td", { class: c.cls || null, "data-label": c.label || null });
      if (c.node) td.appendChild(c.node); else td.textContent = c.text ?? "";
      if (c.title) td.title = c.title;
      tr.appendChild(td);
    }
    return tr;
  }

  let toastTimer;
  function toast(msg, kind = "ok") {
    const t = $("#toast");
    t.textContent = msg;
    t.className = `toast ${kind}`;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, kind === "error" ? 6000 : 2500);
  }

  // ---------------------------------------------------------------- grafici
  const css = getComputedStyle(document.documentElement);
  const C = (name) => css.getPropertyValue(name).trim();
  const PALETTE = ["#8ccba8", "#e8b85c", "#7382eb", "#d48fd1", "#ef7a62", "#b3c48e", "#6fd6c8", "#c9c27a"];
  const charts = {};
  if (window.Chart) {
    Chart.defaults.color = C("--text");
    Chart.defaults.borderColor = C("--line");
    Chart.defaults.font.family = C("--font");
  }
  // ------------------------------------------------- eventi sui grafici
  const EVENT_COLOR = { reboot: "#d48fd1", outage: "#ef7a62", ip: "#7382eb", service: "#e8b85c", container: "#6fd6c8",
                        pihole: "#c9c27a", speedtest: "#f0a35e", alert: "#e8b85c" };
  const eventState = { visible: true, hidden: new Set(), cache: {} };

  function visibleEvents(list) {
    return eventState.visible ? (list || []).filter((e) => !eventState.hidden.has(e.kind)) : [];
  }

  const eventsPlugin = {
    id: "astreoEvents",
    afterDatasetsDraw(chart) {
      const times = chart.$times, evs = visibleEvents(chart.$events);
      chart.$eventMarks = [];
      if (!times || times.length < 2 || !evs.length) return;
      const x = chart.scales.x, area = chart.chartArea, ctx = chart.ctx;
      const step = (times[times.length - 1] - times[0]) / (times.length - 1);
      evs.forEach((e) => {
        const t = Date.parse(e.time);
        if (t < times[0] - step / 2 || t > times[times.length - 1] + step / 2) return;
        let i = 0;
        while (i < times.length - 2 && times[i + 1] <= t) i++;
        const frac = Math.max(0, Math.min(1, (t - times[i]) / ((times[i + 1] - times[i]) || 1)));
        const px = x.getPixelForValue(i) + frac * (x.getPixelForValue(i + 1) - x.getPixelForValue(i));
        const color = EVENT_COLOR[e.kind] || "#e8b85c";
        ctx.save();
        ctx.strokeStyle = color; ctx.globalAlpha = .75; ctx.lineWidth = 1.2; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(px, area.top); ctx.lineTo(px, area.bottom); ctx.stroke();
        ctx.setLineDash([]); ctx.globalAlpha = 1; ctx.fillStyle = color;
        ctx.beginPath(); ctx.moveTo(px - 4, area.top); ctx.lineTo(px + 4, area.top); ctx.lineTo(px, area.top + 6); ctx.fill();
        ctx.restore();
        chart.$eventMarks.push({ px, e });
      });
      const h = chart.$hoverEvent;
      if (h) {
        const text = [h.e.title, `${fmtDateTime(h.e.time)}${h.e.detail ? " — " + h.e.detail : ""}`];
        ctx.save();
        ctx.font = "12px " + C("--font");
        const w = Math.max(...text.map((l) => ctx.measureText(l).width)) + 16;
        const bx = Math.min(Math.max(h.px - w / 2, area.left), area.right - w);
        ctx.fillStyle = "rgba(13,8,34,.95)"; ctx.strokeStyle = EVENT_COLOR[h.e.kind] || "#e8b85c";
        ctx.fillRect(bx, area.top + 8, w, 40); ctx.strokeRect(bx, area.top + 8, w, 40);
        ctx.fillStyle = "#dcefd9"; ctx.fillText(text[0], bx + 8, area.top + 24);
        ctx.fillStyle = "#b7c0b5"; ctx.fillText(text[1], bx + 8, area.top + 40);
        ctx.restore();
      }
    },
    afterEvent(chart, args) {
      const ev = args.event, marks = chart.$eventMarks || [];
      if (ev.type === "mousemove") {
        const m = marks.find((k) => Math.abs(k.px - ev.x) <= 5 && ev.y >= chart.chartArea.top && ev.y <= chart.chartArea.bottom) || null;
        if (m !== chart.$hoverEvent) { chart.$hoverEvent = m; args.changed = true; }
      } else if (ev.type === "mouseout" && chart.$hoverEvent) { chart.$hoverEvent = null; args.changed = true; }
    },
  };
  if (window.Chart) Chart.register(eventsPlugin);

  async function loadEvents(query) {
    if (!eventState.visible) return [];
    try {
      const d = await api(`/api/v1/events?${query}`);
      eventState.cache[query] = d.events;
      eventState.kinds = d.kinds;
      return d.events;
    } catch (e) { return []; }
  }
  function redrawEvents() { Object.values(charts).forEach((c) => c.update("none")); document.dispatchEvent(new Event("events-filter")); }

  function drawChart(id, labels, datasets, yOptions = {}, meta = {}) {
    if (!window.Chart) return;
    const { extra = {}, ...yScale } = yOptions;
    const data = { labels, datasets };
    if (charts[id]) {
      charts[id].$times = meta.times || null; charts[id].$events = meta.events || null;
      charts[id].data = data; charts[id].update("none"); return;
    }
    charts[id] = new Chart(document.getElementById(id), {
      type: "line",
      data,
      options: {
        animation: false, responsive: true, maintainAspectRatio: false, spanGaps: true,
        interaction: { mode: "index", intersect: false },
        elements: { point: { radius: 0, hitRadius: 6 }, line: { borderWidth: 1.6, tension: 0.25 } },
        scales: { x: { ticks: { maxTicksLimit: 8, maxRotation: 0 } }, y: { beginAtZero: true, ...yScale }, ...extra },
        plugins: { legend: { labels: { boxWidth: 12 } } },
      },
    });
    charts[id].$times = meta.times || null;
    charts[id].$events = meta.events || null;
    charts[id].update("none");
  }
  const ds = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, ...extra });
  const constLine = (label, value, n, color) => ds(label, Array(n).fill(value), color,
    { borderDash: [6, 4], borderWidth: 1, pointRadius: 0, tension: 0 });

  // ------------------------------------------------------- viste e schede
  const viewHandlers = {};
  let currentView = null;
  // Se la pagina è già aperta su quella vista (link diretto, es. /#terminale), la carica subito
  function onView(name, fn) { viewHandlers[name] = fn; if (currentView === name) fn(); }
  function showView() {
    const name = (location.hash || "#server").slice(1).split("/")[0] || "server";
    const valid = $$(".view[data-view]").map((v) => v.dataset.view);
    const view = valid.includes(name) ? name : "server";
    $$(".view[data-view]").forEach((v) => { v.hidden = v.dataset.view !== view; });
    $$("[data-view-link]").forEach((a) => a.classList.toggle("active", a.dataset.viewLink === view));
    document.body.dataset.currentView = view;   // NON data-view: verrebbe trattato come una vista
    if (currentView !== view) {
      currentView = view;
      if (viewHandlers[view]) viewHandlers[view]();
      Object.values(charts).forEach((c) => c.resize());
    }
  }
  window.addEventListener("hashchange", showView);

  function setupSubtabs() {
    $$("[data-subtabs]").forEach((bar) => {
      const group = bar.dataset.subtabs;
      bar.addEventListener("click", (ev) => {
        const b = ev.target.closest("button[data-sub]");
        if (!b) return;
        $$("button[data-sub]", bar).forEach((x) => x.classList.toggle("active", x === b));
        $$(`[data-subpanel^="${group}:"]`).forEach((p) => { p.hidden = p.dataset.subpanel !== `${group}:${b.dataset.sub}`; });
        document.dispatchEvent(new CustomEvent("subtab", { detail: { group, sub: b.dataset.sub } }));
        Object.values(charts).forEach((c) => c.resize());
      });
    });
  }

  function every(ms, fn, view) {
    const run = () => { if (!view || currentView === view) fn(); };
    run();
    return setInterval(run, ms);
  }
  const isView = (v) => currentView === v;

  window.AM = { $, $$, api, el, row, toast, fmtNum, fmtGB, fmtTime, fmtDateTime, fmtFull, fmtDuration, fmtUptime,
                level, toLocalInput, C, PALETTE, drawChart, ds, constLine, charts, onView, every, isView,
                loadEvents, eventState, visibleEvents, redrawEvents, EVENT_COLOR };
  // Avvisi di installazione: database incompleto o pagina di una versione diversa dal server
  async function checkInstall() {
    try {
      const h = await api("/api/v1/health");
      const msgs = [];
      if (h.schema_ok === false) {
        msgs.push(`Database incompleto: esegui come <strong>sa</strong> ${h.schema_scripts.map((x) => `<code>sql/${x}</code>`).join(", ")} `
          + "(dettaglio: <code>python -m astreo_monitor.schema</code>). Alcune funzioni non lavorano finché manca.");
      }
      if (h.version && h.version !== document.body.dataset.version) {
        msgs.push(`La pagina è della versione ${document.body.dataset.version}, il server è alla ${h.version}: ricarica con Ctrl+F5.`);
      }
      const b = $("#schema-banner");
      b.innerHTML = msgs.join("<br>");
      b.hidden = msgs.length === 0;
    } catch (e) { /* health non raggiungibile: lo segnalano già le altre sezioni */ }
  }

  document.addEventListener("DOMContentLoaded", () => { setupSubtabs(); showView(); checkInstall(); setInterval(checkInstall, 600_000); });
})();
