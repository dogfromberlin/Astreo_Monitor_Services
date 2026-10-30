/* Astreo Monitor - vista Terminale (ttyd dietro nginx, sblocco con password separata). */
(() => {
  "use strict";
  const { $, api, toast } = window.AM;
  let timer = null;

  function show(part) {
    ["#term-blocked", "#term-unlock", "#term-frame-wrap"].forEach((id) => { $(id).hidden = id !== part; });
    $("#term-lock").hidden = part !== "#term-frame-wrap";
  }
  function blocked(html) { $("#term-blocked").innerHTML = html; show("#term-blocked"); }

  async function refresh() {
    clearInterval(timer);
    let st;
    try { st = await api("/api/v1/terminal/status"); } catch (e) { blocked(`Stato del terminale non disponibile: ${e.message}`); return; }
    if (!st.enabled) {
      blocked("Il terminale non è abilitato. Si attiva nella sezione <code>[terminal]</code> di <code>/etc/astreo-monitor/config.ini</code> (vedi <code>docs/terminale.md</code>).");
      return;
    }
    if (!st.https) {
      const url = `https://${location.hostname}:5443/#terminale`;
      blocked(`Per sicurezza il terminale funziona solo con una connessione cifrata. Apri <a href="${url}">${url}</a>.`);
      return;
    }
    if (!st.ip_allowed) {
      blocked(`Il tuo indirizzo (${st.client_ip}) non è tra quelli ammessi per il terminale.`);
      return;
    }
    if (!st.unlocked_until) {
      $("#term-unlock-info").textContent = `La sessione dura ${st.session_minutes} minuti e si chiude anche dopo 15 minuti di inattività nella shell.`;
      $("#term-session").textContent = "";
      show("#term-unlock");
      $("#term-unlock input").focus();
      return;
    }
    const frame = $("#term-frame");
    if (!frame.src.endsWith("/terminal/")) frame.src = "/terminal/";
    show("#term-frame-wrap");
    const tick = () => {
      const left = st.unlocked_until * 1000 - Date.now();
      if (left <= 0) { lock(true); return; }
      const m = Math.floor(left / 60000), s = Math.floor((left % 60000) / 1000);
      $("#term-session").textContent = `Sessione: ancora ${m}:${String(s).padStart(2, "0")}`;
    };
    tick();
    timer = setInterval(tick, 1000);
  }

  async function lock(expired = false) {
    clearInterval(timer);
    $("#term-frame").src = "about:blank";
    try { await api("/api/v1/terminal/lock", { method: "POST", json: {} }); } catch (e) { /* già bloccato */ }
    toast(expired ? "Sessione del terminale scaduta" : "Terminale bloccato");
    refresh();
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#term-unlock").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const input = $("#term-unlock input");
      try {
        await api("/api/v1/terminal/unlock", { method: "POST", json: { password: input.value } });
        input.value = "";
        refresh();
      } catch (e) { toast(e.message, "error"); input.select(); }
    });
    $("#term-lock").addEventListener("click", () => lock(false));
    window.AM.onView("terminale", refresh);
    // lasciando la vista il terminale si chiude: la shell non resta aperta in background
    window.addEventListener("hashchange", () => {
      if (location.hash !== "#terminale" && !$("#term-frame-wrap").hidden) { $("#term-frame").src = "about:blank"; clearInterval(timer); }
    });
  });
})();
