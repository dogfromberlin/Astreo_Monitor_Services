// 4.6: Alimentazione (UPS): stato, carica, autonomia, carico, storico, aggiunta e prova
(() => {
  "use strict";
  const { t, $, $$, api, el, toast, IS_VIEWER, onView, every, isView, fmtDateTime, drawChart, ds, PALETTE } = window.AM;
  const STATUS = { online: ["", t("dalla rete")], battery: ["alert", t("a batteria")], low: ["alert", t("batteria scarica")],
                   bypass: ["warn", t("bypass")], off: ["warn", t("spento")], unknown: ["wait", t("sconosciuto")] };
  let list = [], range = "24h";

  const mins = (s) => (s === null || s === undefined ? "–" : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : `${Math.round(s / 60)} min`);
  const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v)}%`);
  const volt = (v) => (v === null || v === undefined ? "–" : `${Math.round(v)} V`);

  function state(u) {
    const l = u.last || {};
    if (!l.reading) return ["wait", l.error ? t("non raggiungibile") : t("in attesa della prima lettura")];
    if ((l.fails || 0) >= 3) return ["alert", t("non raggiungibile")];
    return STATUS[l.reading.status] || STATUS.unknown;
  }

  function meter(v, lvl) {
    const m = el("div", { class: `meter ${lvl}` }); const i = el("i"); i.style.width = `${Math.max(0, Math.min(100, v || 0))}%`; m.append(i); return m;
  }

  function card(u) {
    const r = (u.last || {}).reading || {};
    const [cls, label] = state(u);
    const c = el("article", { class: "ups-card" });
    const head = el("div", { class: "card-head" });
    const who = el("div", { class: "who" });
    who.append(el("strong", {}, u.name), el("span", {}, [r.manufacturer, r.model].filter(Boolean).join(" ") || `${u.backend} · ${u.host}`));
    head.append(who, el("span", { class: `pill ${cls}` }, label));
    c.append(head);
    const grid = el("div", { class: "ups-grid" });
    const ch = el("div", { class: "metric" });
    ch.append(el("span", { class: "label" }, t("Carica")), el("span", { class: "value" }, pct(r.charge)),
              meter(r.charge, r.charge <= 30 ? "alert" : r.charge <= 60 ? "warn" : "ok"));
    const ld = el("div", { class: "metric" });
    ld.append(el("span", { class: "label" }, t("Carico")), el("span", { class: "value" }, pct(r.load)),
              meter(r.load, r.load >= 90 ? "alert" : r.load >= 75 ? "warn" : "ok"));
    const rt = el("div", { class: "metric" });
    rt.append(el("span", { class: "label" }, t("Autonomia")), el("span", { class: "value" }, mins(r.runtime_s)));
    grid.append(ch, ld, rt);
    c.append(grid);
    const kv = el("dl", { class: "kv" });
    const add = (k, v) => { if (v !== null && v !== undefined && v !== "") kv.append(el("dt", {}, k), el("dd", {}, v)); };
    add(t("Tensione in ingresso"), volt(r.input_v)); add(t("Tensione in uscita"), volt(r.output_v));
    add(t("Temperatura"), r.temperature != null ? `${Math.round(r.temperature)} °C` : null);
    add(t("Avvisi dell'UPS"), [(r.flags || []).includes("replace") ? t("batteria da sostituire") : "", (r.flags || []).includes("overload") ? t("sovraccarico") : ""].filter(Boolean).join(", ") || null);
    add(t("Ultimo test"), r.test_result); add(t("Numero di serie"), r.serial);
    const lb = (u.last || {}).last_blackout;
    add(t("Ultimo blackout"), lb ? t("{p0}, durato {p1} min", { p0: fmtDateTime(lb.since), p1: lb.minutes }) : null);
    add(t("Ultima lettura"), (u.last || {}).read_at ? fmtDateTime(u.last.read_at) : null);
    if ((u.last || {}).error) add(t("Errore"), u.last.error);
    c.append(kv);
    if (!IS_VIEWER) {
      const acts = el("div", { class: "acts" });
      const tog = el("button", { type: "button", class: "btn small" }, u.enabled ? t("Sospendi") : t("Riattiva"));
      tog.addEventListener("click", async () => { try { await api(`/api/v1/ups/${u.id}`, { method: "PUT", json: { enabled: !u.enabled } }); load(); } catch (e) { toast(e.message, "error"); } });
      const del = el("button", { type: "button", class: "btn small danger" }, t("Elimina"));
      del.addEventListener("click", async () => {
        if (!confirm(t("Eliminare l'UPS {p0} e il suo storico?", { p0: u.name }))) return;
        try { await api(`/api/v1/ups/${u.id}`, { method: "DELETE", json: {} }); toast(t("UPS eliminato")); load(); } catch (e) { toast(e.message, "error"); }
      });
      acts.append(tog, del); c.append(acts);
    }
    return c;
  }

  async function load() {
    try { list = (await api("/api/v1/ups")).ups; } catch (e) { return; }
    $("#ups-list").replaceChildren(...(list.length ? list.map(card)
      : [el("p", { class: "hint ups-empty" }, t("Nessun UPS. Aggiungine uno qui sotto: si collega a un server NUT (anche su un NAS), ad apcupsd o via SNMP."))]));
    const sel = $("#ups-hist-sel"), keep = sel.value;
    sel.replaceChildren(...list.map((u) => el("option", { value: String(u.id) }, u.name)));
    if (keep && list.some((u) => String(u.id) === keep)) sel.value = keep;
    $("#ups-hist").hidden = !list.length;
    if (list.length) history();
  }

  async function history() {
    const id = $("#ups-hist-sel").value;
    if (!id) return;
    let d;
    try { d = await api(`/api/v1/ups/${id}/history?range=${range}`); } catch (e) { return; }
    const s = d.samples;
    const lab = s.map((x) => { const dt = new Date(x.timestamp); return range === "24h" ? dt.toLocaleTimeString(window.AM.LOCALE, { hour: "2-digit", minute: "2-digit" }) : dt.toLocaleDateString(window.AM.LOCALE, { day: "2-digit", month: "2-digit" }) + " " + dt.toLocaleTimeString(window.AM.LOCALE, { hour: "2-digit", minute: "2-digit" }); });
    drawChart("ch-ups", lab, [ds(t("Carica %"), s.map((x) => x.charge), PALETTE[0]), ds(t("Carico %"), s.map((x) => x.load), PALETTE[2])], { max: 100 });
  }

  // ------------------------------------------------------ modulo di aggiunta
  function formData() {
    const f = $("#ups-form");
    return { name: f.name.value.trim(), backend: f.backend.value, host: f.host.value.trim(), port: f.port.value ? Number(f.port.value) : null,
             ups_name: f.ups_name.value.trim(), community: f.community.value.trim() };
  }
  function syncForm() {
    const f = $("#ups-form"), b = f.backend.value;
    f.port.placeholder = { nut: "3493", apcupsd: "3551", snmp: "161" }[b];
    f.querySelector(".nut-only").hidden = b !== "nut";
    f.querySelector(".snmp-only").hidden = b !== "snmp";
  }

  document.addEventListener("DOMContentLoaded", () => {
    onView("alimentazione", load);
    every(30_000, () => { if (isView("alimentazione")) load(); });
    $$("#ups-hist [data-range]").forEach((b) => b.addEventListener("click", () => {
      range = b.dataset.range; $$("#ups-hist [data-range]").forEach((x) => x.classList.toggle("active", x === b)); history();
    }));
    $("#ups-hist-sel").addEventListener("change", history);
    $("#ups-form").backend.addEventListener("change", syncForm);
    syncForm();
    $("#ups-find").addEventListener("click", async () => {
      const d = formData();
      if (!d.host) { toast(t("Scrivi prima l'indirizzo"), "error"); return; }
      try {
        const r = await api("/api/v1/ups/discover", { method: "POST", json: d });
        $("#ups-names").replaceChildren(...r.ups.map((u) => el("option", { value: u.name }, u.description || u.name)));
        if (r.ups.length === 1) $("#ups-form").ups_name.value = r.ups[0].name;
        toast(r.ups.length ? t("Trovati: {p0}", { p0: r.ups.map((u) => u.name).join(", ") }) : t("Nessun UPS su questo server"));
      } catch (e) { toast(e.message, "error"); }
    });
    $("#ups-test").addEventListener("click", async () => {
      const out = $("#ups-test-out");
      out.textContent = t("Prova in corso…"); out.className = "ups-test-out";
      try {
        const r = (await api("/api/v1/ups/test", { method: "POST", json: formData() })).reading;
        out.textContent = t("Letto: {p0} · carica {p1} · carico {p2} · {p3}", { p0: (STATUS[r.status] || STATUS.unknown)[1], p1: pct(r.charge), p2: pct(r.load),
                                                                             p3: [r.manufacturer, r.model].filter(Boolean).join(" ") || "–" });
        out.className = "ups-test-out ok-text";
      } catch (e) { out.textContent = e.message; out.className = "ups-test-out alert-text"; }
    });
    $("#ups-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try { await api("/api/v1/ups", { method: "POST", json: formData() }); toast(t("UPS aggiunto: la prima lettura arriva entro un minuto")); ev.target.reset(); syncForm(); load(); }
      catch (e) { toast(e.message, "error"); }
    });
  });

  // per la Panoramica
  window.AM.upsState = state;
  window.AM.upsMins = mins;
})();
