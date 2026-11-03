/* Astreo Monitor - aiuto in linea: pagine della guida (docs/<lingua>) in un pannello laterale.
   Qualsiasi elemento con un attributo data-help (pagina e ancora facoltativa) apre la guida in quel punto. */
(() => {
  "use strict";
  const { t, $, api, toast, LANG } = window.AM;
  const history = [];
  let current = null;

  async function open(ref, push = true) {
    const [page, anchor] = ref.split("#");
    const dlg = $("#help-dialog");
    try {
      if (!current || current.page !== page) {
        const d = await api(`/api/v1/help/${encodeURIComponent(page)}?lang=${LANG}`);
        $("#help-title").textContent = d.title;
        $("#help-body").innerHTML = d.html;            // contenuto generato dal server dalla guida del progetto
        if (push && current) history.push(current.ref);
        current = { page, ref };
      } else if (push && current.ref !== ref) {
        history.push(current.ref);
        current.ref = ref;
      }
      $("#help-back").disabled = history.length === 0;
      if (!dlg.open) dlg.showModal();
      const body = $("#help-body");
      const target = anchor && body.querySelector(`[id="${CSS.escape(anchor)}"]`);
      if (target) {
        const block = target.closest("p")?.nextElementSibling || target;
        block.scrollIntoView({ block: "start" });
        block.classList.remove("flash"); void block.offsetWidth; block.classList.add("flash");
      } else {
        dlg.scrollTop = 0; body.scrollIntoView({ block: "start" });
      }
    } catch (e) { toast(e.message, "error"); }
  }

  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-help]");
    if (!el) return;
    ev.preventDefault();
    ev.stopPropagation();
    open(el.dataset.help);
  });
  document.addEventListener("DOMContentLoaded", () => {
    $("#help-back").addEventListener("click", () => { const ref = history.pop(); if (ref) { current = null; open(ref, false); } });
    $("#help-dialog").addEventListener("close", () => { history.length = 0; current = null; });
  });
  window.AM.openHelp = open;
})();
