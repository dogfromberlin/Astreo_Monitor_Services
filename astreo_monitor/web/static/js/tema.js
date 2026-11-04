/* Astreo Monitor 4.1 - tema chiaro, scuro o come il sistema.
   La scelta vale per l'utente (salvata sul server, uguale su computer e telefono); il browser ne tiene
   una copia per applicarla prima di disegnare la pagina (script nel <head> di index.html). */
(() => {
  "use strict";
  const { $$, api, t, toast } = window.AM;
  const KEY = "astreo-theme";
  const root = document.documentElement;
  const media = window.matchMedia ? matchMedia("(prefers-color-scheme: light)") : null;
  let pref = root.dataset.themePref || "system";

  const resolved = (p) => (p === "system" ? (media && media.matches ? "light" : "dark") : p);

  function apply(p, animate) {
    pref = ["system", "light", "dark"].includes(p) ? p : "system";
    const theme = resolved(pref);
    const changed = root.dataset.theme !== theme;
    if (animate && changed) {
      root.classList.add("theme-anim");
      setTimeout(() => root.classList.remove("theme-anim"), 400);
    }
    root.dataset.theme = theme;
    root.dataset.themePref = pref;
    try { localStorage.setItem(KEY, pref); } catch (e) { /* navigazione privata: resta per questa pagina */ }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#F7F9FB" : "#0D1117";
    $$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === pref)));
    if (changed) {
      window.AM.applyChartTheme();
      window.AM.reloadView();                       // ridisegna i grafici della vista con i colori nuovi
      document.dispatchEvent(new CustomEvent("theme-changed", { detail: { theme, pref } }));
    }
  }

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-theme-set]");
    if (!b || b.dataset.themeSet === pref) return;
    apply(b.dataset.themeSet, true);
    try { await api("/api/v1/ui/prefs", { method: "PUT", json: { theme: pref } }); }
    catch (e) { toast(t("Tema non salvato: {p0}", { p0: e.message }), "error"); }
  });
  if (media) media.addEventListener("change", () => { if (pref === "system") apply("system", true); });

  apply(pref, false);
  // la scelta salvata per l'utente prevale su quella del browser (es. cambiata dal telefono)
  api("/api/v1/ui/prefs").then((p) => { if (p.theme && p.theme !== pref) apply(p.theme, true); }).catch(() => {});
})();
