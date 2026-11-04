/* Astreo Monitor 4.1 - ricerca (Ctrl K / Cmd K): sezioni, server, servizi, dispositivi, schede delle impostazioni,
   pagine e capitoli della guida, comandi rapidi. Mostra solo quello che l'utente può aprire. */
(() => {
  "use strict";
  const { t, $, $$, api, el, IS_VIEWER, LANG } = window.AM;
  const MAX = 14;
  let items = [], shown = [], active = 0, loaded = 0;

  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const visible = (n) => n && !n.closest(".admin-only") || !IS_VIEWER;

  function go(hash) { if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange")); else location.hash = hash; }

  async function collect() {
    const out = [];
    // sezioni del menu
    $$(".views [data-view-link]").forEach((a) => {
      if (!visible(a)) return;
      out.push({ kind: t("Sezione"), title: a.querySelector("span").textContent, run: () => go(`#${a.dataset.viewLink}`) });
    });
    // schede delle impostazioni
    if (!IS_VIEWER) {
      $$('.view[data-view="impostazioni"] [data-subtabs] button[data-sub]').forEach((b) => out.push({
        kind: t("Impostazioni"), title: `${t("Impostazioni")} → ${b.textContent.trim()}`, run: () => go(`#impostazioni/${b.dataset.sub}`) }));
    }
    // server e loro servizi
    try {
      const hosts = (await api("/api/v1/hosts")).hosts;
      const ov = window.AM.overview && window.AM.overview();
      hosts.forEach((h) => {
        out.push({ kind: t("Server"), title: h.name, sub: h.os_info || (h.kind === "local" ? t("server centrale") : h.kind),
                   run: () => go(`#server/${h.id}`) });
        const known = ((ov && ov.hosts.find((x) => x.id === h.id)) || {}).services || [];
        const seen = new Set();
        known.forEach((s) => {
          seen.add(s.unit.toLowerCase());
          out.push({ kind: t("Servizio"), title: s.label, sub: `${s.unit} · ${h.name}`, run: () => go(`#server/${h.id}`) });
        });
        (h.kind === "local" ? [] : (h.services || "").split(",")).map((u) => u.trim()).filter((u) => u && !seen.has(u.toLowerCase()))
          .forEach((u) => out.push({ kind: t("Servizio"), title: u, sub: h.name, run: () => go(`#server/${h.id}`) }));
      });
    } catch (e) { /* elenco server non disponibile */ }
    // dispositivi
    try {
      (await api("/api/v1/checks")).checks.filter((c) => c.enabled).forEach((c) => out.push({
        kind: t("Dispositivo"), title: c.name, sub: c.target, run: () => go("#dispositivi") }));
    } catch (e) { /* */ }
    // guida
    try {
      (await api(`/api/v1/help-search?lang=${LANG}`)).entries.forEach((e) => out.push({
        kind: t("Guida"), title: e.title, sub: e.title === e.page ? "" : e.page, run: () => window.AM.openHelp(e.ref) }));
    } catch (e) { /* */ }
    // comandi
    const theme = (p) => () => document.querySelector(`[data-theme-set="${p}"]`)?.click();
    out.push({ kind: t("Comando"), title: t("Tema chiaro"), run: theme("light") },
             { kind: t("Comando"), title: t("Tema scuro"), run: theme("dark") },
             { kind: t("Comando"), title: t("Tema: segui il sistema"), run: theme("system") },
             { kind: t("Comando"), title: t("Apri la guida"), run: () => window.AM.openHelp("index") },
             { kind: t("Comando"), title: t("Personalizza questa pagina"), keys: "card ordine nascondi", run: () => setTimeout(() => $("#edit-open").click(), 50),
               when: () => !$("#edit-open").hidden });
    out.forEach((x) => { x.hay = norm(`${x.title} ${x.sub || ""} ${x.kind} ${x.keys || ""}`); x.t = norm(x.title); });
    return out;
  }

  function search(q) {
    const words = norm(q).split(/\s+/).filter(Boolean);
    const pool = items.filter((x) => !x.when || x.when());
    if (!words.length) return pool.filter((x) => x.kind === t("Sezione") || x.kind === t("Comando")).slice(0, MAX);
    return pool.filter((x) => words.every((w) => x.hay.includes(w)))
      .map((x) => ({ x, s: (x.t.startsWith(words[0]) ? 0 : x.t.includes(words[0]) ? 1 : 2) + (x.kind === t("Guida") ? 0.5 : 0) }))
      .sort((a, b) => a.s - b.s).slice(0, MAX).map((r) => r.x);
  }

  function render() {
    const ul = $("#search-results");
    if (!shown.length) { ul.replaceChildren(el("li", { class: "empty" }, t("Nessun risultato"))); return; }
    ul.replaceChildren(...shown.map((x, i) => {
      const li = el("li", { role: "option", id: `sr-${i}`, "aria-selected": String(i === active), class: i === active ? "active" : "" });
      const txt = el("span", { class: "txt" });
      txt.append(el("strong", {}, x.title));
      if (x.sub) txt.append(el("small", {}, x.sub));
      li.append(el("span", { class: "kind" }, x.kind), txt);
      li.addEventListener("click", () => choose(i));
      li.addEventListener("mousemove", () => { if (active !== i) { active = i; mark(); } });
      return li;
    }));
    $("#search-input").setAttribute("aria-activedescendant", `sr-${active}`);
  }
  function mark() {
    $$("#search-results li[role=option]").forEach((li, i) => { li.classList.toggle("active", i === active); li.setAttribute("aria-selected", String(i === active)); });
    $(`#sr-${active}`)?.scrollIntoView({ block: "nearest" });
    $("#search-input").setAttribute("aria-activedescendant", `sr-${active}`);
  }
  function choose(i) {
    const x = shown[i];
    if (!x) return;
    $("#search-dialog").close();
    x.run();
  }

  async function open() {
    const dlg = $("#search-dialog");
    if (dlg.open) return;
    $("#search-input").value = "";
    dlg.showModal();
    $("#search-input").focus();
    if (Date.now() - loaded > 60_000) { items = await collect(); loaded = Date.now(); }
    shown = search(""); active = 0; render();
  }

  document.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key.toLowerCase() === "k") { ev.preventDefault(); open(); }
  });
  document.addEventListener("DOMContentLoaded", () => {
    $("#search-open").addEventListener("click", open);
    if (/Mac|iPhone|iPad/.test(navigator.platform)) $$("#search-open kbd").forEach((k) => { k.textContent = "⌘ K"; });
    const input = $("#search-input");
    input.addEventListener("input", () => { shown = search(input.value); active = 0; render(); });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); active = Math.min(active + 1, shown.length - 1); mark(); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); active = Math.max(active - 1, 0); mark(); }
      else if (ev.key === "Enter") { ev.preventDefault(); choose(active); }
    });
    $("#search-dialog").addEventListener("click", (ev) => { if (ev.target.id === "search-dialog") ev.target.close(); });
  });
})();
