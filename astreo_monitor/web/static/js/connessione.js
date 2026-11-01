/* Astreo Monitor - vista Connessione (ex NetPulse): andamento, qualità, confronto. */
(() => {
  "use strict";
  const { t, $, $$, api, el, row, fmtNum, fmtDateTime, fmtFull, fmtDuration, toLocalInput, C, drawChart, ds, constLine, toast } = window.AM;
  const state = { range: "7d", custom: null, data: null };
  const DOWN = C("--ok"), UP = C("--accent2");

  const query = () => (state.custom
    ? `from=${encodeURIComponent(state.custom.from)}&to=${encodeURIComponent(state.custom.to)}`
    : `range=${state.range}`);

  // Righe come oggetti; i valori dell'upload legacy arrivano già a null dal server
  function toRows(d) {
    return d.labels.map((ts, i) => ({
      ts: new Date(ts).getTime(), iso: ts, download: d.download[i], upload: d.upload[i],
      latency: d.latency[i], status: d.status[i], provider: d.provider[i],
    }));
  }
  const values = (rows, k) => rows.map((r) => r[k]).filter((v) => v !== null && v !== undefined);
  const avg = (a) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : null);
  const max = (a) => (a.length ? Math.max(...a) : null);
  const min = (a) => (a.length ? Math.min(...a) : null);

  async function load() {
    const err = $("#conn-error");
    err.hidden = true;
    try {
      const [d, evs] = await Promise.all([api(`/api/v1/history/speedtest?${query()}`), window.AM.loadEvents(query())]);
      state.data = { ...d, rows: toRows(d), events: evs };
      window.AM.renderEvents($("#conn-events"), evs);
      $("#conn-label").textContent = `Dal ${fmtFull(d.from)} al ${fmtFull(d.to)}: ${d.labels.length} misure`;
      renderAndamento();
      renderQualita();
      $("#compare-result").hidden = true;
      loadAvailability();
    } catch (e) {
      err.textContent = t("Dati non disponibili: {p0}", { p0: e.message });
      err.hidden = false;
    }
  }

  // -------------------------------------------------------------- andamento
  function stat(label, value, unit, sub) {
    const a = el("article", { class: "stat" });
    a.append(el("h3", {}, label));
    const p = el("p", { class: "value" });
    p.append(el("span", {}, value), document.createTextNode(unit ? ` ${unit}` : ""));
    a.append(p);
    if (sub) a.append(el("p", { class: "sub" }, sub));
    return a;
  }

  function renderAndamento() {
    const { rows, thresholds: th } = state.data;
    const dl = values(rows, "download"), ul = values(rows, "upload"), lat = values(rows, "latency");
    const down = rows.filter((r) => r.status === "DOWN").length;
    $("#conn-stats").replaceChildren(
      stat(t("Download medio"), fmtNum(avg(dl), 0), "Mbps", `minimo ${fmtNum(min(dl), 0)}`),
      stat(t("Download massimo"), fmtNum(max(dl), 0), "Mbps"),
      stat(t("Upload medio"), fmtNum(avg(ul), 0), "Mbps", `minimo ${fmtNum(min(ul), 0)}`),
      stat(t("Upload massimo"), fmtNum(max(ul), 0), "Mbps"),
      stat(t("Latenza media"), fmtNum(avg(lat), 0), "ms"),
      stat(t("Misure"), String(rows.length), "", down ? t("{p0} con connessione assente", { p0: down }) : t("nessuna interruzione")),
    );
    const labels = rows.map((r) => fmtDateTime(r.iso));
    const meta = { times: rows.map((r) => r.ts), events: state.data.events };
    drawChart("chart-conn-speed", labels, [
      ds("Download", rows.map((r) => r.download), DOWN, { pointRadius: 2, tension: 0 }),
      ds("Upload", rows.map((r) => r.upload), UP, { pointRadius: 2, tension: 0 }),
      constLine(t("Soglia download {p0}", { p0: th.download_warning }), th.download_warning, rows.length, DOWN),
      constLine(t("Soglia upload {p0}", { p0: th.upload_warning }), th.upload_warning, rows.length, UP),
    ], {}, meta);
    drawChart("chart-conn-latency", labels, [ds(t("Latenza"), rows.map((r) => r.latency), C("--warn"), { pointRadius: 2, tension: 0 })], {}, meta);

    const last = [...rows].reverse().slice(0, 200);
    $("#conn-table tbody").replaceChildren(...last.map((r) => row([
      { text: fmtFull(r.iso), label: t("Quando") },
      { text: fmtNum(r.download, 0), cls: `num ${r.download !== null && r.download < th.download_warning ? "warn" : ""}`, label: "Download" },
      { text: fmtNum(r.upload, 0), cls: `num ${r.upload !== null && r.upload < th.upload_warning ? "warn" : ""}`, label: "Upload" },
      { text: fmtNum(r.latency, 0), cls: "num", label: t("Latenza") },
      { label: t("Esito"), text: r.status || (r.provider === "legacy" ? "storico 1.x" : "–"),
        cls: r.status === "OK" ? "" : r.status === "WARNING" ? "warn" : r.status ? "alert" : "" },
    ])));
  }

  // ----------------------------------------------------------- disponibilità
  async function loadAvailability() {
    try {
      const d = await api(`/api/v1/history/connectivity?${query()}`);
      const series = Object.entries(d.series);
      const avgOf = (role) => {
        const v = series.filter(([, x]) => x.role === role).flatMap(([, x]) => x.rtt).filter((x) => x !== null);
        return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
      };
      const longest = d.outages.reduce((m, o) => (o.minutes > m ? o.minutes : m), 0);
      $("#avail-stats").replaceChildren(
        stat(t("Disponibilità"), d.availability === null ? "–" : fmtNum(d.availability, 2), d.availability === null ? "" : "%",
             d.samples ? `${d.samples} controlli` : t("nessun dato nel periodo")),
        stat(t("Interruzioni"), String(d.outages.length), "", d.down_minutes ? t("{p0} in totale", { p0: fmtDuration(d.down_minutes * 60000) }) : t("nessuna")),
        stat(t("Più lunga"), longest ? fmtDuration(longest * 60000) : "–", ""),
        stat(t("Latenza router"), fmtNum(avgOf("gateway"), 1), "ms"),
        stat(t("Latenza Internet"), fmtNum(avgOf("internet"), 1), "ms", t("soglia {p0} ms", { p0: d.thresholds.rtt_warning })),
      );
      const labels = d.labels.map(fmtDateTime);
      const pal = window.AM.PALETTE;
      const meta = { times: d.labels.map((x) => Date.parse(x)), events: (state.data && state.data.events) || [] };
      drawChart("chart-avail-rtt", labels, series.map(([tgt, x], i) =>
        ds(x.role === "gateway" ? `${tgt} (router)` : tgt, x.rtt, pal[i % pal.length])), {}, meta);
      drawChart("chart-avail-loss", labels, [
        ...series.map(([tgt, x], i) => ds(x.role === "gateway" ? `${tgt} (router)` : tgt, x.loss, pal[i % pal.length])),
        constLine(t("Soglia {p0}%", { p0: d.thresholds.loss_warning }), d.thresholds.loss_warning, labels.length, C("--warn")),
      ], { max: 100 }, meta);
      $("#avail-outages tbody").replaceChildren(...[...d.outages].reverse().map((o) => row([
        { text: fmtFull(o.start), label: t("Inizio") }, { text: fmtFull(o.end), label: t("Fine") },
        { text: fmtDuration(o.minutes * 60000), cls: "num alert", label: t("Durata") },
      ])));
      $("#avail-empty").hidden = d.outages.length > 0;
    } catch (e) {
      $("#avail-stats").replaceChildren(stat(t("Disponibilità"), "–", "", t("dati non disponibili: {p0}", { p0: e.message })));
    }
  }

  // ---------------------------------------------------------------- qualità
  /* Campioni consecutivi sotto soglia raggruppati in episodi (logica di NetPulse).
     Una misura con connessione assente (DOWN) conta come sotto soglia;
     un valore mancante (es. upload della 1.x) non conta. */
  function medianStep(rows) {
    if (rows.length < 2) return 4 * 3600_000;
    const gaps = rows.slice(1).map((r, i) => r.ts - rows[i].ts).sort((a, b) => a - b);
    return gaps[Math.floor(gaps.length / 2)] || 4 * 3600_000;
  }
  function episodes(rows, key, thr) {
    const valid = rows.filter((r) => r[key] !== null || r.status === "DOWN");
    if (!valid.length) return null;
    const step = medianStep(valid);
    const below = (r) => r.status === "DOWN" || r[key] < thr;
    const list = [];
    let cur = null;
    for (const r of valid) {
      if (below(r)) {
        const v = r[key] ?? 0;
        if (!cur) cur = { start: r.ts, end: r.ts, min: v, n: 1 };
        else { cur.end = r.ts; cur.min = Math.min(cur.min, v); cur.n++; }
      } else if (cur) { list.push(cur); cur = null; }
    }
    if (cur) list.push(cur);
    list.forEach((e) => { e.durata = e.end - e.start + step; });
    const span = valid[valid.length - 1].ts - valid[0].ts + step;
    const sotto = list.reduce((s, e) => s + e.durata, 0);
    return { list, span, sotto, step, n: valid.length, nSotto: list.reduce((s, e) => s + e.n, 0),
             longest: list.reduce((m, e) => (!m || e.durata > m.durata ? e : m), null),
             disponibilita: span ? 100 - (sotto / span) * 100 : 100 };
  }

  function qualityBlock(target, title, key, thr) {
    const q = episodes(state.data.rows, key, thr);
    const box = $(target);
    box.replaceChildren(el("h3", { class: "sub-title" }, t("{p0}: soglia {p1} Mbps", { p0: title, p1: thr })));
    if (!q) { box.append(el("p", { class: "hint" }, t("Nessuna misura valida nel periodo."))); return; }
    const stats = el("div", { class: "stats" });
    stats.append(
      stat(t("Episodi sotto soglia"), String(q.list.length), "", q.list.length ? "" : t("nessun calo")),
      stat(t("Tempo sotto soglia"), fmtDuration(q.sotto), "", t(q.nSotto === 1 ? "{p0} misura su {p1}" : "{p0} misure su {p1}", { p0: q.nSotto, p1: q.n })),
      stat(t("Disponibilità"), fmtNum(q.disponibilita, 1), "%"),
      stat(t("Episodio più lungo"), q.longest ? fmtDuration(q.longest.durata) : "–", "",
           q.longest ? t("dal {p0}", { p0: fmtDateTime(new Date(q.longest.start).toISOString()) }) : ""),
    );
    box.append(stats);
    if (q.list.length) {
      const wrap = el("div", { class: "scroll" });
      const table = el("table", { class: "data" });
      table.innerHTML = `<thead><tr><th>${t("Inizio")}</th><th>${t("Fine")}</th><th class='num'>${t("Durata")}</th>`
        + `<th class='num'>${t("Minimo (Mbps)")}</th><th class='num'>${t("Misure")}</th></tr></thead>`;
      const tb = el("tbody");
      [...q.list].reverse().slice(0, 100).forEach((e) => tb.append(row([
        { text: fmtFull(new Date(e.start).toISOString()) }, { text: fmtFull(new Date(e.end).toISOString()) },
        { text: fmtDuration(e.durata), cls: "num" }, { text: fmtNum(e.min, 0), cls: "num alert" }, { text: e.n, cls: "num" },
      ])));
      table.append(tb);
      wrap.append(table);
      box.append(wrap);
    }
  }

  function renderQualita() {
    const th = state.data.thresholds;
    const step = medianStep(state.data.rows);
    $("#quality-hint").textContent =
      t("Un episodio è una sequenza di misure consecutive sotto la soglia di warning. Con una misura ogni {p0}, ", { p0: fmtDuration(step) })
      + t("ogni campione rappresenta quell'intervallo: le durate vanno lette con questa granularità.");
    qualityBlock("#quality-download", "Download", "download", th.download_warning);
    qualityBlock("#quality-upload", "Upload", "upload", th.upload_warning);
  }

  // -------------------------------------------------------------- confronto
  function buckets(rows, start, span, n, key) {
    const acc = Array.from({ length: n }, () => ({ s: 0, c: 0 }));
    rows.forEach((r) => {
      const i = Math.floor(((r.ts - start) / span) * n);
      if (i >= 0 && i < n && r[key] !== null) { acc[i].s += r[key]; acc[i].c++; }
    });
    return acc.map((a) => (a.c ? a.s / a.c : null));
  }

  async function runCompare(ev) {
    ev.preventDefault();
    if (!state.data) return;
    const start = new Date(state.data.from).getTime(), end = new Date(state.data.to).getTime();
    const span = end - start;
    const shift = { prev: span, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000 }[new FormData(ev.target).get("shift")];
    const pFrom = toLocalInput(new Date(start - shift)), pTo = toLocalInput(new Date(end - shift));
    try {
      const d = await api(`/api/v1/history/speedtest?from=${encodeURIComponent(pFrom)}&to=${encodeURIComponent(pTo)}`);
      const prev = toRows(d), cur = state.data.rows;
      if (!prev.length) { toast(t("Nessuna misura nel periodo di confronto"), "error"); return; }
      const delta = (a, b) => (a !== null && b ? `${a >= b ? "+" : ""}${fmtNum(((a - b) / b) * 100, 1)}%` : "–");
      const rowsCmp = [
        [t("Download medio (Mbps)"), avg(values(cur, "download")), avg(values(prev, "download"))],
        [t("Download massimo (Mbps)"), max(values(cur, "download")), max(values(prev, "download"))],
        [t("Upload medio (Mbps)"), avg(values(cur, "upload")), avg(values(prev, "upload"))],
        [t("Upload massimo (Mbps)"), max(values(cur, "upload")), max(values(prev, "upload"))],
        [t("Latenza media (ms)"), avg(values(cur, "latency")), avg(values(prev, "latency"))],
        [t("Misure"), cur.length, prev.length],
      ];
      $("#compare-table thead").innerHTML =
        `<tr><th></th><th class="num">${fmtFull(state.data.from)} → ${fmtFull(state.data.to)}</th>`
        + `<th class="num">${fmtFull(d.from)} → ${fmtFull(d.to)}</th><th class="num">${t("Differenza")}</th></tr>`;
      $("#compare-table tbody").replaceChildren(...rowsCmp.map(([l, a, b], i) => row([
        { text: l }, { text: fmtNum(a, i === 5 ? 0 : 1), cls: "num" }, { text: fmtNum(b, i === 5 ? 0 : 1), cls: "num" },
        { text: i === 5 ? "" : delta(a, b), cls: `num ${a !== null && b && a < b ? "warn" : ""}` },
      ])));
      const N = 120;
      const labels = Array.from({ length: N }, (_, i) => fmtDateTime(new Date(start + (i + 0.5) * (span / N)).toISOString()));
      const pS = start - shift;
      drawChart("chart-cmp-down", labels, [
        ds(t("Periodo selezionato"), buckets(cur, start, span, N, "download"), DOWN),
        ds(t("Periodo di confronto"), buckets(prev, pS, span, N, "download"), C("--off"), { borderDash: [4, 3] }),
      ]);
      drawChart("chart-cmp-up", labels, [
        ds(t("Periodo selezionato"), buckets(cur, start, span, N, "upload"), UP),
        ds(t("Periodo di confronto"), buckets(prev, pS, span, N, "upload"), C("--off"), { borderDash: [4, 3] }),
      ]);
      $("#compare-result").hidden = false;
      Object.values(window.AM.charts).forEach((c) => c.resize());
    } catch (e) { toast(t("Confronto non riuscito: {p0}", { p0: e.message }), "error"); }
  }

  // ------------------------------------------------------------------- CSV
  function exportCsv() {
    if (!state.data || !state.data.rows.length) { toast(t("Nessuna misura da esportare"), "error"); return; }
    const n = (v) => (v === null || v === undefined ? "" : String(v).replace(".", ","));
    const lines = ["timestamp;download_mbps;upload_mbps;latenza_ms;esito;origine"];
    state.data.rows.forEach((r) => lines.push([r.iso.replace("T", " "), n(r.download), n(r.upload), n(r.latency), r.status || "", r.provider].join(";")));
    const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = el("a", { href: URL.createObjectURL(blob), download: `connessione_${state.data.from.slice(0, 10)}_${state.data.to.slice(0, 10)}.csv` });
    document.body.append(a); a.click(); a.remove();
  }

  // ----------------------------------------------------------------- eventi
  document.addEventListener("DOMContentLoaded", () => {
    const buttons = $$("#conn-period button");
    buttons.forEach((b) => b.addEventListener("click", () => {
      buttons.forEach((x) => x.classList.toggle("active", x === b));
      state.range = b.dataset.range; state.custom = null; load();
    }));
    $("#conn-custom").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const f = new FormData(ev.target);
      if (f.get("from") >= f.get("to")) { toast(t("La data di fine deve essere successiva a quella di inizio"), "error"); return; }
      buttons.forEach((x) => x.classList.remove("active"));
      state.custom = { from: f.get("from"), to: f.get("to") }; load();
    });
    $("#conn-csv").addEventListener("click", exportCsv);
    $("#compare-form").addEventListener("submit", runCompare);
    window.AM.onView("connessione", load);
  });
})();
