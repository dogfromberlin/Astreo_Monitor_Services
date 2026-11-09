/* Astreo Monitor 4.1 - Avvisi ed eventi: eventi di tutti i server in un elenco unico, con filtri, e notifiche inviate. */
(() => {
  "use strict";
  const { t, $, $$, api, el, row, fmtFull, IS_VIEWER, every, onView, EVENT_COLOR } = window.AM;
  const state = { range: "24h", events: [], kinds: {}, hosts: [] };
  const CHANNEL = { email: "Email", telegram: "Telegram", whatsapp: "WhatsApp", ntfy: "ntfy", gotify: "Gotify", discord: "Discord", webhook: "Webhook" };
  const SEV_CLASS = { alert: "alert", warning: "warning", info: "info" };

  async function loadEvents() {
    try { state.hosts = (await api("/api/v1/hosts")).hosts.filter((h) => h.enabled || h.kind === "local"); }
    catch (e) { state.hosts = [{ id: 1, name: t("server centrale") }]; }
    const sel = $("#ev-host");
    const keep = sel.value;
    sel.replaceChildren(el("option", { value: "" }, t("Tutti")), ...state.hosts.map((h) => el("option", { value: String(h.id) }, h.name)));
    sel.value = state.hosts.some((h) => String(h.id) === keep) ? keep : "";
    const lists = await Promise.all(state.hosts.map((h) => api(`/api/v1/events?range=${state.range}&host=${h.id}`)
      .then((d) => { Object.assign(state.kinds, d.kinds || {}); return d.events.map((e) => ({ ...e, host: h.name, host_id: h.id })); })
      .catch(() => [])));
    state.events = lists.flat().sort((a, b) => (a.time < b.time ? 1 : -1));
    const ksel = $("#ev-kind");
    const kkeep = ksel.value;
    const present = [...new Set(state.events.map((e) => e.kind))];
    ksel.replaceChildren(el("option", { value: "" }, t("Tutti")), ...present.map((k) => el("option", { value: k }, state.kinds[k] || k)));
    ksel.value = present.includes(kkeep) ? kkeep : "";
    render();
  }

  function render() {
    const host = $("#ev-host").value, kind = $("#ev-kind").value, sev = $("#ev-sev").value;
    const list = state.events.filter((e) => (!host || String(e.host_id) === host) && (!kind || e.kind === kind)
      && (!sev || (sev === "info" ? !["alert", "warning"].includes(e.severity) : e.severity === sev)));
    const alerts = list.filter((e) => e.severity === "alert").length;
    $("#ev-sum").textContent = list.length === 1 ? t("1 evento") : t("{p0} eventi", { p0: list.length })
      + (alerts ? ` · ${alerts === 1 ? t("1 allarme") : t("{p0} allarmi", { p0: alerts })}` : "");
    const multi = state.hosts.length > 1 && !host;
    $("#ev-list").replaceChildren(...(list.length ? list.slice(0, 300).map((e) => {
      const li = el("li", { class: SEV_CLASS[e.severity] || "info" });
      li.style.setProperty("--chip", EVENT_COLOR[e.kind] || "#E0A22E");
      const head = el("div", { class: "ev-head" });
      head.append(el("time", { datetime: e.time }, fmtFull(e.time)), el("span", { class: "ev-kind" }, state.kinds[e.kind] || e.kind));
      if (multi) head.append(el("span", { class: "ev-host" }, e.host));
      li.append(head, el("strong", {}, e.title));
      if (e.detail) li.append(el("span", { class: "ev-detail" }, e.detail));
      return li;
    }) : [el("li", { class: "empty" }, state.events.length ? t("Nessun evento con questi filtri.") : t("Nessun evento nel periodo."))]));
  }

  async function loadSent() {
    if (IS_VIEWER) return;
    try {
      const d = await api("/api/v1/notify/log");
      const label = { inviata: t("Inviata"), fallita: t("Non inviata"), "in coda": t("In coda") };
      $("#sent-sum").textContent = d.pending ? t("Avvisi in coda ora: {p0}.", { p0: d.pending }) : t("ultime 30");
      $("#sent-log tbody").replaceChildren(...d.items.map((r) => row([
        { text: fmtFull(r.timestamp), label: t("Quando") }, { text: CHANNEL[r.channel] || r.channel, label: t("Canale") },
        { text: r.subject, label: t("Oggetto"), cls: "subject" },
        { text: `${label[r.status] || r.status}${r.error ? `: ${r.error}` : ""}`, label: t("Esito"),
          cls: r.status === "fallita" ? "alert" : r.status === "in coda" ? "warn" : "" },
      ])));
    } catch (e) { /* registro non disponibile */ }
  }

  // 4.4: silenzi attivi
  async function loadSilences() {
    let lst = [];
    try { lst = (await api("/api/v1/silences")).silences; } catch (e) { return; }
    const SCOPE = { all: t("tutto"), host: t("server"), source: t("tipo di evento"), service: t("servizio") };
    $("#sil-list").replaceChildren(...(lst.length ? lst.map((s) => {
      const li = el("li");
      li.append(el("strong", {}, s.label || SCOPE[s.scope]), el("span", {}, `${SCOPE[s.scope]} · ${t("fino alle {p0}", { p0: s.until.slice(11, 16) })}${s.by ? " · " + s.by : ""}`));
      if (!IS_VIEWER) {
        const b = el("button", { type: "button", class: "btn small" }, t("Riattiva"));
        b.addEventListener("click", () => window.AM.unsilence(s.id, loadSilences));
        li.append(b);
      }
      return li;
    }) : [el("li", { class: "hint" }, t("Nessun silenzio attivo: gli avvisi partono normalmente."))]));
    if (!IS_VIEWER && window.AM.silenceButton && !$("#sil-all").children.length) {
      $("#sil-all").append(window.AM.silenceButton({ scope: "all" }, t("tutti gli avvisi"), loadSilences));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    onView("avvisi", loadSilences);
    $("#ev-period").addEventListener("click", (ev) => {
      const b = ev.target.closest("button[data-range]");
      if (!b) return;
      $$("#ev-period button").forEach((x) => x.classList.toggle("active", x === b));
      state.range = b.dataset.range;
      loadEvents();
    });
    ["#ev-host", "#ev-kind", "#ev-sev"].forEach((id) => $(id).addEventListener("change", render));
    onView("avvisi", () => { loadEvents(); loadSent(); });
    every(60_000, () => { loadEvents(); loadSent(); }, "avvisi");
  });
})();
