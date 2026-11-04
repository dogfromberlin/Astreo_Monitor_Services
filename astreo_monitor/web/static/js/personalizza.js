/* Astreo Monitor 4.1 - Personalizza: ordine e visibilità delle card dentro ogni sezione.
   Una sezione è un contenitore [data-layout="nome"]; le sue card sono i figli diretti [data-card="id"].
   La disposizione è nelle preferenze dell'utente (/api/v1/ui/prefs, chiave "layout"), uguale su ogni dispositivo.
   Le card non citate nella disposizione salvata (ad esempio arrivate con una versione nuova) restano in fondo. */
(() => {
  "use strict";
  const { t, $, $$, api, el, toast, isView } = window.AM;
  // sezioni modificabili per vista; la fascia di stato e "Da controllare" restano fisse
  const VIEWS = { panoramica: ["ov-kpis", "ov-hosts", "ov-bottom"], server: ["srv-detail"] };
  let layout = {};
  let editing = null;                    // vista in modifica
  let saveTimer = null;

  const box = (sec) => document.querySelector(`[data-layout="${sec}"]`);
  const cards = (sec) => { const b = box(sec); return b ? [...b.children].filter((c) => c.dataset.card) : []; };
  const conf = (sec) => (layout[sec] = layout[sec] || { order: [], hidden: [] });
  const svg = (name) => {
    const ns = "http://www.w3.org/2000/svg";
    const s = document.createElementNS(ns, "svg");
    s.setAttribute("class", "icon"); s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS(ns, "use"); u.setAttribute("href", `#${name}`); s.append(u);
    return s;
  };
  const cardName = (c) => (c.querySelector("h2, .label, .who strong")?.textContent || c.dataset.card).trim();

  // ------------------------------------------------------------- applica
  function applyLayout(sec) {
    const b = box(sec);
    if (!b) return;
    const c = layout[sec] || { order: [], hidden: [] };
    const list = cards(sec);
    const pos = (x) => { const i = c.order.indexOf(x.dataset.card); return i < 0 ? 1000 + list.indexOf(x) : i; };
    [...list].sort((a, z) => pos(a) - pos(z)).forEach((x) => b.append(x));
    list.forEach((x) => x.classList.toggle("card-hidden", c.hidden.includes(x.dataset.card)));
    if (editing && VIEWS[editing].includes(sec)) addTools(sec);
  }
  const applyAll = () => Object.values(VIEWS).flat().forEach(applyLayout);

  function remember(sec) {
    const c = conf(sec);
    c.order = cards(sec).map((x) => x.dataset.card);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 600);
  }
  async function save() {
    try { await api("/api/v1/ui/prefs", { method: "PUT", json: { layout } }); }
    catch (e) { toast(t("Disposizione non salvata: {p0}", { p0: e.message }), "error"); }
  }

  // ------------------------------------------------------------- modifica
  function move(card, dir) {
    const sec = card.parentElement.dataset.layout;
    const sib = dir < 0 ? card.previousElementSibling : card.nextElementSibling;
    if (!sib || !sib.dataset.card) return;
    if (dir < 0) sib.before(card); else sib.after(card);
    remember(sec);
    card.querySelector(dir < 0 ? "[data-move='up']" : "[data-move='down']")?.focus();
  }

  function toggleHidden(card) {
    const sec = card.parentElement.dataset.layout;
    const c = conf(sec);
    const id = card.dataset.card;
    c.hidden = c.hidden.includes(id) ? c.hidden.filter((x) => x !== id) : [...c.hidden, id];
    card.classList.toggle("card-hidden", c.hidden.includes(id));
    remember(sec);
    tools(card);
    updateBanner();
  }

  function tools(card) {
    card.querySelector(":scope > .card-tools")?.remove();
    const name = cardName(card);
    const hidden = card.classList.contains("card-hidden");
    const bar = el("div", { class: "card-tools" });
    const grip = el("button", { type: "button", class: "grip", "aria-label": t("Trascina {p0} per spostarla", { p0: name }) });
    grip.append(svg("i-grip"), el("span", {}, t("Trascina")));
    grip.addEventListener("pointerdown", (ev) => startDrag(ev, card));
    grip.addEventListener("click", (ev) => ev.preventDefault());
    const up = el("button", { type: "button", "data-move": "up", "aria-label": t("Sposta {p0} prima", { p0: name }), title: t("Sposta prima") });
    up.append(svg("i-up"));
    up.addEventListener("click", (ev) => { ev.preventDefault(); move(card, -1); });
    const down = el("button", { type: "button", "data-move": "down", "aria-label": t("Sposta {p0} dopo", { p0: name }), title: t("Sposta dopo") });
    down.append(svg("i-down"));
    down.addEventListener("click", (ev) => { ev.preventDefault(); move(card, 1); });
    const eye = el("button", { type: "button", class: "eye", "aria-pressed": String(hidden),
                               "aria-label": hidden ? t("Mostra {p0}", { p0: name }) : t("Nascondi {p0}", { p0: name }),
                               title: hidden ? t("Mostra") : t("Nascondi") });
    eye.append(svg(hidden ? "i-eye-off" : "i-eye"));
    eye.addEventListener("click", (ev) => { ev.preventDefault(); toggleHidden(card); });
    bar.append(grip, up, down, eye);
    card.prepend(bar);
  }
  const addTools = (sec) => cards(sec).forEach(tools);

  // trascinamento con mouse, dito o penna (eventi pointer: funziona anche sul telefono)
  function startDrag(ev, card) {
    if (ev.button !== undefined && ev.button !== 0) return;
    ev.preventDefault();
    const container = card.parentElement;
    const sec = container.dataset.layout;
    card.classList.add("dragging");
    const id = ev.pointerId;
    try { ev.currentTarget.setPointerCapture(id); } catch (e) { /* non tutti i browser: si ascolta comunque il documento */ }
    const onMove = (e) => {
      if (e.pointerId !== id) return;
      const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-card]");
      if (!over || over === card || over.parentElement !== container) return;
      const r = over.getBoundingClientRect();
      const wide = r.width > container.getBoundingClientRect().width * 0.8;     // card a tutta larghezza: conta l'altezza
      const after = wide ? e.clientY > r.top + r.height / 2 : e.clientX > r.left + r.width / 2;
      if (after) over.after(card); else over.before(card);
    };
    const onUp = (e) => {
      if (e.pointerId !== id) return;
      card.classList.remove("dragging");
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onUp);
      remember(sec);
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  }

  // ------------------------------------------------------------- fascia della modalità modifica
  function banner() {
    const b = el("div", { class: "edit-banner", role: "status", id: "edit-banner" });
    const txt = el("div", { class: "txt" });
    txt.append(el("strong", {}, t("Stai riorganizzando questa pagina")),
               el("span", {}, t("Trascina le card per spostarle dentro la loro sezione, oppure usa le frecce · l'occhio le nasconde · l'ordine si salva per il tuo utente")));
    const reset = el("button", { type: "button", class: "btn small" }, t("Ripristina ordine"));
    reset.addEventListener("click", resetView);
    const show = el("button", { type: "button", class: "btn small", id: "edit-show" });
    show.addEventListener("click", showHidden);
    const done = el("button", { type: "button", class: "btn small primary" }, t("Fine"));
    done.addEventListener("click", stop);
    b.append(svg("i-settings"), txt, reset, show, done);
    return b;
  }
  function updateBanner() {
    const n = editing ? VIEWS[editing].reduce((a, sec) => a + (layout[sec] ? layout[sec].hidden.length : 0), 0) : 0;
    const show = $("#edit-show");
    if (!show) return;
    show.textContent = t("Mostra card nascoste ({p0})", { p0: n });
    show.disabled = n === 0;
  }

  function start() {
    const view = document.body.dataset.currentView;
    if (!VIEWS[view] || editing) return;
    editing = view;
    document.body.classList.add("editing");
    const v = $(`.view[data-view="${view}"]`);
    const anchor = view === "server" ? $("#srv-detail") : v;
    anchor.prepend(banner());
    VIEWS[view].forEach(addTools);
    updateBanner();
    $("#edit-open").hidden = true;
    $("#edit-banner button:last-child").focus();
  }
  function stop() {
    if (!editing) return;
    VIEWS[editing].forEach((sec) => cards(sec).forEach((c) => c.querySelector(":scope > .card-tools")?.remove()));
    $("#edit-banner")?.remove();
    document.body.classList.remove("editing");
    editing = null;
    clearTimeout(saveTimer); save();
    refreshButton();
    toast(t("Disposizione salvata"));
  }
  function resetView() {
    VIEWS[editing].forEach((sec) => {
      delete layout[sec];
      const b = box(sec);
      const def = (b.$default || []).map((id) => cards(sec).find((c) => c.dataset.card === id)).filter(Boolean);
      def.forEach((c) => b.append(c));
      applyLayout(sec);
    });
    clearTimeout(saveTimer); save();
    updateBanner();
  }
  function showHidden() {
    VIEWS[editing].forEach((sec) => { if (layout[sec]) { layout[sec].hidden = []; applyLayout(sec); } });
    clearTimeout(saveTimer); save();
    updateBanner();
  }

  // il pulsante compare solo dove c'è qualcosa da riorganizzare (Panoramica, dettaglio di un server)
  function refreshButton() {
    const view = document.body.dataset.currentView;
    const ok = !!VIEWS[view] && !(view === "server" && $("#srv-detail").hidden);
    $("#edit-open").hidden = !ok || !!editing;
    if (editing && editing !== view) stop();
  }

  document.addEventListener("DOMContentLoaded", () => {
    Object.values(VIEWS).flat().forEach((sec) => { const b = box(sec); if (b) b.$default = cards(sec).map((c) => c.dataset.card); });
    $("#edit-open").addEventListener("click", start);
    // in modifica un clic sulla scheda di un server non apre il server
    document.addEventListener("click", (ev) => {
      if (editing && ev.target.closest("[data-layout] > a[data-card]")) ev.preventDefault();
    }, true);
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && editing && !document.querySelector("dialog[open]")) stop(); });
    window.addEventListener("hashchange", () => setTimeout(refreshButton, 0));
    setTimeout(refreshButton, 0);
    const useLayout = (p) => { layout = (p && p.layout) || {}; applyAll(); };
    if (window.AM.prefs) useLayout(window.AM.prefs);
    document.addEventListener("prefs-loaded", (ev) => useLayout(ev.detail));
  });
  window.AM.applyLayout = applyLayout;
  window.AM.isEditing = () => !!editing && isView(editing);
})();
