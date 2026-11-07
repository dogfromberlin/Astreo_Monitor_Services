/* Astreo Monitor 4.0 - server collegati: panoramica nella vista Server, server scelto, Impostazioni → Server collegati. */
(() => {
  "use strict";
  const { t, $, $$, api, el, row, toast, fmtNum, fmtGB, fmtDateTime, fmtUptime, level, every } = window.AM;
  const STATUS = { OK: ["ok", "raggiungibile"], DOWN: ["down", "non raggiungibile"], WAITING: ["wait", "in attesa del primo invio"],
                   DISABLED: ["wait", "disattivato"] };
  let hosts = [];
  window.AM.host = Number((location.hash.split("/")[1]) || 1) || 1;
  // 4.1: dalla Panoramica si apre un server con #server/<id>
  window.addEventListener("hashchange", () => {
    if (!location.hash.startsWith("#server")) return;
    const id = detailId();
    if (id && id !== window.AM.host) select(id); else layout();
  });


  // 4.1: #server = elenco dei server (se più di uno), #server/<id> = dettaglio del server
  const detailId = () => { const m = location.hash.match(/^#server\/(\d+)/); return m ? Number(m[1]) : 0; };
  const listMode = () => hosts.length > 1 && !detailId();

  function layout() {
    const list = listMode();
    $("#srv-list").hidden = !list;
    $("#srv-detail").hidden = list;
    $("#srv-crumbs").hidden = hosts.length <= 1;
    const down = hosts.filter((h) => h.status === "DOWN").length;
    $("#srv-list-sum").textContent = down ? t("{p0} su {p1} non raggiungibili", { p0: down, p1: hosts.length })
      : t("{p0} server", { p0: hosts.length });
    if (list && window.AM.renderServerList) window.AM.renderServerList();
    const h = hosts.find((x) => x.id === window.AM.host);
    if (!h) return;
    $("#srv-name").textContent = h.name;
    $("#crumb-name").textContent = h.name;
    $("#srv-ic").className = `ic${h.kind === "local" ? "" : " remote"}`;
    const stopped = ((h.services_state || {}).services || []).filter((x) => (x.status || (x.up ? "up" : "down")) === "down").length;
    let [cls, label] = h.kind === "local" ? ["", t("regolare")] : [STATUS[h.status][0], t(STATUS[h.status][1])];
    if (cls === "ok") cls = "";
    if (h.status === "OK" && stopped) { cls = "warn"; label = stopped === 1 ? t("1 servizio fermo") : t("{p0} servizi fermi", { p0: stopped }); }
    // 4.3: agente Windows più vecchio del centrale e aggiornamento permesso: pulsante "Aggiorna agente"
    const central = document.body.dataset.version;
    const upd = $("#srv-agent-update");
    const can = !window.AM.IS_VIEWER && h.kind === "windows" && h.allow_update && h.agent_version && h.agent_version !== central;
    upd.hidden = !can;
    if (can && !upd.dataset.busy) upd.textContent = t("Aggiorna agente a {p0}", { p0: central });
    const pill = $("#srv-pill");
    pill.className = `pill ${cls}`;
    pill.replaceChildren(el("span", { class: `dot ${cls || "ok"}`, "aria-hidden": "true" }), el("span", {}, label));
  }

  async function load() {
    try { hosts = (await api("/api/v1/hosts")).hosts; } catch (e) { return; }
    if (!hosts.some((h) => h.id === window.AM.host)) window.AM.host = 1;
    const want = detailId();
    if (want && want !== window.AM.host && hosts.some((h) => h.id === want)) { select(want); return; }
    layout();
    if (window.AM.host !== 1) renderRemote();
  }

  function select(id, notify = true) {
    const changed = window.AM.host !== id;
    window.AM.host = id;
    document.body.dataset.remote = id === 1 ? "0" : "1";
    if (location.hash.startsWith("#server") && hosts.length > 1 && detailId() !== id) history.replaceState(null, "", `#server/${id}`);
    layout();
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
    if (!(s.disks || []).length) {                    // agente precedente alla 4.0.1: solo il disco di sistema
      const td = el("td", { colspan: "4", class: "hint" },
        t("L'agente {p0} invia solo il disco di sistema: aggiornalo per vedere tutti i dischi (guida, Server collegati).", { p0: h.agent_version || "" }));
      const tr = el("tr"); tr.append(td);
      $("#disks tbody").replaceChildren(tr);
    } else
    $("#disks tbody").replaceChildren(...(s.disks || []).map((d) => row([      // 4.0.1: tutti i dischi dell'agente
      { text: d.label ? `${d.mountpoint} ${d.label}` : d.mountpoint, title: [d.device, d.fstype].filter(Boolean).join(" ") },
      { text: fmtGB(d.used_mb), cls: "num" }, { text: fmtGB(d.free_mb), cls: "num" },
      { text: fmtNum(d.used_pct), cls: `num ${level(d.used_pct, 85, 95)}` },
    ])));
    renderAgentHealth(h);
    const svc = (h.services_state || {}).services || [];
    // 4.3: up, down, rest (discontinuo fermo), pending (in attesa del primo controllo), unseen, missing
    const LABEL = { rest: t("a riposo"), pending: t("in attesa del primo controllo"), unseen: t("non rilevato"),
                    missing: t("inesistente su questo server") };
    void LABEL;
    $("#services").replaceChildren(...(svc.length ? svc.map((x) => serviceRow(x, {
      actions: h.allow_commands && !window.AM.IS_VIEWER ? commandMenu(h, x) : null })) :
      [el("li", { class: "hint" }, t("Nessun servizio indicato per questo server (Impostazioni → Server collegati)."))]));
  }

  // ------------------------------------------------------------ 4.3: avvia / ferma / riavvia
  const pendingCmd = {};               // "hid:unit" -> id del comando in attesa
  const ACT = { start: [t("Avvia"), "i-play"], stop: [t("Ferma"), "i-stop"], restart: [t("Riavvia"), "i-restart"] };
  const icon = (name) => {
    const ns = "http://www.w3.org/2000/svg";
    const s = document.createElementNS(ns, "svg"); s.setAttribute("class", "icon"); s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS(ns, "use"); u.setAttribute("href", `#${name}`); s.append(u);
    return s;
  };

  // 4.3: riga di un servizio (anche per il centrale): pallino, nome intero, stato, azioni a destra
  function serviceRow(x, { actions = null, onOpen = null } = {}) {
    const st = x.status || (x.up ? "up" : x.ondemand ? "rest" : "down");
    const STATE = { up: t("attivo"), down: t("fermo"), rest: t("a riposo"), pending: t("in attesa del primo controllo"),
                    unseen: t("non rilevato"), missing: t("inesistente") };
    const why = { unseen: t("l'agente non ne ha ancora dato lo stato: premi Aggiorna o controlla che il server sia acceso"),
                  missing: t("su questo server non esiste un servizio con questo nome: controlla in Impostazioni → Server collegati") }[st];
    const li = el("li", { class: `svc-row ${st}` });
    const name = el(onOpen ? "button" : "span", { class: "svc-name", title: `${x.label} — ${x.unit}${why ? ": " + why : ""}`, ...(onOpen ? { type: "button" } : {}) });
    name.append(el("span", { class: `led ${st}`, "aria-hidden": "true" }), el("span", { class: "svc-label" }, x.label));
    if (onOpen) name.addEventListener("click", onOpen);
    const state = el("span", { class: "svc-state" }, STATE[st] + (x.protected ? ` · ${t("protetto")}` : "")
                                                     + (st === "down" && x.state && x.state !== "stopped" && x.state !== "inactive" ? ` (${x.state})` : ""));
    const act = el("span", { class: "svc-act" });
    if (x.protected) {
      const lk = icon("i-lock"); lk.setAttribute("class", "icon lock");
      const wrap = el("span", { title: t("Windows non permette di fermarlo o riavviarlo dalla gestione dei servizi") });
      wrap.append(lk); act.append(wrap);
    } else if (actions) act.append(actions);
    li.append(name, act, state);                 // azioni prima dello stato, che resta in fondo a destra
    return li;
  }
  window.AM.serviceRow = serviceRow;

  // menu "…" con le azioni (avvia / riavvia / ferma); un solo menu aperto alla volta
  function closeMenus() { $$(".svc-menu").forEach((m) => m.remove()); $$(".svc-more[aria-expanded=true]").forEach((b) => b.setAttribute("aria-expanded", "false")); }
  document.addEventListener("click", (ev) => { if (!ev.target.closest(".svc-menu, .svc-more")) closeMenus(); });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeMenus(); });

  function commandMenu(h, x) {
    const st = x.status || (x.up ? "up" : "down");
    if (!["up", "down", "rest"].includes(st)) return null;
    const key = `${h.id}:${x.unit}`;
    if (pendingCmd[key]) return el("span", { class: "svc-wait" }, t("comando in corso…"));
    const btn = el("button", { type: "button", class: "svc-more", "aria-haspopup": "menu", "aria-expanded": "false",
                               "aria-label": t("Azioni per {p0}", { p0: x.label }), title: t("Azioni") });
    btn.append(icon("i-dots"));
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const open = btn.getAttribute("aria-expanded") === "true";
      closeMenus();
      if (open) return;
      const menu = el("div", { class: "svc-menu", role: "menu" });
      for (const a of x.up ? ["restart", "stop"] : ["start"]) {
        const it = el("button", { type: "button", role: "menuitem", class: a === "stop" ? "danger" : "" });
        const ic = icon(ACT[a][1]);
        if (a !== "restart") ic.classList.add("solid");
        it.append(ic, el("span", {}, ACT[a][0]));
        it.addEventListener("click", () => { closeMenus(); sendCommand(h, x, a); });
        menu.append(it);
      }
      btn.after(menu);
      btn.setAttribute("aria-expanded", "true");
      menu.querySelector("button").focus();
    });
    return btn;
  }

  function commandButtons(h, x) {
    const box = el("span", { class: "svc-cmds" });
    const key = `${h.id}:${x.unit}`;
    if (pendingCmd[key]) { box.append(el("span", { class: "svc-wait" }, t("comando in corso…"))); return box; }
    if (x.protected) {                  // 4.3: Windows non lascia fermare o riavviare Firewall e Defender
      box.append(el("span", { class: "svc-wait", title: t("Windows non permette di fermarlo o riavviarlo dalla gestione dei servizi") }, t("protetto da Windows")));
      return box;
    }
    for (const a of x.up ? ["restart", "stop"] : ["start"]) {
      const b = el("button", { type: "button", class: `svc-cmd ${a}`, title: `${ACT[a][0]} ${x.label}`, "aria-label": `${ACT[a][0]} ${x.label}` });
      b.append(icon(ACT[a][1]));
      b.addEventListener("click", () => sendCommand(h, x, a));
      box.append(b);
    }
    return box;
  }

  async function sendCommand(h, x, action) {
    const msg = action === "stop"
      ? t("Fermare {p0} su {p1}? Il servizio resterà fermo finché non lo riavvii; partirà un avviso di servizio fermo.", { p0: x.label, p1: h.name })
      : t("{p0} {p1} su {p2}? Il comando parte entro un minuto.", { p0: ACT[action][0], p1: x.label, p2: h.name });
    if (!confirm(msg)) return;
    try {
      const r = await api(`/api/v1/hosts/${h.id}/services/${encodeURIComponent(x.unit)}/${action}`, { method: "POST", json: {} });
      pendingCmd[`${h.id}:${x.unit}`] = r.id;
      toast(t("Comando inviato: l'agente lo esegue entro un minuto"));
      renderRemote();
      waitResult(h, x, r.id, Date.now());
    } catch (e) { toast(e.message, "error"); }
  }

  async function waitResult(h, x, id, started) {
    const key = `${h.id}:${x.unit}`;
    try {
      const st = await api(`/api/v1/hosts/${h.id}/commands`);
      const res = st.results.find((r) => r.id === id);
      if (res || !st.pending.some((p) => p.id === id)) {
        delete pendingCmd[key];
        if (res && res.ok) toast(t("{p0}: comando eseguito ({p1})", { p0: x.label, p1: res.detail }));
        else toast(t("{p0}: comando non riuscito: {p1}", { p0: x.label, p1: res ? res.detail : t("nessuna risposta") }), "error");
        await load();
        document.dispatchEvent(new CustomEvent("hosts-changed"));
        return;
      }
    } catch (e) { /* riprova */ }
    if (Date.now() - started < 12 * 60_000) setTimeout(() => waitResult(h, x, id, started), 5000);
    else { delete pendingCmd[key]; renderRemote(); }
  }
  // 4.3: "Aggiorna" su un server collegato: l'agente ricontrolla i servizi al prossimo contatto (entro un minuto)
  window.AM.refreshRemoteServices = async () => {
    const id = window.AM.host;
    const btn = $("#services-refresh");
    try {
      await api(`/api/v1/hosts/${id}/refresh`, { method: "POST", json: {} });
      btn.disabled = true; btn.textContent = t("richiesta inviata…");
      const until = Date.now() + 90_000;
      const tick = async () => { await load(); if (Date.now() < until && window.AM.host === id) setTimeout(tick, 10_000);
                                 else { btn.disabled = false; btn.textContent = t("Aggiorna"); } };
      setTimeout(tick, 10_000);
    } catch (e) { toast(e.message, "error"); }
  };
  async function updateAgent() {
    const h = hosts.find((x) => x.id === window.AM.host);
    if (!h || !confirm(t("Aggiornare l'agente di {p0} dalla {p1} alla {p2}? Parte entro un minuto; l'agente tiene una copia dei file precedenti.",
                         { p0: h.name, p1: h.agent_version, p2: document.body.dataset.version }))) return;
    const btn = $("#srv-agent-update");
    try {
      const r = await api(`/api/v1/hosts/${h.id}/agent-update`, { method: "POST", json: {} });
      btn.dataset.busy = "1"; btn.disabled = true; btn.textContent = t("aggiornamento in corso…");
      const started = Date.now();
      const tick = async () => {
        const st = await api(`/api/v1/hosts/${h.id}/commands`).catch(() => null);
        const res = st && st.results.find((x) => x.id === r.id);
        if (res || (st && !st.pending.some((p) => p.id === r.id)) || Date.now() - started > 12 * 60_000) {
          delete btn.dataset.busy; btn.disabled = false;
          if (res && res.ok) toast(t("{p0}: {p1}", { p0: h.name, p1: res.detail }));
          else toast(t("Aggiornamento non riuscito: {p0}", { p0: res ? res.detail : t("nessuna risposta") }), "error");
          await load();
          return;
        }
        setTimeout(tick, 5000);
      };
      setTimeout(tick, 5000);
    } catch (e) { toast(e.message, "error"); }
  }
  window.AM.sendServiceCommand = (hid, unit, label, action) => {
    const h = hosts.find((y) => y.id === hid);
    if (h) sendCommand(h, { unit, label }, action);
  };

  // 4.2: dischi, aggiornamenti e Docker inviati dall'agente
  function renderAgentHealth(h) {
    const hl = h.health;
    const cont = (h.containers || {}).containers || [];
    const step = (cls, title, sub) => {
      const li = el("li", { class: cls });
      const d = el("div"); d.append(el("strong", {}, title)); if (sub) d.append(el("span", {}, sub));
      li.append(el("span", { class: `dot ${cls === "ok" ? "ok" : cls}`, "aria-hidden": "true" }), d);
      return li;
    };
    $("#ah-none").hidden = !!hl;
    if (!hl) $("#ah-none").textContent = t("L'agente {p0} non invia dischi e aggiornamenti: aggiornalo alla 4.2 (guida, Server collegati).", { p0: h.agent_version || "" });
    $("#ah-time").textContent = hl ? t("aggiornato {p0} · ogni 6 ore", { p0: fmtDateTime(hl.time) }) : "";
    const items = [];
    if (hl) {
      if (!hl.disks.length) items.push(step("wait", t("Dischi"), hl.smart_available ? t("nessun disco letto") : t("SMART non disponibile (installa smartmontools)")));
      hl.disks.forEach((d) => {
        const bad = d.passed === false || d.os_health === "Unhealthy" || d.pending || d.uncorrectable || d.media_errors;
        const warn = d.os_health === "Warning" || d.reallocated;
        const extra = [d.temperature != null ? `${d.temperature} °C` : "", d.wear_used_pct != null ? t("usura {p0}%", { p0: d.wear_used_pct }) : "",
                       d.error || ""].filter(Boolean).join(" · ");
        items.push(step(bad ? "alert" : warn ? "warn" : "ok", `${t("Disco")} ${d.device} ${d.model || ""}`.trim(),
                        (bad ? t("guasto o settori danneggiati") : warn ? t("da tenere d'occhio") : t("regolare")) + (extra ? ` · ${extra}` : "")));
      });
      const u = hl.updates;
      if (u) {
        if (u.error) items.push(step("wait", t("Aggiornamenti"), u.error));
        else items.push(step(u.security_count ? "warn" : "ok", t("Aggiornamenti"),
          u.total ? t("{p0} disponibili, {p1} di sicurezza", { p0: u.total, p1: u.security_count || 0 }) : t("tutto aggiornato")));
        if (u.reboot && u.reboot.required) items.push(step("warn", t("Riavvio richiesto"), t("per completare gli aggiornamenti")));
      }
    }
    $("#ah-list").replaceChildren(...items);
    if (h.containers && h.containers.running === false) {        // 4.3: Docker installato ma fermo
      items.push(step("wait", t("Docker"), t("installato ma non in esecuzione")));
      $("#ah-list").replaceChildren(...items);
    }
    $("#ah-docker").hidden = $("#ah-docker-h").hidden = !cont.length;
    $("#ah-docker tbody").replaceChildren(...cont.map((c) => row([
      { text: c.name }, { text: c.image }, { text: c.status || c.state, cls: c.state === "running" ? "" : "alert" }])));
  }

  // ------------------------------------------------------------ Impostazioni → Server collegati
  // 4.3: elenco dei servizi di un server collegato, con "discontinuo" scelto già quando si aggiunge
  function serviceEditor(services, ondemand) {
    const od = new Set((ondemand || "").split(",").map((u) => u.trim().toLowerCase()).filter(Boolean));
    let items = (services || "").split(",").map((u) => u.trim()).filter(Boolean).map((u) => ({ unit: u, od: od.has(u.toLowerCase()) }));
    const box = el("div", { class: "svc-editor" });
    const list = el("ul", { class: "svc-edit-list" });
    const add = el("div", { class: "svc-edit-add" });
    const name = el("input", { type: "text", maxlength: "200", placeholder: t("nome del servizio, es. Spooler o ssh.service"),
                               "aria-label": t("Nome del servizio da aggiungere") });
    const odNew = el("input", { type: "checkbox", "aria-label": t("Discontinuo") });
    const odLab = el("label", { class: "check-row" }); odLab.append(odNew, el("span", {}, t("discontinuo")));
    const addB = el("button", { type: "button", class: "ghost" }, t("+ Aggiungi"));
    function draw() {
      list.replaceChildren(...(items.length ? items.map((it, i) => {
        const li = el("li");
        const cb = el("input", { type: "checkbox", "aria-label": t("{p0} discontinuo", { p0: it.unit }) });
        cb.checked = it.od;
        cb.addEventListener("change", () => { it.od = cb.checked; });
        const lab = el("label", { class: "check-row", title: t("Parte solo quando serve: fermo non è un guasto, nessun avviso") });
        lab.append(cb, el("span", {}, t("discontinuo")));
        const rm = el("button", { type: "button", class: "ghost danger", "aria-label": t("Togli {p0}", { p0: it.unit }) }, "✕");
        rm.addEventListener("click", () => { items.splice(i, 1); draw(); });
        li.append(el("code", {}, it.unit), lab, rm);
        return li;
      }) : [el("li", { class: "hint" }, t("Nessun servizio controllato."))]));
    }
    function doAdd() {
      const u = name.value.trim();
      if (!u) return;
      if (/[,\s]/.test(u)) { toast(t("Un servizio per volta, senza spazi né virgole"), "error"); return; }
      if (!items.some((x) => x.unit.toLowerCase() === u.toLowerCase())) items.push({ unit: u, od: odNew.checked });
      name.value = ""; odNew.checked = false; draw(); name.focus();
    }
    addB.addEventListener("click", doAdd);
    name.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); doAdd(); } });
    add.append(name, odLab, addB);
    box.append(list, add);
    draw();
    return { node: box, list, add,
             value: () => ({ services: items.map((x) => x.unit).join(","), services_ondemand: items.filter((x) => x.od).map((x) => x.unit) }),
             reset: () => { items = []; draw(); } };
  }

  function renderAdmin() {
    const remotes = hosts.filter((h) => h.kind !== "local");
    $("#hosts-admin").replaceChildren(...(remotes.length ? remotes.map((h) => {
      const editor = serviceEditor(h.services, h.services_ondemand);
      const save = el("button", { type: "button", class: "btn small primary" }, t("Salva servizi"));
      save.addEventListener("click", async () => {
        try { await api(`/api/v1/hosts/${h.id}`, { method: "PUT", json: editor.value() }); toast(t("Servizi salvati: l'agente li controlla entro un minuto.")); load(); }
        catch (e) { toast(e.message, "error"); }
      });
      const token = el("button", { type: "button", class: "btn small" }, t("Nuovo token"));
      token.addEventListener("click", async () => {
        if (!confirm(t("Il token attuale di {p0} smetterà subito di funzionare. Continuare?", { p0: h.name }))) return;
        try { showInstall(h.name, h.kind, await api(`/api/v1/hosts/${h.id}/token`, { method: "POST", json: {} })); }
        catch (e) { toast(e.message, "error"); }
      });
      const del = el("button", { type: "button", class: "btn small danger" }, t("Elimina"));
      del.addEventListener("click", async () => {
        if (!confirm(t("Eliminare {p0} con tutti i suoi dati? L'agente sul server va disinstallato a parte.", { p0: h.name }))) return;
        try { await api(`/api/v1/hosts/${h.id}`, { method: "DELETE", json: {} }); toast(t("Server eliminato")); load().then(renderAdmin); }
        catch (e) { toast(e.message, "error"); }
      });
      const conf = el("button", { type: "button", class: "btn small" }, t("Soglie e avvisi"));
      conf.addEventListener("click", () => openSettings(h));
      const [cls, label] = STATUS[h.status] || ["", h.status];
      const card = el("article", { class: "host-admin" });
      const head = el("div", { class: "head" });
      const who = el("div", { class: "who" });
      who.append(el("strong", {}, h.name),
                 el("span", {}, [h.os_info || (h.kind === "windows" ? "Windows" : "Linux"),
                                 h.agent_version ? t("agente {p0}", { p0: h.agent_version }) : "",
                                 h.last_seen ? t("ultimo invio {p0}", { p0: fmtDateTime(h.last_seen) }) : t("nessun dato ancora")].filter(Boolean).join(" · ")));
      const pill = el("span", { class: `pill ${{ ok: "", down: "alert" }[cls] ?? "wait"}` }, t(label));
      const acts = el("div", { class: "acts" });
      acts.append(conf, token, del);
      head.append(who, pill, acts);
      const body = el("div", { class: "body" });
      body.append(el("span", { class: "field-label" }, t("Servizi controllati")), editor.node);
      const foot = el("div", { class: "foot" });
      foot.append(save);
      card.append(head, body, foot);
      return card;
    }) : [el("p", { class: "hint" }, t("Nessun server collegato: aggiungine uno qui sotto."))]));
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

  // ------------------------------------------------------------ 4.2: impostazioni del server
  let defaults = null, editing = null;
  async function openSettings(h) {
    try { const d = await api("/api/v1/hosts"); defaults = { ...d.defaults, offline_minutes: d.offline_minutes }; hosts = d.hosts; }
    catch (e) { toast(e.message, "error"); return; }
    editing = hosts.find((x) => x.id === h.id) || h;
    const f = $("#hs-form");
    $("#hs-title").textContent = t("Impostazioni di {p0}", { p0: editing.name });
    const remote = editing.kind !== "local";
    $$("#hs-form .remote-only-field").forEach((x) => { x.hidden = !remote; });
    f.notify_offline.checked = editing.notify_offline !== false;
    f.allow_commands.checked = !!editing.allow_commands;

    f.allow_update.checked = !!editing.allow_update;
    for (const k of ["offline_minutes", "disk_warning", "disk_alert", "temp_warning", "temp_alert", "cpu_warning", "cpu_alert", "mem_warning", "mem_alert"]) {
      f[k].value = editing[k] ?? "";
      f[k].placeholder = defaults[k] != null ? String(defaults[k]) : "";
    }
    $("#hs-error").hidden = true;
    $("#host-settings").showModal();
  }
  async function saveSettings(ev) {
    ev.preventDefault();
    const f = $("#hs-form");
    const data = {};
    for (const k of ["disk_warning", "disk_alert", "temp_warning", "temp_alert", "cpu_warning", "cpu_alert", "mem_warning", "mem_alert"]) {
      data[k] = f[k].value === "" ? null : Number(f[k].value);
    }
    if (editing.kind !== "local") {
      data.notify_offline = f.notify_offline.checked;
      data.allow_commands = f.allow_commands.checked;

      data.allow_update = f.allow_update.checked;
      data.offline_minutes = f.offline_minutes.value === "" ? null : Number(f.offline_minutes.value);
    }
    try {
      $("#hs-error").hidden = true;
      await api(`/api/v1/hosts/${editing.id}`, { method: "PUT", json: data });
      $("#host-settings").close();
      toast(t("Impostazioni di {p0} salvate", { p0: editing.name }));
      await load();
      if (!$('[data-subpanel="set:server"]').hidden) renderAdmin();
      document.dispatchEvent(new CustomEvent("hosts-changed"));
    } catch (e) {
      // 4.2: il motivo resta visibile nella finestra, non solo in un messaggio che sparisce
      $("#hs-error").textContent = t("Non salvato: {p0}", { p0: e.message });
      $("#hs-error").hidden = false;
    }
  }

  let newEditor = null;
  async function create(ev) {
    ev.preventDefault();
    const f = ev.target.elements;
    try {
      const r = await api("/api/v1/hosts", { method: "POST", json: { name: f.name.value, kind: f.kind.value, ...newEditor.value() } });
      showInstall(f.name.value, f.kind.value, r);
      ev.target.reset();
      newEditor.reset();
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
    newEditor = serviceEditor("", "");
    $("#host-new-list").append(newEditor.list);        // elenco e riga di aggiunta in due celle della griglia,
    $("#host-new-add").append(newEditor.add);          // allineate a Nome e a Sistema
    $("#hs-form").addEventListener("submit", saveSettings);
    $("#hs-cancel").addEventListener("click", () => $("#host-settings").close());
    $("#srv-agent-update").addEventListener("click", updateAgent);
    $("#srv-settings").addEventListener("click", () => { const h = hosts.find((x) => x.id === window.AM.host); if (h) openSettings(h); });
    $("#host-form").addEventListener("submit", create);
    $("#form-hosts").addEventListener("submit", saveOffline);
    document.addEventListener("subtab", async (ev) => {
      if (ev.detail.sub !== "server") return;
      await load(); renderAdmin();
      try { $('#form-hosts [data-key="hosts.offline_minutes"]').value = (await api("/api/v1/settings")).values["hosts.offline_minutes"]; } catch (e) { /* */ }
    });
  });
})();
