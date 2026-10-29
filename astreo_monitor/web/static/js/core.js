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
      const td = el("td", c.cls ? { class: c.cls } : {});
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
  const PALETTE = ["#8fd19e", "#e8b85c", "#7fb2e5", "#d48fd1", "#ef7a62", "#a6b488", "#6fd6c8", "#c9c27a"];
  const charts = {};
  if (window.Chart) {
    Chart.defaults.color = C("--text");
    Chart.defaults.borderColor = C("--line");
    Chart.defaults.font.family = C("--font");
  }
  function drawChart(id, labels, datasets, yOptions = {}) {
    if (!window.Chart) return;
    const { extra = {}, ...yScale } = yOptions;
    const data = { labels, datasets };
    if (charts[id]) { charts[id].data = data; charts[id].update("none"); return; }
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
  }
  const ds = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, ...extra });
  const constLine = (label, value, n, color) => ds(label, Array(n).fill(value), color,
    { borderDash: [6, 4], borderWidth: 1, pointRadius: 0, tension: 0 });

  // ------------------------------------------------------- viste e schede
  const viewHandlers = {};
  let currentView = null;
  function onView(name, fn) { viewHandlers[name] = fn; }
  function showView() {
    const name = (location.hash || "#server").slice(1).split("/")[0] || "server";
    const valid = $$("[data-view]").map((v) => v.dataset.view);
    const view = valid.includes(name) ? name : "server";
    $$("[data-view]").forEach((v) => { v.hidden = v.dataset.view !== view; });
    $$("[data-view-link]").forEach((a) => a.classList.toggle("active", a.dataset.viewLink === view));
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
                level, toLocalInput, C, PALETTE, drawChart, ds, constLine, charts, onView, every, isView };
  document.addEventListener("DOMContentLoaded", () => { setupSubtabs(); showView(); });
})();
