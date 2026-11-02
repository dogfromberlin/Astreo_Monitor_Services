/* Astreo Monitor - vista Impostazioni: speedtest, notifiche, servizi. */
(() => {
  "use strict";
  const { t, $, $$, api, el, row, toast, fmtFull, fmtDateTime, fmtNum } = window.AM;
  const CHANNEL_LABEL = { email: "Email", telegram: "Telegram", whatsapp: "WhatsApp", ntfy: "ntfy", gotify: "Gotify",
                          discord: "Discord", webhook: "Webhook" };
  const MODE_LABEL = { escalation: t("Solo se peggiora"), change: t("A ogni cambio") };
  let settings = null;      // { values, meta, sources, channels, policy_sources }
  let catalog = [];
  let viewOrder = null;     // ordine delle righe dei servizi, fisso finché non cambi filtro

  // ------------------------------------------------------ form <-> valori
  function fillForm(form) {
    $$("[data-key]", form).forEach((input) => {
      const v = settings.values[input.dataset.key];
      if (input.type === "checkbox") input.checked = Boolean(v);
      else input.value = v ?? "";
      const m = settings.meta[input.dataset.key];
      if (m && input.type === "number") {
        if (m.min !== null) input.min = m.min;
        if (m.max !== null) input.max = m.max;
      }
    });
  }
  function readForm(form) {
    const out = {};
    $$("[data-key]", form).forEach((input) => {
      const k = input.dataset.key;
      const v = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value) : input.value.trim();
      if (settings.meta[k] && settings.meta[k].secret && (v === "" || String(v).includes("•"))) return;
      if (v !== settings.values[k]) out[k] = v;
    });
    return out;
  }
  async function saveForm(form, label) {
    const changes = readForm(form);
    if (!Object.keys(changes).length) { toast(t("Nessuna modifica da salvare")); return; }
    try {
      settings = await api("/api/v1/settings", { method: "PUT", json: changes });
      $$("form.settings-form").forEach(fillForm);
      renderTraffic();
      toast(`${label} salvate`);
      loadLog();
    } catch (e) { toast(e.message, "error"); }
  }

  async function loadSettings() {
    try {
      settings = await api("/api/v1/settings");
      renderRoutes();
      renderRules();
      $$("form.settings-form").forEach(fillForm);
      renderTraffic();
    } catch (e) { toast(t("Impostazioni non disponibili: {p0}", { p0: e.message }), "error"); }
  }

  // ------------------------------------------------------------ speedtest
  function renderTraffic() {
    const v = settings.values;
    const dl = v["speedtest.streams"] * v["speedtest.rounds"] * v["speedtest.download_mb"];
    const ul = v["speedtest.streams"] * v["speedtest.rounds"] * v["speedtest.upload_mb"];
    $("#st-traffic").textContent = t("Traffico per misura: circa {p0} MB in download e {p1} MB in upload; con 6 misure al giorno {p2} GB al giorno.", { p0: dl, p1: ul, p2: fmtNum(dl * 6 / 1000, 1) });
  }

  async function loadSpeedtestStatus() {
    try {
      const s = await api("/api/v1/speedtest/status");
      const running = s.service.active === "activating" || s.service.sub === "start";
      $("#st-state").textContent = running ? t("Misura in corso") : s.enabled ? t("Attivo") : t("Sospeso");
      $("#st-state").className = s.enabled ? "" : "warn-text";
      $("#st-next").textContent = s.enabled && s.timer.next_run ? fmtFull(s.timer.next_run) : "–";
      if (s.latest) {
        $("#st-last").textContent = `↓ ${fmtNum(s.latest.download_mbps, 0)}  ↑ ${fmtNum(s.latest.upload_mbps, 0)} Mbps`;
        $("#st-last-when").textContent = t("{p0} alle {p1}", { p0: s.latest.status, p1: fmtDateTime(s.latest.timestamp) });
      }
      const pause = $("#st-pause");
      pause.textContent = s.enabled ? t("Sospendi") : t("Riattiva");
      pause.dataset.paused = s.enabled ? "0" : "1";
      $("#st-run").disabled = running;
    } catch (e) { toast(t("Stato speedtest non disponibile: {p0}", { p0: e.message }), "error"); }
  }

  async function runNow() {
    const msg = $("#st-run-msg");
    try {
      await api("/api/v1/speedtest/run", { method: "POST", json: {} });
      msg.textContent = t("Misura avviata: dura circa un minuto, poi il risultato compare qui e nella vista Connessione.");
      msg.hidden = false;
      toast(t("Speedtest avviato"));
      setTimeout(loadSpeedtestStatus, 3000);
      setTimeout(() => { loadSpeedtestStatus(); msg.hidden = true; }, 75_000);
    } catch (e) { toast(e.message, "error"); }
  }

  async function togglePause() {
    const paused = $("#st-pause").dataset.paused !== "1";
    if (paused && !confirm(t("Sospendere lo speedtest automatico? Resterà sospeso anche dopo un riavvio, finché non lo riattivi."))) return;
    try {
      const r = await api("/api/v1/speedtest/pause", { method: "POST", json: { paused } });
      await loadSettings();
      await loadSpeedtestStatus();
      toast(paused ? t("Speedtest sospeso") : t("Speedtest riattivato"));
      if (r.timer_error) toast(t("Impostazione salvata, ma il timer non è stato aggiornato: {p0}", { p0: r.timer_error }), "error");
    } catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------------------ notifiche
  function renderRoutes() {
    $("#routes thead").replaceChildren(row([{ text: t("Evento") }, ...settings.channels.map((ch) => ({ text: CHANNEL_LABEL[ch] || ch }))], "th"));
    // interruttori dei canali per lo speedtest (scheda Speedtest)
    $("#st-routes").replaceChildren(...settings.channels.map((ch) => {
      const lab = el("label", { class: "switch" });
      const cb = el("input", { type: "checkbox", "data-key": `route.speedtest.${ch}` });
      cb.checked = Boolean(settings.values[`route.speedtest.${ch}`]);
      lab.append(cb, el("span", {}, CHANNEL_LABEL[ch] || ch));
      return lab;
    }));
    const tb = $("#routes tbody");
    tb.replaceChildren(...Object.entries(settings.sources).map(([src, label]) => {
      const tr = el("tr");
      tr.append(el("td", {}, label));
      settings.channels.forEach((ch) => {
        const td = el("td");
        const lab = el("label", { class: "switch compact" });
        const cb = el("input", { type: "checkbox", "data-key": `route.${src}.${ch}`, "aria-label": `${label} via ${CHANNEL_LABEL[ch]}` });
        cb.checked = Boolean(settings.values[`route.${src}.${ch}`]);
        lab.append(cb, el("span"));
        td.append(lab);
        tr.append(td);
      });
      return tr;
    }));
  }

  function renderRules() {
    $("#rules tbody").replaceChildren(...Object.entries(settings.policy_sources).map(([src, label]) => {
      const tr = el("tr");
      tr.append(el("td", { "data-label": t("Monitoraggio") }, label));
      const sel = el("select", { "data-key": `alert.${src}.mode`, "aria-label": t("Quando avvisare per {p0}", { p0: label }) });
      Object.entries(MODE_LABEL).forEach(([v, lbl]) => sel.append(el("option", { value: v }, lbl)));
      const td1 = el("td", { "data-label": t("Quando avvisare") }); td1.append(sel);
      const lab = el("label", { class: "switch compact" });
      lab.append(el("input", { type: "checkbox", "data-key": `alert.${src}.recovery`, "aria-label": t("Avviso di rientro per {p0}", { p0: label }) }), el("span"));
      const td2 = el("td", { "data-label": t("Al rientro in OK") }); td2.append(lab);
      const num = el("input", { type: "number", step: "1", min: "0", max: "720", "data-key": `alert.${src}.reminder_hours`, "aria-label": t("Promemoria per {p0}", { p0: label }) });
      const td3 = el("td", { "data-label": t("Promemoria (ore)") }); td3.append(num);
      tr.append(td1, td2, td3);
      return tr;
    }));
  }

  async function loadLog() {
    try {
      const data = await api("/api/v1/notify/log");
      const label = { inviata: t("Inviata"), fallita: t("Non inviata"), "in coda": t("In coda") };
      $("#notify-log tbody").replaceChildren(...data.items.map((r) => row([
        { text: fmtFull(r.timestamp), label: t("Quando") }, { text: CHANNEL_LABEL[r.channel] || r.channel, label: t("Canale") },
        { text: settings?.sources[r.source] || ({ test: t("Prova"), riepilogo: t("Riepilogo") }[r.source] || r.source), label: t("Evento") },
        { text: r.subject, label: t("Oggetto") },
        { text: `${label[r.status] || r.status}${r.error ? `: ${r.error}` : ""}`, label: t("Esito"),
          cls: r.status === "fallita" ? "alert" : r.status === "in coda" ? "warn" : "" },
      ])));
      $("#queue-info").textContent = data.pending ? t("Avvisi in coda ora: {p0}.", { p0: data.pending }) : "";
    } catch (e) { /* tabella non ancora creata o DB assente: nessun registro */ }
  }

  async function testChannel(ch) {
    const changes = readForm($("#form-notify"));
    if (Object.keys(changes).length && !confirm(t("Ci sono modifiche non salvate: salvarle prima della prova?"))) return;
    try {
      if (Object.keys(changes).length) settings = await api("/api/v1/settings", { method: "PUT", json: changes });
      const r = await api("/api/v1/notify/test", { method: "POST", json: { channel: ch } });
      toast(r.ok ? t("Prova {p0} inviata", { p0: CHANNEL_LABEL[ch] }) : t("Prova {p0} non riuscita: {p1}", { p0: CHANNEL_LABEL[ch], p1: r.error }),
            r.ok ? "ok" : "error");
      fillForm($("#form-notify"));
      loadLog();
    } catch (e) { toast(e.message, "error"); }
  }

  // -------------------------------------------------------------- moduli
  async function loadModulesTab() {
    try {
      const d = await api("/api/v1/integrations");
      $("#modules-table tbody").replaceChildren(...d.modules.map((m) => {
        const tr = el("tr");
        const st = el("span", { class: m.available ? "" : "warn-text" }, m.available ? `✔ ${m.reason}` : t("non presente — {p0}", { p0: m.reason }));
        const lab = el("label", { class: "switch compact" });
        lab.append(el("input", { type: "checkbox", "data-key": `ui.${m.key}`, "aria-label": `Mostra ${m.label}` }), el("span"));
        [[m.label, el("strong", {}, m.label)], [t("Sul server"), st], [t("Mostra"), lab]].forEach(([l, node]) => {
          const td = el("td", { "data-label": l }); td.append(node); tr.append(td);
        });
        return tr;
      }));
      if (settings) fillForm($("#form-modules"));
    } catch (e) { toast(t("Moduli non disponibili: {p0}", { p0: e.message }), "error"); }
  }
  async function testPihole() {
    const changes = readForm($("#form-modules"));
    try {
      if (Object.keys(changes).length) settings = await api("/api/v1/settings", { method: "PUT", json: changes });
      const r = await api("/api/v1/pihole/test", { method: "POST", json: {} });
      toast(r.ok ? t("Pi-hole raggiunto: {p0}", { p0: r.detail }) : `Pi-hole: ${r.detail}`, r.ok ? "ok" : "error");
      fillForm($("#form-modules"));
      window.AM.loadModules();
    } catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------- token per le integrazioni
  function renderToken() {
    const set = Boolean(settings && settings.values["api.token"]);
    $("#api-token-state").textContent = set ? t("Token attivo: /metrics e /api/v1/status rispondono a chi lo presenta.")
      : t("Nessun token: le integrazioni sono disattivate.");
    $("#api-token-del").hidden = !set;
  }
  async function newToken() {
    if (settings.values["api.token"] && !confirm(t("Il token attuale smetterà di funzionare. Generarne uno nuovo?"))) return;
    try {
      const r = await api("/api/v1/api-token", { method: "POST", json: {} });
      const box = $("#api-token-box");
      box.textContent = t("Copia ora il token, non verrà più mostrato:") + "\n" + r.token + "\n\n"
        + `curl -H "Authorization: Bearer ${r.token}" ${location.origin}/metrics`;
      box.hidden = false;
      settings.values["api.token"] = "••••";
      renderToken();
    } catch (e) { toast(e.message, "error"); }
  }
  async function delToken() {
    if (!confirm(t("Revocare il token? Prometheus e Home Assistant non potranno più leggere i dati."))) return;
    try {
      await api("/api/v1/api-token", { method: "DELETE", json: {} });
      settings.values["api.token"] = "";
      $("#api-token-box").hidden = true;
      renderToken();
      toast(t("Token revocato"));
    } catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------------------ heartbeat
  async function loadHeartbeat() {
    try {
      const h = await api("/api/v1/heartbeat");
      $("#hb-info").textContent = !h.time ? "" : h.ok ? t("Ultimo ping alle {p0}: inviato.", { p0: fmtFull(h.time) })
        : t("Ultimo ping alle {p0}: non inviato ({p1}).", { p0: fmtFull(h.time), p1: h.error });
    } catch (e) { /* */ }
  }
  async function testHeartbeat() {
    const changes = readForm($("#form-notify"));
    try {
      if (Object.keys(changes).length) settings = await api("/api/v1/settings", { method: "PUT", json: changes });
      const r = await api("/api/v1/heartbeat/test", { method: "POST", json: {} });
      toast(r.ok ? t("Ping di prova inviato") : t("Ping non riuscito: {p0}", { p0: r.error }), r.ok ? "ok" : "error");
      fillForm($("#form-notify"));
      loadHeartbeat();
    } catch (e) { toast(e.message, "error"); }
  }

  // -------------------------------------------------------------- servizi
  async function loadCatalog() {
    try {
      catalog = await api("/api/v1/settings/services");
      renderServices(true);
    } catch (e) { toast(t("Elenco servizi non disponibile: {p0}", { p0: e.message }), "error"); }
  }

  function monitoredSorted() {
    return catalog.filter((s) => s.monitored).sort((a, b) => (a.sort_order ?? 9e9) - (b.sort_order ?? 9e9));
  }

  /* L'ordine delle righe si calcola solo all'apertura e quando cambi ricerca o filtro:
     attivando o disattivando un servizio la riga resta dov'è e la pagina non si sposta. */
  function computeOrder() {
    const q = $("#svc-search").value.trim().toLowerCase();
    const only = $("#svc-only").checked;
    const mon = monitoredSorted();
    const list = [...mon, ...(only ? [] : catalog.filter((s) => !s.monitored))].filter((s) =>
      !q || s.unit.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q) || (s.label || "").toLowerCase().includes(q));
    viewOrder = list.map((s) => s.unit);
  }

  function serviceRow(s) {
    const mon = monitoredSorted();
    const tr = el("tr", { class: s.monitored ? "monitored" : "", "data-unit": s.unit });
    const led = el("span", { class: `led ${s.active === "active" ? "up" : s.monitored ? "down" : ""}`, title: `${s.active} (${s.sub})` });
    const name = el("div", { class: "svc-name" });
    name.append(el("strong", { title: s.unit }, s.unit), el("small", { class: "block" }, s.description || s.load));
    const label = el("input", { type: "text", value: s.label, maxlength: "100", "aria-label": t("Etichetta di {p0}", { p0: s.unit }) });
    label.disabled = !s.monitored;
    label.addEventListener("change", () => update(s, { label: label.value.trim() || s.unit }));
    const monSw = switchEl(s.monitored, `Monitora ${s.unit}`, (v) => update(s, { monitored: v }));
    const ntf = switchEl(s.notify, t("Avvisami per {p0}", { p0: s.unit }), (v) => update(s, { notify: v, monitored: v ? true : s.monitored }));
    const order = el("div", { class: "order" });
    if (s.monitored) {
      const i = mon.indexOf(s);
      const upB = el("button", { type: "button", class: "ghost", "aria-label": t("Sposta su") }, "↑");
      const dnB = el("button", { type: "button", class: "ghost", "aria-label": t("Sposta giù") }, "↓");
      upB.disabled = i <= 0; dnB.disabled = i === mon.length - 1;
      upB.addEventListener("click", () => move(i, -1));
      dnB.addEventListener("click", () => move(i, 1));
      order.append(upB, dnB);
    }
    [[t("Stato"), led], [t("Servizio"), name], [t("Etichetta"), label], [t("Monitora"), monSw], [t("Avvisami"), ntf], [t("Ordine"), order]].forEach(([l, node]) => {
      const td = el("td", { "data-label": l }); td.append(node); tr.append(td);
    });
    return tr;
  }

  function renderServices(resetOrder = false) {
    if (resetOrder || !viewOrder) computeOrder();
    const byUnit = Object.fromEntries(catalog.map((s) => [s.unit, s]));
    const y = window.scrollY;
    $("#svc-count").textContent = t("{p0} monitorati su {p1} servizi", { p0: monitoredSorted().length, p1: catalog.length });
    $("#svc-table tbody").replaceChildren(...viewOrder.filter((u) => byUnit[u]).map((u) => serviceRow(byUnit[u])));
    window.scrollTo({ top: y });
  }

  function switchEl(checked, aria, onChange) {
    const lab = el("label", { class: "switch compact" });
    const cb = el("input", { type: "checkbox", "aria-label": aria });
    cb.checked = checked;
    cb.addEventListener("change", () => onChange(cb.checked));
    lab.append(cb, el("span"));
    return lab;
  }
  async function update(s, changes) {
    try {
      const r = await api(`/api/v1/settings/services/${encodeURIComponent(s.unit)}`, { method: "PUT", json: changes });
      Object.assign(s, { monitored: Boolean(r.enabled), notify: Boolean(r.notify), label: r.label, sort_order: r.sort_order });
      renderServices(false);
      toast(`${r.label}: salvato`);
      document.dispatchEvent(new Event("services-changed"));
    } catch (e) { toast(e.message, "error"); loadCatalog(); }
  }
  async function move(i, dir) {
    const units = monitoredSorted().map((s) => s.unit);
    [units[i], units[i + dir]] = [units[i + dir], units[i]];
    try {
      await api("/api/v1/settings/services-order", { method: "PUT", json: { units } });
      units.forEach((u, k) => { catalog.find((s) => s.unit === u).sort_order = (k + 1) * 10; });
      document.dispatchEvent(new Event("services-changed"));
      renderServices(true);
    } catch (e) { toast(e.message, "error"); }
  }

  // ----------------------------------------------------------------- avvio
  document.addEventListener("DOMContentLoaded", () => {
    $("#form-speedtest").addEventListener("submit", (ev) => { ev.preventDefault(); saveForm(ev.target, t("Impostazioni speedtest")); });
    $("#form-notify").addEventListener("submit", (ev) => { ev.preventDefault(); saveForm(ev.target, t("Impostazioni notifiche")); });
    $("#form-modules").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      await saveForm(ev.target, t("Impostazioni dei moduli"));
      window.AM.loadModules();
    });
    $("#pihole-test").addEventListener("click", testPihole);
    $("#api-token-new").addEventListener("click", newToken);
    $("#api-token-del").addEventListener("click", delToken);
    $("#st-run").addEventListener("click", runNow);
    $("#hb-test").addEventListener("click", testHeartbeat);
    $("#summary-test").addEventListener("click", async () => {
      try {
        await api("/api/v1/summary/test", { method: "POST", json: {} });
        toast(t("Riepilogo inviato sui canali scelti per il Riepilogo settimanale"));
        loadLog();
      } catch (e) { toast(e.message, "error"); }
    });
    $("#st-pause").addEventListener("click", togglePause);
    $$("[data-test]").forEach((b) => b.addEventListener("click", () => testChannel(b.dataset.test)));
    $("#svc-search").addEventListener("input", () => renderServices(true));
    $("#svc-only").addEventListener("change", () => renderServices(true));
    document.addEventListener("subtab", (ev) => {
      if (ev.detail.group !== "set") return;
      if (ev.detail.sub === "notifiche") { loadLog(); loadHeartbeat(); }
      if (ev.detail.sub === "servizi") loadCatalog();
      if (ev.detail.sub === "speedtest") loadSpeedtestStatus();
      if (ev.detail.sub === "moduli") { loadModulesTab(); renderToken(); }
    });
    window.AM.onView("impostazioni", () => { loadSettings().then(() => { loadLog(); loadModulesTab(); }); loadSpeedtestStatus(); loadCatalog(); });
    window.AM.every(30_000, loadSpeedtestStatus, "impostazioni");
  });
})();
