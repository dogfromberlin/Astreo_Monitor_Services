/* Astreo Monitor - vista Terminale.
   La shell (ttyd in un iframe) resta aperta mentre navighi nelle altre sezioni:
   l'iframe viene solo nascosto, mai ricaricato. Si chiude con "Chiudi terminale",
   dopo N minuti senza attività, o chiudendo la scheda / il browser. */
(() => {
  "use strict";
  const { $, api, toast } = window.AM;
  const TOUCH_EVERY = 60_000;     // al massimo un rinnovo al minuto
  let st = null;                   // ultimo stato dal server
  let open = false;                // shell caricata nell'iframe
  let lastActivity = 0, lastTouch = 0, tick = null;

  function show(part) {
    ["#term-blocked", "#term-unlock", "#term-frame-wrap"].forEach((id) => { $(id).hidden = id !== part; });
    $("#term-lock").hidden = part !== "#term-frame-wrap";
  }
  function blocked(html) { $("#term-blocked").innerHTML = html; show("#term-blocked"); }
  function setBadge(on) { document.querySelector('[data-view-link="terminale"]').classList.toggle("session-open", on); }

  // ------------------------------------------------------------ attività
  function hookActivity() {
    // stessa origine: posso ascoltare la tastiera dentro l'iframe di ttyd
    try {
      const doc = $("#term-frame").contentDocument;
      if (doc && !doc.__astreoHooked) {
        ["keydown", "mousedown", "touchstart", "paste"].forEach((ev) =>
          doc.addEventListener(ev, () => { lastActivity = Date.now(); }, { passive: true, capture: true }));
        doc.__astreoHooked = true;
      }
    } catch (e) { /* iframe non ancora pronto */ }
  }

  async function touchIfActive() {
    if (!open || lastActivity <= lastTouch || Date.now() - lastTouch < TOUCH_EVERY) return;
    lastTouch = Date.now();
    try { st = await api("/api/v1/terminal/touch", { method: "POST", json: {} }); }
    catch (e) { closeShell("Sessione del terminale scaduta"); }
  }

  function startTick() {
    clearInterval(tick);
    tick = setInterval(() => {
      if (!open || !st || !st.unlocked_until) return;
      hookActivity();
      touchIfActive();
      const left = st.unlocked_until * 1000 - Date.now();
      if (left <= 0) { closeShell("Sessione del terminale chiusa per inattività"); return; }
      const m = Math.floor(left / 60000), s = Math.floor((left % 60000) / 1000);
      $("#term-session").textContent = `Si chiude tra ${m}:${String(s).padStart(2, "0")} senza attività`;
    }, 1000);
  }

  // ------------------------------------------------------- apri / chiudi
  function openShell() {
    const frame = $("#term-frame");
    if (!open) {
      frame.src = "/terminal/";
      frame.addEventListener("load", hookActivity, { once: true });
      open = true;
      lastActivity = lastTouch = Date.now();
    }
    setBadge(true);
    show("#term-frame-wrap");
    startTick();
    // rientrando nella vista: xterm si adatta alla dimensione e riprende il focus
    setTimeout(() => {
      try { frame.contentWindow.dispatchEvent(new Event("resize")); frame.contentWindow.focus(); } catch (e) { /* */ }
    }, 50);
  }

  async function closeShell(message) {
    clearInterval(tick);
    open = false;
    setBadge(false);
    $("#term-frame").src = "about:blank";
    try { await api("/api/v1/terminal/lock", { method: "POST", json: {} }); } catch (e) { /* già chiusa */ }
    if (message) toast(message);
    refresh();
  }

  async function refresh() {
    try { st = await api("/api/v1/terminal/status"); } catch (e) { blocked(`Stato del terminale non disponibile: ${e.message}`); return; }
    if (!st.enabled) {
      blocked("Il terminale non è abilitato. Si attiva nella sezione <code>[terminal]</code> di <code>/etc/astreo-monitor/config.ini</code> (vedi <code>docs/terminale.md</code>).");
      return;
    }
    if (!st.https) {
      if (location.protocol === "https:") {
        blocked("La pagina è in HTTPS, ma la dashboard non lo rileva: in <code>/etc/astreo-monitor/config.ini</code>, sezione <code>[web]</code>, "
          + "devono esserci <code>trusted_proxy = 127.0.0.1</code> e <code>host = 127.0.0.1</code> (vedi <code>docs/terminale.md</code>, Diagnosi).");
      } else {
        const url = `https://${location.hostname}:5443/#terminale`;
        blocked(`Per sicurezza il terminale funziona solo con una connessione cifrata. Apri <a href="${url}">${url}</a>.`);
      }
      return;
    }
    if (!st.ip_allowed) { blocked(`Il tuo indirizzo (${st.client_ip}) non è tra quelli ammessi per il terminale.`); return; }
    if (!st.unlocked_until) {
      open = false;
      setBadge(false);
      $("#term-frame").src = "about:blank";
      $("#term-unlock-info").textContent = `La sessione resta aperta mentre usi le altre sezioni e si chiude dopo ${st.session_minutes} minuti senza attività, `
        + "con Chiudi terminale o chiudendo la scheda.";
      $("#term-session").textContent = "";
      show("#term-unlock");
      $("#term-unlock input").focus();
      return;
    }
    openShell();
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
    $("#term-lock").addEventListener("click", () => closeShell("Terminale chiuso"));
    // entrando nella vista: se la shell è già aperta la mostra com'era, altrimenti verifica lo stato
    window.AM.onView("terminale", () => { if (open) openShell(); else refresh(); });
    // chiusura della scheda o del browser: chiude subito la sessione lato server
    window.addEventListener("pagehide", () => { if (open) navigator.sendBeacon("/api/v1/terminal/lock"); });
  });
})();
