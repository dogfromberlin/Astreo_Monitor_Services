/* Astreo Monitor - vista Impostazioni: speedtest, notifiche, servizi. */
(() => {
  "use strict";
  const { $, $$, api, el, row, toast, fmtFull, fmtDateTime, fmtNum } = window.AM;
  const CHANNEL_LABEL = { email: "Email", telegram: "Telegram", whatsapp: "WhatsApp" };
  let settings = null;      // { values, meta, sources, channels, email }
  let catalog = [];

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
      const v = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value) : input.value;
      if (settings.meta[k] && settings.meta[k].secret && (v === "" || String(v).includes("•"))) return;
      if (v !== settings.values[k]) out[k] = v;
    });
    return out;
  }
  async function saveForm(form, label) {
    const changes = readForm(form);
    if (!Object.keys(changes).length) { toast("Nessuna modifica da salvare"); return; }
    try {
      settings = await api("/api/v1/settings", { method: "PUT", json: changes });
      $$("form.settings-form").forEach(fillForm);
      renderTraffic();
      toast(`${label} salvate`);
    } catch (e) { toast(e.message, "error"); }
  }

  async function loadSettings() {
    try {
      settings = await api("/api/v1/settings");
      $$("form.settings-form").forEach(fillForm);
      renderRoutes();
      renderTraffic();
      $("#email-info").textContent = settings.email.recipients.length
        ? `Destinatari: ${settings.email.recipients.join(", ")} (server ${settings.email.smtp})`
        : "Nessun destinatario configurato.";
    } catch (e) { toast(`Impostazioni non disponibili: ${e.message}`, "error"); }
  }

  // ------------------------------------------------------------ speedtest
  function renderTraffic() {
    const v = settings.values;
    const dl = v["speedtest.streams"] * v["speedtest.rounds"] * v["speedtest.download_mb"];
    const ul = v["speedtest.streams"] * v["speedtest.rounds"] * v["speedtest.upload_mb"];
    $("#st-traffic").textContent = `Traffico per misura: circa ${dl} MB in download e ${ul} MB in upload; con 6 misure al giorno ${fmtNum(dl * 6 / 1000, 1)} GB al giorno.`;
  }

  async function loadSpeedtestStatus() {
    try {
      const s = await api("/api/v1/speedtest/status");
      const running = s.service.active === "activating" || s.service.sub === "start";
      $("#st-state").textContent = running ? "Misura in corso" : s.enabled ? "Attivo" : "Sospeso";
      $("#st-state").className = s.enabled ? "" : "warn-text";
      $("#st-next").textContent = s.enabled && s.timer.next_run ? fmtFull(s.timer.next_run) : "–";
      if (s.latest) {
        $("#st-last").textContent = `↓ ${fmtNum(s.latest.download_mbps, 0)}  ↑ ${fmtNum(s.latest.upload_mbps, 0)} Mbps`;
        $("#st-last-when").textContent = `${s.latest.status} alle ${fmtDateTime(s.latest.timestamp)}`;
      }
      const pause = $("#st-pause");
      pause.textContent = s.enabled ? "Sospendi" : "Riattiva";
      pause.dataset.paused = s.enabled ? "0" : "1";
      $("#st-run").disabled = running;
    } catch (e) { toast(`Stato speedtest non disponibile: ${e.message}`, "error"); }
  }

  async function runNow() {
    const msg = $("#st-run-msg");
    try {
      await api("/api/v1/speedtest/run", { method: "POST", json: {} });
      msg.textContent = "Misura avviata: dura circa un minuto, poi il risultato compare qui e nella vista Connessione.";
      msg.hidden = false;
      toast("Speedtest avviato");
      setTimeout(loadSpeedtestStatus, 3000);
      setTimeout(() => { loadSpeedtestStatus(); msg.hidden = true; }, 75_000);
    } catch (e) { toast(e.message, "error"); }
  }

  async function togglePause() {
    const paused = $("#st-pause").dataset.paused !== "1";
    if (paused && !confirm("Sospendere lo speedtest automatico? Resterà sospeso anche dopo un riavvio, finché non lo riattivi.")) return;
    try {
      const r = await api("/api/v1/speedtest/pause", { method: "POST", json: { paused } });
      await loadSettings();
      await loadSpeedtestStatus();
      toast(paused ? "Speedtest sospeso" : "Speedtest riattivato");
      if (r.timer_error) toast(`Impostazione salvata, ma il timer non è stato aggiornato: ${r.timer_error}`, "error");
    } catch (e) { toast(e.message, "error"); }
  }

  // ------------------------------------------------------------ notifiche
  function renderRoutes() {
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

  async function loadLog() {
    try {
      const rows = await api("/api/v1/notify/log");
      $("#notify-log tbody").replaceChildren(...rows.map((r) => row([
        { text: fmtFull(r.timestamp) }, { text: CHANNEL_LABEL[r.channel] || r.channel },
        { text: settings?.sources[r.source] || (r.source === "test" ? "Prova" : r.source) },
        { text: r.subject }, { text: r.ok ? "Inviata" : `Non inviata: ${r.error || ""}`, cls: r.ok ? "" : "alert" },
      ])));
    } catch (e) { /* tabella non ancora creata o DB assente: nessun registro */ }
  }

  async function testChannel(ch) {
    const changes = readForm($("#form-notify"));
    if (Object.keys(changes).length && !confirm("Ci sono modifiche non salvate: salvarle prima della prova?")) return;
    try {
      if (Object.keys(changes).length) settings = await api("/api/v1/settings", { method: "PUT", json: changes });
      const r = await api("/api/v1/notify/test", { method: "POST", json: { channel: ch } });
      toast(r.ok ? `Prova ${CHANNEL_LABEL[ch]} inviata` : `Prova ${CHANNEL_LABEL[ch]} non riuscita: ${r.error}`, r.ok ? "ok" : "error");
      fillForm($("#form-notify"));
      loadLog();
    } catch (e) { toast(e.message, "error"); }
  }

  // -------------------------------------------------------------- servizi
  async function loadCatalog() {
    try {
      catalog = await api("/api/v1/settings/services");
      renderServices();
    } catch (e) { toast(`Elenco servizi non disponibile: ${e.message}`, "error"); }
  }

  function renderServices() {
    const q = $("#svc-search").value.trim().toLowerCase();
    const only = $("#svc-only").checked;
    const monitored = catalog.filter((s) => s.monitored).sort((a, b) => (a.sort_order ?? 9e9) - (b.sort_order ?? 9e9));
    const others = catalog.filter((s) => !s.monitored);
    const list = [...monitored, ...(only ? [] : others)].filter((s) =>
      !q || s.unit.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q) || (s.label || "").toLowerCase().includes(q));
    $("#svc-count").textContent = `${monitored.length} monitorati su ${catalog.length} servizi`;
    $("#svc-table tbody").replaceChildren(...list.map((s) => {
      const tr = el("tr", { class: s.monitored ? "monitored" : "" });
      const led = el("span", { class: `led ${s.active === "active" ? "up" : s.monitored ? "down" : ""}`, title: `${s.active} (${s.sub})` });
      const name = el("div");
      name.append(el("strong", {}, s.unit), el("small", { class: "block" }, s.description || s.load));
      const label = el("input", { type: "text", value: s.label, maxlength: "100", "aria-label": `Etichetta di ${s.unit}` });
      label.disabled = !s.monitored;
      label.addEventListener("change", () => update(s, { label: label.value.trim() || s.unit }));
      const mon = switchEl(s.monitored, `Monitora ${s.unit}`, (v) => update(s, { monitored: v }));
      const ntf = switchEl(s.notify, `Avvisami per ${s.unit}`, (v) => update(s, { notify: v, monitored: v ? true : s.monitored }));
      const order = el("div", { class: "order" });
      if (s.monitored) {
        const i = monitored.indexOf(s);
        const upB = el("button", { type: "button", class: "ghost", "aria-label": "Sposta su" }, "↑");
        const dnB = el("button", { type: "button", class: "ghost", "aria-label": "Sposta giù" }, "↓");
        upB.disabled = i === 0; dnB.disabled = i === monitored.length - 1;
        upB.addEventListener("click", () => move(monitored, i, -1));
        dnB.addEventListener("click", () => move(monitored, i, 1));
        order.append(upB, dnB);
      }
      [ { node: led }, { node: name }, { node: label }, { node: mon }, { node: ntf }, { node: order } ].forEach((c) => {
        const td = el("td"); td.append(c.node); tr.append(td);
      });
      return tr;
    }));
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
      renderServices();
      toast(`${r.label}: salvato`);
      document.dispatchEvent(new Event("services-changed"));
    } catch (e) { toast(e.message, "error"); loadCatalog(); }
  }
  async function move(list, i, dir) {
    const units = list.map((s) => s.unit);
    [units[i], units[i + dir]] = [units[i + dir], units[i]];
    try {
      await api("/api/v1/settings/services-order", { method: "PUT", json: { units } });
      units.forEach((u, k) => { catalog.find((s) => s.unit === u).sort_order = (k + 1) * 10; });
      renderServices();
    } catch (e) { toast(e.message, "error"); }
  }

  // ----------------------------------------------------------------- avvio
  document.addEventListener("DOMContentLoaded", () => {
    $("#form-speedtest").addEventListener("submit", (ev) => { ev.preventDefault(); saveForm(ev.target, "Impostazioni speedtest"); });
    $("#form-notify").addEventListener("submit", (ev) => { ev.preventDefault(); saveForm(ev.target, "Impostazioni notifiche"); });
    $("#st-run").addEventListener("click", runNow);
    $("#st-pause").addEventListener("click", togglePause);
    $$("[data-test]").forEach((b) => b.addEventListener("click", () => testChannel(b.dataset.test)));
    $("#svc-search").addEventListener("input", renderServices);
    $("#svc-only").addEventListener("change", renderServices);
    document.addEventListener("subtab", (ev) => {
      if (ev.detail.group !== "set") return;
      if (ev.detail.sub === "notifiche") loadLog();
      if (ev.detail.sub === "servizi") loadCatalog();
      if (ev.detail.sub === "speedtest") loadSpeedtestStatus();
    });
    window.AM.onView("impostazioni", () => { loadSettings().then(loadLog); loadSpeedtestStatus(); loadCatalog(); });
    window.AM.every(30_000, loadSpeedtestStatus, "impostazioni");
  });
})();
