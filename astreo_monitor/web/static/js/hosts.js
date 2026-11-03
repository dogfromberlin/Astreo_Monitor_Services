/* Astreo Monitor 4.0 - server collegati: panoramica nella vista Server, server scelto, Impostazioni → Server collegati. */
(() => {
  "use strict";
  const { t, $, api, el, row, toast, fmtNum, fmtGB, fmtDateTime, fmtUptime, level, every } = window.AM;
  const STATUS = { OK: ["ok", "raggiungibile"], DOWN: ["down", "non raggiungibile"], WAITING: ["wait", "in attesa del primo invio"],
                   DISABLED: ["wait", "disattivato"] };
  let hosts = [];
  window.AM.host = Number((location.hash.split("/")[1]) || 1) || 1;

  const cardClass = (h) => {
    if (h.status !== "OK") return STATUS[h.status][0];
    const down = ((h.services_state || {}).services || []).some((s) => !s.up);
    const s = h.snapshot || {};
    return down || (s.disk_used_pct || 0) >= 85 ? "warn" : "ok";
  };

  async function load() {
    try { hosts = (await api("/api/v1/hosts")).hosts; } catch (e) { return; }
    const show = hosts.length > 1;
    $("#hosts-panel").hidden = !show;
    if (!show) { select(1, false); return; }
    if (!hosts.some((h) => h.id === window.AM.host)) window.AM.host = 1;
    const down = hosts.filter((h) => h.status === "DOWN").length;
    $("#hosts-summary").textContent = down ? t("{p0} su {p1} non raggiungibili", { p0: down, p1: hosts.length })
      : t("{p0} server", { p0: hosts.length });
    $("#host-cards").replaceChildren(...hosts.map((h) => {
      const s = h.snapshot || {};
      const svc = (h.services_state || {}).services || [];
      const b = el("button", { type: "button", role: "tab", class: `host-card ${h.kind === "local" ? "ok" : cardClass(h)}`,
                               "aria-selected": String(h.id === window.AM.host) });
      const vals = el("div", { class: "vals" });
      if (h.kind === "local") vals.append(el("span", {}, t("server centrale")));
      else if (s.cpu_pct != null) vals.append(el("span", {}, `CPU ${fmtNum(s.cpu_pct, 0)}%`), el("span", {}, `RAM ${fmtNum(s.mem_used_pct, 0)}%`),
                                         el("span", {}, `${t("Disco")} ${fmtNum(s.disk_used_pct, 0)}%`));
      const stopped = svc.filter((x) => !x.up).length;
      b.append(el("span", { class: "name" }, h.name), vals,
               el("span", { class: "meta" }, h.kind === "local" ? "" : [t(STATUS[h.status][1]),
                 stopped === 1 ? t("1 servizio fermo") : stopped ? t("{p0} servizi fermi", { p0: stopped }) : "",
                 h.last_seen ? t("ultimo invio {p0}", { p0: fmtDateTime(h.last_seen) }) : ""].filter(Boolean).join(" · ")));
      b.addEventListener("click", () => select(h.id));
      return b;
    }));
    if (window.AM.host !== 1) renderRemote();
  }

  function select(id, notify = true) {
    const changed = window.AM.host !== id;
    window.AM.host = id;
    document.body.dataset.remote = id === 1 ? "0" : "1";
    if (location.hash.startsWith("#server")) history.replaceState(null, "", id === 1 ? "#server" : `#server/${id}`);
    [...document.querySelectorAll(".host-card")].forEach((c, i) => c.setAttribute("aria-selected", String(hosts[i] && hosts[i].id === id)));
    if (id !== 1) renderRemote();
    else { $("#remote-note").hidden = true; $("#g-disk h2").textContent = t("Disco /"); }
    if (changed && notify) document.dispatchEvent(new CustomEvent("host-changed"));
  }

  function renderRemote() {
    const h = hosts.find((x) => x.id === window.AM.host);
    if (!h) return;
    const s = h.snapshot || {};
    const note = $("#remote-note");
    note.hidden = false;
    note.textContent = h.status === "WAITING" ? t("{p0}: in attesa del primo invio dell'agente.", { p0: h.name })
      : t("{p0} ({p1}) · agente {p2} · ultimo invio {p3}", { p0: h.name, p1: h.os_info || h.kind, p2: h.agent_version || "–",
          p3: h.last_seen ? fmtDateTime(h.last_seen) : "–" }) + (h.status === "DOWN" ? " · " + t("non raggiungibile") : "");
    const g = window.AM.setGauge;
    if (s.cpu_pct != null) g("#g-cpu", s.cpu_pct, level(s.cpu_pct, 70, 90), s.load1 != null ? t("load {p0} / {p1} / {p2}", { p0: s.load1, p1: s.load5, p2: s.load15 }) : "");
    if (s.mem_used_pct != null) g("#g-mem", s.mem_used_pct, level(s.mem_used_pct, 80, 92), s.mem_total_mb ? t("{p0} di {p1}, swap {p2}%", {
      p0: fmtGB(s.mem_used_mb), p1: fmtGB(s.mem_total_mb), p2: fmtNum(s.swap_used_pct || 0) }) : "");
    if (s.disk_used_pct != null) g("#g-disk", s.disk_used_pct, level(s.disk_used_pct, 85, 95), "");
    if (s.temperature_max != null) g("#g-temp", s.temperature_max, level(s.temperature_max, 85, 95), "");
    else { g("#g-temp", 0, null, t("non disponibile")); $("#g-temp .value span").textContent = "–"; }
    $("#g-disk h2").textContent = h.kind === "windows" ? t("Disco di sistema") : t("Disco /");
    if (s.uptime_s != null) $("#g-cpu .sub").title = t("acceso da {p0}", { p0: fmtUptime(s.uptime_s) });
    $("#disks tbody").replaceChildren(...(s.disks || []).map((d) => row([      // 4.0.1: tutti i dischi dell'agente
      { text: d.label ? `${d.mountpoint} ${d.label}` : d.mountpoint, title: [d.device, d.fstype].filter(Boolean).join(" ") },
      { text: fmtGB(d.used_mb), cls: "num" }, { text: fmtGB(d.free_mb), cls: "num" },
      { text: fmtNum(d.used_pct), cls: `num ${level(d.used_pct, 85, 95)}` },
    ])));
    const svc = (h.services_state || {}).services || [];
    $("#services").replaceChildren(...(svc.length ? svc.map((x) => {
      const li = el("li", { class: x.up ? "up" : "down" });
      const b = el("button", { type: "button", title: `${x.label} — ${x.unit}: ${x.state}` });
      b.append(el("span", { class: `led ${x.up ? "up" : "down"}` }), el("span", { class: "svc-label" }, x.label));
      if (!x.up) b.append(el("span", { class: "state" }, x.state));
      li.append(b);
      return li;
    }) : [el("li", { class: "hint" }, t("Nessun servizio indicato per questo server (Impostazioni → Server collegati)."))]));
  }

  // ------------------------------------------------------------ Impostazioni → Server collegati
  function renderAdmin() {
    $("#hosts-admin tbody").replaceChildren(...hosts.filter((h) => h.kind !== "local").map((h) => {
      const input = el("input", { type: "text", value: h.services || "", "aria-label": t("Servizi controllati") });
      const save = el("button", { type: "button", class: "ghost" }, t("Salva"));
      save.addEventListener("click", async () => {
        try { await api(`/api/v1/hosts/${h.id}`, { method: "PUT", json: { services: input.value } }); toast(t("Servizi salvati: l'agente li riceve al prossimo invio.")); load(); }
        catch (e) { toast(e.message, "error"); }
      });
      const token = el("button", { type: "button", class: "ghost" }, t("Nuovo token"));
      token.addEventListener("click", async () => {
        if (!confirm(t("Il token attuale di {p0} smetterà subito di funzionare. Continuare?", { p0: h.name }))) return;
        try { showInstall(h.name, h.kind, await api(`/api/v1/hosts/${h.id}/token`, { method: "POST", json: {} })); }
        catch (e) { toast(e.message, "error"); }
      });
      const del = el("button", { type: "button", class: "ghost danger" }, t("Elimina"));
      del.addEventListener("click", async () => {
        if (!confirm(t("Eliminare {p0} con tutti i suoi dati? L'agente sul server va disinstallato a parte.", { p0: h.name }))) return;
        try { await api(`/api/v1/hosts/${h.id}`, { method: "DELETE", json: {} }); toast(t("Server eliminato")); load().then(renderAdmin); }
        catch (e) { toast(e.message, "error"); }
      });
      const actions = el("div", { class: "row-actions" });
      actions.append(save, token, del);
      const svcBox = el("div");
      svcBox.append(input);
      return row([
        { text: h.name, label: t("Nome") }, { text: h.os_info || (h.kind === "windows" ? "Windows" : "Linux"), label: t("Sistema") },
        { text: t(STATUS[h.status][1]), cls: STATUS[h.status][0], label: t("Stato") },
        { text: h.last_seen ? fmtDateTime(h.last_seen) : "–", label: t("Ultimo invio") },
        { node: svcBox, label: t("Servizi controllati") }, { node: actions, label: "" },
      ]);
    }));
  }

  // Passi completi dell'installazione (gli stessi della guida, docs/<lingua>/agents.md)
  const STEPS = {
    windows: [
      "Sul server Windows apri https://github.com/dogfromberlin/Astreo_Monitor_Services/releases e scarica lo zip dell'ultima versione.",
      "Tasto destro sullo zip → Estrai tutto… nella cartella C:\\AstreoAgentSetup.",
      "Start → scrivi PowerShell → tasto destro su Windows PowerShell → Esegui come amministratore.",
      "Nella finestra: cd C:\\AstreoAgentSetup e poi Get-ChildItem -Recurse | Unblock-File (sblocca i file scaricati).",
      "Incolla il comando qui sotto e premi Invio: deve comparire «Collegamento al server centrale: OK».",
      "Entro un paio di minuti il server compare nella panoramica della vista Server.",
    ],
    linux: [
      "Sul server Linux, come utente con sudo: git clone https://github.com/dogfromberlin/Astreo_Monitor_Services.git",
      "cd Astreo_Monitor_Services",
      "Incolla il comando qui sotto e premi Invio: deve comparire «Collegamento al server centrale: OK».",
      "Entro un paio di minuti il server compare nella panoramica della vista Server.",
    ],
  };

  function showInstall(name, kind, r) {
    const k = kind === "windows" ? "windows" : "linux";
    $("#host-install").hidden = false;
    $("#host-install-title").textContent = t("Installazione dell'agente su {p0}", { p0: name });
    $("#host-install-steps").replaceChildren(...STEPS[k].map((s) => el("li", {}, t(s))));
    $("#host-install-guide").dataset.help = `agents#${k}`;
    $("#host-install-cmd").textContent = r.command;
    $("#host-install").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function create(ev) {
    ev.preventDefault();
    const f = ev.target.elements;
    try {
      const r = await api("/api/v1/hosts", { method: "POST", json: { name: f.name.value, kind: f.kind.value, services: f.services.value } });
      showInstall(f.name.value, f.kind.value, r);
      ev.target.reset();
      load().then(renderAdmin);
    } catch (e) { toast(e.message, "error"); }
  }

  async function saveOffline(ev) {
    ev.preventDefault();
    try {
      await api("/api/v1/settings", { method: "PUT", json: { "hosts.offline_minutes": Number($('#form-hosts [data-key="hosts.offline_minutes"]').value) } });
      toast(t("Impostazione salvata"));
    } catch (e) { toast(e.message, "error"); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.body.dataset.remote = window.AM.host === 1 ? "0" : "1";
    load();
    every(60_000, load, "server");
    window.AM.onView("server", load);
    if (window.AM.IS_VIEWER) return;
    $("#host-form").addEventListener("submit", create);
    $("#form-hosts").addEventListener("submit", saveOffline);
    document.addEventListener("subtab", async (ev) => {
      if (ev.detail.sub !== "server") return;
      await load(); renderAdmin();
      try { $('#form-hosts [data-key="hosts.offline_minutes"]').value = (await api("/api/v1/settings")).values["hosts.offline_minutes"]; } catch (e) { /* */ }
    });
  });
})();
