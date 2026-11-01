/* Astreo Monitor - controlli di altri dispositivi e servizi (vista Server e Impostazioni → Dispositivi). */
(() => {
  "use strict";
  const { t, $, $$, api, el, row, toast, fmtNum, fmtDateTime, fmtFull, drawChart, ds, C, every } = window.AM;
  const KIND = { ping: "Ping", tcp: "TCP", http: "HTTP" };
  const LED = { OK: "up", WARNING: "warn", DOWN: "down" };
  let list = [];

  const where = (c) => (c.kind === "tcp" ? `${c.target}:${c.port}` : c.target);
  function statusCell(c) {
    const st = c.state || {};
    const box = el("div");
    box.append(el("span", { class: `led ${LED[st.status] || ""}` }),
               document.createTextNode(` ${st.status || t("in attesa")}`));
    if (st.status && (st.warning || st.detail)) box.append(el("small", { class: "block" }, st.warning || st.detail));
    return box;
  }

  // ------------------------------------------------------------ vista Server
  async function load() {
    try {
      list = (await api("/api/v1/checks")).checks;
    } catch (e) { return; }
    const active = list.filter((c) => c.enabled);
    $("#checks-panel").hidden = active.length === 0;
    const down = active.filter((c) => (c.state || {}).status === "DOWN").length;
    $("#checks-summary").textContent = down === 1 ? t("1 non raggiungibile su {p0}", { p0: active.length })
      : down ? t("{p0} non raggiungibili su {p1}", { p0: down, p1: active.length })
      : t("{p0} controlli, tutti regolari", { p0: active.length });
    $("#checks-table tbody").replaceChildren(...active.map((c) => {
      const st = c.state || {};
      const tr = row([
        { text: c.name, label: t("Nome") },
        { text: `${KIND[c.kind]} ${where(c)}`, cls: "target", label: t("Controllo") },
        { node: statusCell(c), label: t("Stato") },
        { text: st.latency_ms != null ? `${fmtNum(st.latency_ms, 1)} ms` : "–", cls: "num", label: t("Latenza") },
        { text: c.availability_24h != null ? `${fmtNum(c.availability_24h, 2)}%` : "–", cls: "num", label: t("Disponibilità 24 ore") },
        { text: st.since ? fmtDateTime(st.since) : "–", label: t("Dal") },
      ]);
      tr.addEventListener("click", () => openHistory(c));
      return tr;
    }));
    if (window.AM.isView("impostazioni")) renderAdmin();
  }

  let current = null;
  async function openHistory(c, range = "24h") {
    current = c;
    $("#check-dialog-title").textContent = `${c.name} — ${KIND[c.kind]} ${where(c)}`;
    $$("#check-period button").forEach((b) => b.classList.toggle("active", b.dataset.range === range));
    if (!$("#check-dialog").open) $("#check-dialog").showModal();
    try {
      const h = await api(`/api/v1/checks/${c.id}/history?range=${range}`);
      const labels = h.labels.map(fmtDateTime);
      drawChart("chart-check-latency", labels, [ds(t("Latenza"), h.latency, C("--accent2"))]);
      drawChart("chart-check-up", labels, [ds(t("Raggiungibile (%)"), h.up, C("--ok"))], { max: 100 });
    } catch (e) { toast(e.message, "error"); }
  }

  // ---------------------------------------------------- Impostazioni → Dispositivi
  function renderAdmin() {
    $("#checks-empty").hidden = list.length > 0;
    $("#checks-admin tbody").replaceChildren(...list.map((c) => {
      const actions = el("div", { class: "row-actions" });
      const edit = el("button", { type: "button", class: "ghost" }, t("Modifica"));
      const del = el("button", { type: "button", class: "ghost danger" }, t("Elimina"));
      edit.addEventListener("click", () => fillForm(c));
      del.addEventListener("click", () => remove(c));
      actions.append(edit, del);
      return row([
        { text: c.name + (c.enabled ? "" : ` (${t("disattivato")})`), label: t("Nome") },
        { text: `${KIND[c.kind]} ${where(c)}`, cls: "target", label: t("Controllo") },
        { text: `${c.interval_s} s`, label: t("Ogni") },
        { node: statusCell(c), label: t("Stato") },
        { node: actions, label: "" },
      ]);
    }));
  }

  const form = () => $("#check-form");
  function syncKind() {
    const kind = form().elements.kind.value;
    $$("#check-form [data-for]").forEach((n) => { n.hidden = n.dataset.for !== kind; });
  }
  function readForm() {
    const f = form().elements;
    return { name: f.name.value, kind: f.kind.value, target: f.target.value.trim(), port: f.port.value || null,
             interval_s: f.interval_s.value, timeout_s: f.timeout_s.value, retries: f.retries.value,
             expect_status: f.expect_status.value, keyword: f.keyword.value, cert_warning_days: f.cert_warning_days.value,
             verify_tls: f.verify_tls.checked, enabled: f.enabled.checked };
  }
  function fillForm(c) {
    const f = form().elements;
    f.id.value = c ? c.id : "";
    f.name.value = c ? c.name : ""; f.kind.value = c ? c.kind : "ping"; f.target.value = c ? c.target : "";
    f.port.value = c && c.port ? c.port : ""; f.interval_s.value = c ? c.interval_s : 60; f.timeout_s.value = c ? c.timeout_s : 10;
    f.retries.value = c ? c.retries : 2; f.expect_status.value = c && c.expect_status ? c.expect_status : "";
    f.keyword.value = c && c.keyword ? c.keyword : ""; f.cert_warning_days.value = c ? c.cert_warning_days : 14;
    f.verify_tls.checked = c ? c.verify_tls : true; f.enabled.checked = c ? c.enabled : true;
    $("#check-form-title").textContent = c ? t("Modifica: {p0}", { p0: c.name }) : t("Nuovo controllo");
    $("#check-cancel").hidden = !c;
    $("#check-test-result").textContent = "";
    syncKind();
    if (c) form().scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function test() {
    const out = $("#check-test-result");
    out.textContent = t("Prova in corso…");
    try {
      const r = await api("/api/v1/checks/test", { method: "POST", json: readForm() });
      out.textContent = (r.ok ? "✔ " : "✘ ") + [r.detail, r.latency_ms != null ? `${fmtNum(r.latency_ms, 1)} ms` : null, r.warning]
        .filter(Boolean).join(" — ");
    } catch (e) { out.textContent = `✘ ${e.message}`; }
  }
  async function save(ev) {
    ev.preventDefault();
    const id = form().elements.id.value;
    try {
      await api(id ? `/api/v1/checks/${id}` : "/api/v1/checks", { method: id ? "PUT" : "POST", json: readForm() });
      toast(t("Controllo salvato: il primo risultato arriva entro un minuto."));
      fillForm(null);
      load();
    } catch (e) { toast(e.message, "error"); }
  }
  async function remove(c) {
    if (!confirm(t("Eliminare il controllo «{p0}» e il suo storico?", { p0: c.name }))) return;
    try { await api(`/api/v1/checks/${c.id}`, { method: "DELETE", json: {} }); toast(t("Controllo eliminato")); load(); }
    catch (e) { toast(e.message, "error"); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    load();
    every(60_000, load, "server");
    window.AM.onView("server", load);
    $$("#check-period button").forEach((b) => b.addEventListener("click", () => current && openHistory(current, b.dataset.range)));
    if (window.AM.IS_VIEWER) return;
    form().elements.kind.addEventListener("change", syncKind);
    form().addEventListener("submit", save);
    $("#check-test").addEventListener("click", test);
    $("#check-cancel").addEventListener("click", () => fillForm(null));
    document.addEventListener("subtab", (ev) => { if (ev.detail.sub === "dispositivi") { fillForm(null); load().then(renderAdmin); } });
    syncKind();
  });
})();
