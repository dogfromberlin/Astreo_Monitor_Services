/* Astreo Monitor - vista Log: journal dei servizi monitorati e di Astreo Monitor. */
(() => {
  "use strict";
  const { t, $, api, el, toast, fmtFull, isView } = window.AM;
  let timer = null;

  async function loadUnits() {
    try {
      const d = await api("/api/v1/logs/units");
      const sel = $("#log-unit");
      const all = d.units.map((u) => u.unit).join(",");
      sel.replaceChildren(el("option", { value: all }, t("Tutti i servizi")),
        ...d.units.map((u) => el("option", { value: u.unit }, `${u.label} (${u.unit})`)));
    } catch (e) { toast(e.message, "error"); }
  }

  async function show(ev) {
    if (ev) ev.preventDefault();
    const f = $("#log-filters").elements;
    if (!f.unit.value) return;
    const q = new URLSearchParams({ units: f.unit.value, since: f.since.value, priority: f.priority.value, grep: f.grep.value, lines: 500 });
    let d;
    try { d = await api(`/api/v1/logs?${q}`); } catch (e) { toast(e.message, "error"); return; }
    $("#log-error").hidden = !d.error;
    $("#log-error").textContent = d.error || "";
    const box = $("#log-box");
    const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
    box.replaceChildren(...(d.entries.length ? d.entries.map((e) => {
      const line = el("div", { class: `log-line p${e.priority}` });
      line.append(el("time", {}, fmtFull(e.time)), el("span", { class: "src", title: e.unit }, e.ident || e.unit),
                  el("span", { class: "msg" }, e.message));
      return line;
    }) : [el("div", { class: "log-empty" }, d.error ? "" : t("Nessuna riga nel periodo con questi filtri."))]));
    $("#log-count").textContent = d.entries.length ? t("{p0} righe (le più recenti in fondo)", { p0: d.entries.length }) : "";
    if (atBottom || !ev) box.scrollTop = box.scrollHeight;
  }

  function follow() {
    clearInterval(timer);
    if ($("#log-follow").checked) timer = setInterval(() => { if (isView("log") && !document.hidden) show(); }, 10_000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.AM.IS_VIEWER) return;
    $("#log-filters").addEventListener("submit", show);
    $("#log-follow").addEventListener("change", follow);
    window.AM.onView("log", async () => { if (!$("#log-unit").options.length) await loadUnits(); show(); });
  });
})();
