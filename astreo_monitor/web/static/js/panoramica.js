/* Astreo Monitor 4.1 - Panoramica: stato in una frase, "Da controllare", server, connessione, backup, eventi.
   Tutti i dati arrivano da /api/v1/overview, aggiornato ogni 30 secondi. */
(() => {
  "use strict";
  const { t, LOCALE, IS_VIEWER, $, api, el, toast, fmtNum, fmtDateTime, fmtUptime, every, setTitle, isView } = window.AM;
  const LOCAL = 1;
  let last = null;

  const svgIcon = (name) => {
    const ns = "http://www.w3.org/2000/svg";
    const s = document.createElementNS(ns, "svg");
    s.setAttribute("class", "icon"); s.setAttribute("aria-hidden", "true");
    const u = document.createElementNS(ns, "use");
    u.setAttribute("href", `#${name}`);
    s.appendChild(u);
    return s;
  };
  const hostHref = (id) => `#server/${id}`;
  const pct = (v) => (v === null || v === undefined ? "–" : `${fmtNum(v, 0)} %`);
  const meterLevel = (v, warn, alert) => (v >= alert ? "alert" : v >= warn ? "warn" : "");
  const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" }) : "–");

  function dayLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso), today = new Date();
    const yest = new Date(today); yest.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return t("di oggi");
    if (d.toDateString() === yest.toDateString()) return t("di ieri");
    return t("del {p0}", { p0: d.toLocaleDateString(LOCALE, { day: "2-digit", month: "2-digit" }) });
  }

  // ------------------------------------------------------------------ intestazione
  function greeting() {
    const h = new Date().getHours();
    const hello = h < 13 ? t("Buongiorno") : h < 18 ? t("Buon pomeriggio") : t("Buonasera");
    const user = document.body.dataset.user || "";
    const name = user ? user.charAt(0).toUpperCase() + user.slice(1) : "";
    const date = new Date().toLocaleDateString(LOCALE, { weekday: "long", day: "numeric", month: "long" });
    const sub = last ? `${date} · ${t("dati aggiornati alle {p0}", { p0: clock(last.time) })}` : date;
    if (isView("panoramica")) setTitle(name ? `${hello}, ${name}` : hello, sub);
  }

  function renderHero(d) {
    const hero = $("#ov-hero");
    hero.dataset.level = d.status.level;
    $("#ov-headline").textContent = d.status.headline;
    $("#ov-summary").textContent = d.status.summary;
    $("#ov-ring").setAttribute("stroke-dasharray", `${(d.status.ok_pct * 1.382).toFixed(1)} 139`);
    const n = d.todo.filter((x) => x.severity !== "info").length;
    $("#ov-goto").hidden = n === 0;
    const badge = $("#nav-todo");
    badge.hidden = n === 0;
    badge.textContent = String(n);
    badge.className = `badge${d.status.level === "alert" ? " alert" : ""}`;
    badge.setAttribute("aria-label", n === 1 ? t("1 cosa da controllare") : t("{p0} cose da controllare", { p0: n }));
  }

  // ------------------------------------------------------------------ numeri principali
  function kpi(id, value, unit, subText, subLevel) {
    const box = $(id);
    const v = box.querySelector(".value");
    v.replaceChildren(document.createTextNode(value));
    if (unit) v.append(el("small", {}, ` ${unit}`));
    const sub = box.querySelector(".sub");
    sub.className = `sub ${subLevel || ""}`;
    sub.replaceChildren(...(subLevel ? [el("span", { class: `dot ${subLevel}`, "aria-hidden": "true" })] : []), el("span", {}, subText));
  }

  function renderKpis(d) {
    const active = d.hosts.filter((h) => h.enabled);
    const up = active.filter((h) => h.status === "OK");
    const down = active.filter((h) => h.status === "DOWN" && h.notify_offline !== false);
    kpi("#kpi-servers", String(up.length), t("/ {p0} raggiungibili", { p0: active.length }),
        down.length ? t("non raggiungibile: {p0}", { p0: down.map((h) => h.name).join(", ") }) : up.map((h) => h.name).join(", "),
        down.length ? "alert" : "ok");

    const s = d.services;
    const byHost = {};
    s.down.forEach((x) => { byHost[x.host] = (byHost[x.host] || 0) + 1; });
    const downTxt = Object.entries(byHost).map(([h, n]) => (n === 1 ? t("1 fermo su {p0}", { p0: h }) : t("{p0} fermi su {p1}", { p0: n, p1: h }))).join(", ");
    kpi("#kpi-services", String(s.up), t("/ {p0} attivi", { p0: s.total }), s.down.length ? downTxt : t("tutti attivi"), s.down.length ? "warn" : "ok");

    const c = d.connection;
    const out = c.outages_7d;
    kpi("#kpi-conn", c.availability_7d === null ? "–" : fmtNum(c.availability_7d, 2), c.availability_7d === null ? "" : "%",
        out === 0 ? t("nessuna interruzione") : out === 1 ? t("1 interruzione di {p0} min", { p0: c.down_minutes_7d })
          : t("{p0} interruzioni, {p1} min in tutto", { p0: out, p1: c.down_minutes_7d }),
        out ? "warn" : c.availability_7d === null ? "" : "ok");

    const b = d.backup;
    if (!b.status) kpi("#kpi-backup", "–", "", t("nessun backup registrato"), "warn");
    else {
      const where = b.github ? t("copia su GitHub") : b.destinations ? t("{p0} destinazioni", { p0: b.destinations }) : t("solo copia locale");
      kpi("#kpi-backup", clock(b.time), dayLabel(b.time),
          b.status === "OK" ? `${b.databases === 1 ? t("1 database") : t("{p0} database", { p0: b.databases })} · ${where}` : t("non riuscito"),
          b.status === "OK" ? "ok" : "alert");
    }
  }

  // ------------------------------------------------------------------ da controllare
  const SEV = { alert: [t("Urgente"), "i-alert"], warn: [t("Da guardare"), "i-alert"], info: [t("Informazione"), "i-info"] };

  async function unmonitor(a) {
    if (!confirm(t("Non controllare più il servizio {p0}? Puoi riattivarlo dalle impostazioni.", { p0: a.label }))) return;
    try {
      if (a.host === LOCAL) {
        await api(`/api/v1/settings/services/${encodeURIComponent(a.unit)}`, { method: "PUT", json: { monitored: false } });
      } else {
        const h = (await api("/api/v1/hosts")).hosts.find((x) => x.id === a.host);
        const units = (h && h.services ? h.services.split(",") : []).map((u) => u.trim()).filter((u) => u && u !== a.unit);
        await api(`/api/v1/hosts/${a.host}`, { method: "PUT", json: { services: units.join(",") } });
      }
      toast(t("{p0} non viene più controllato", { p0: a.label }));
      load();
    } catch (e) { toast(e.message, "error"); }
  }

  function actions(item, d) {
    const a = item.action || {};
    const out = [];
    const host = d.hosts.find((h) => h.id === (a.host || item.host));
    if (a.kind === "host" || a.kind === "unmonitor") {
      out.push(el("a", { class: "btn small", href: hostHref(a.host) }, t("Apri {p0}", { p0: host ? host.name : t("server") })));
    }
    if (a.kind === "unmonitor" && !IS_VIEWER) {
      const b = el("button", { type: "button", class: "btn small" }, t("Non controllarlo più"));
      b.addEventListener("click", () => unmonitor(a));
      out.push(b);
    }
    if (a.kind === "view" && !(IS_VIEWER && a.view === "impostazioni")) {
      out.push(el("a", { class: "btn small", href: `#${a.view}` },
                  a.view === "connessione" ? t("Apri Connessione") : t("Apri le impostazioni")));
    }
    if (a.kind === "check") out.push(el("a", { class: "btn small", href: "#dispositivi" }, t("Apri Dispositivi")));
    if (a.kind === "help") out.push(el("button", { type: "button", class: "btn small", "data-help": a.page }, t("Cosa fare")));
    return out;
  }

  function renderTodo(d) {
    const list = $("#ov-todo");
    if (!d.todo.length) {
      const li = el("li", { class: "todo-empty" });
      li.append(svgIcon("i-ok"), el("span", {}, t("Niente da controllare: è tutto a posto.")));
      list.replaceChildren(li);
      return;
    }
    list.replaceChildren(...d.todo.map((item) => {
      const li = el("li", { class: `todo ${item.severity}` });
      const sev = el("span", { class: "sev" });
      sev.append(svgIcon(SEV[item.severity][1]), el("span", {}, SEV[item.severity][0]));
      const what = el("div", { class: "what" });
      const detail = [item.since ? t("dalle {p0}", { p0: fmtDateTime(item.since) }) : "", item.detail].filter(Boolean).join(" · ");
      what.append(el("strong", {}, item.title));
      if (detail) what.append(el("span", {}, detail));
      const acts = el("div", { class: "acts" });
      acts.append(...actions(item, d));
      li.append(sev, what, acts);
      return li;
    }));
  }

  // ------------------------------------------------------------------ server
  const STATUS = { OK: ["", t("regolare")], DOWN: ["alert", t("non raggiungibile")], WAITING: ["wait", t("in attesa")],
                   DISABLED: ["wait", t("disattivato")] };

  function metric(label, value, meter, lvl) {
    const m = el("div", { class: "metric" });
    m.append(el("span", { class: "label" }, label), el("span", { class: "value" }, value));
    if (meter !== null && meter !== undefined) {
      const bar = el("span", { class: `meter ${lvl || ""}` });
      const fill = el("i");
      fill.style.width = `${Math.max(0, Math.min(100, meter))}%`;
      bar.append(fill);
      m.append(bar);
    }
    return m;
  }

  function hostCard(h, d) {
    const problems = d.todo.filter((x) => x.host === h.id);
    const worst = problems.length ? problems[0].severity : null;
    const stopped = h.services.filter((s) => !s.up);
    let [cls, label] = STATUS[h.status] || ["wait", h.status];
    if (h.status === "DOWN" && h.notify_offline === false) [cls, label] = ["wait", t("spento")];   // 4.2
    if (h.status === "OK" && stopped.length) {
      cls = "warn";
      label = stopped.length === 1 ? t("1 servizio fermo") : t("{p0} servizi fermi", { p0: stopped.length });
    } else if (h.status === "OK" && worst === "alert") cls = "alert";
    else if (h.status === "OK" && worst === "warn") cls = "warn";
    const a = el("a", { class: `ov-host ${cls === "wait" ? "" : cls}`, href: hostHref(h.id), "data-card": `host-${h.id}` });

    const head = el("div", { class: "head" });
    const ic = el("span", { class: `ic${h.kind === "local" ? "" : " remote"}`, "aria-hidden": "true" });
    ic.append(svgIcon("i-server"));
    const who = el("div", { class: "who" });
    const name = el("strong", {}, h.name);
    name.append(el("small", {}, h.kind === "local" ? ` · ${t("server centrale")}` : ` · ${t("agente {p0}", { p0: h.agent_version || "–" })}`));
    const meta = [h.os, h.kind === "local" ? (h.uptime_s ? t("acceso da {p0}", { p0: fmtUptime(h.uptime_s) }) : "")
      : (h.last_seen ? t("ultimo invio {p0}", { p0: fmtDateTime(h.last_seen) }) : "")].filter(Boolean).join(" · ");
    who.append(name, el("span", {}, meta || "–"));
    const pill = el("span", { class: `pill ${cls}` });
    pill.append(el("span", { class: `dot ${cls === "" ? "ok" : cls === "wait" ? "" : cls}`, "aria-hidden": "true" }), el("span", {}, label));
    head.append(ic, who, pill);
    a.append(head);

    if (h.status === "OK") {
      const m = el("div", { class: "metrics" });
      const L = h.limits || {};                       // 4.2: soglie del server (o generali)
      m.append(metric(t("CPU"), pct(h.cpu_pct), h.cpu_pct, meterLevel(h.cpu_pct, L.cpu_warning ?? 90, L.cpu_alert ?? 98)),
               metric(t("Memoria"), pct(h.mem_pct), h.mem_pct, meterLevel(h.mem_pct, L.mem_warning ?? 90, L.mem_alert ?? 97)),
               metric(h.disks.length > 1 ? t("Disco più pieno") : t("Disco"), pct(h.disk_pct), h.disk_pct, meterLevel(h.disk_pct, L.disk_warning ?? 85, L.disk_alert ?? 95)),
               h.temperature_max !== null && h.temperature_max !== undefined
                 ? metric(t("Temperatura"), `${fmtNum(h.temperature_max, 0)} °C`, null)
                 : metric(t("Acceso da"), h.uptime_s ? fmtUptime(h.uptime_s) : "–", null));
      a.append(m);
      if (h.services.length) {
        const chips = el("div", { class: "chips" });
        const sorted = [...stopped, ...h.services.filter((s) => s.up)];
        sorted.slice(0, 8).forEach((s) => chips.append(el("span", { class: s.up ? "" : "down" }, s.up ? s.label : `${s.label} · ${t("fermo")}`)));
        if (sorted.length > 8) chips.append(el("span", { class: "more" }, t("+{p0} altri", { p0: sorted.length - 8 })));
        a.append(chips);
      }
    }
    return a;
  }

  // ------------------------------------------------------------------ riquadri in basso
  function renderConnection(c) {
    const box = $("#ov-conn");
    const f = (k) => box.querySelector(`[data-f="${k}"]`);
    const st = { OK: ["", t("regolare")], WARNING: ["warn", t("degradata")], DOWN: ["alert", t("assente")] }[c.status] || ["wait", "–"];
    f("pill").className = `pill ${st[0]}`; f("pill").textContent = st[1];
    const sp = c.speedtest;
    if (sp && sp.download_mbps !== null) {
      const pair = (txt) => { const s = el("span", {}, txt); s.append(el("small", {}, "Mbps")); return s; };
      f("speed").replaceChildren(pair(`↓ ${fmtNum(sp.download_mbps, 0)}`), pair(`↑ ${fmtNum(sp.upload_mbps, 0)}`));
    } else f("speed").textContent = t("nessuno speedtest");
    f("latency").textContent = c.latency_ms === null ? "–" : `${fmtNum(c.latency_ms, 0)} ms`;
    f("speedtime").textContent = sp ? fmtDateTime(sp.timestamp) : "–";
    f("ip").textContent = (c.public_ip && c.public_ip.ip) || "–";
  }

  function step(level, title, sub) {
    const li = el("li", { class: level });
    li.append(svgIcon(level === "ok" ? "i-ok" : level === "wait" ? "i-clock" : "i-alert"));
    const d = el("div");
    d.append(el("strong", {}, title));
    if (sub) d.append(el("span", {}, sub));
    li.append(d);
    return li;
  }

  function renderBackup(b, box) {
    const f = (k) => box.querySelector(`[data-f="${k}"]`);
    const rt = b.restore_test;
    const bad = b.status === "ALERT" || (rt && ["ALERT", "DOWN"].includes(rt.status));
    f("pill").className = `pill ${!b.status ? "wait" : bad ? "alert" : ""}`;
    f("pill").textContent = !b.status ? "–" : bad ? t("da controllare") : t("protetti");
    const steps = [];
    if (!b.status) steps.push(step("wait", t("Nessun backup registrato"), t("si configura nelle impostazioni")));
    else {
      steps.push(step(b.status === "OK" ? "ok" : "alert", b.status === "OK" ? t("Backup completato") : t("Backup non riuscito"),
                      `${fmtDateTime(b.time)} · ${b.databases === 1 ? t("1 database") : t("{p0} database", { p0: b.databases })}`));
      steps.push(step(b.github || b.destinations ? "ok" : "wait", b.github ? t("Copia su GitHub") : b.destinations ? t("Copia su altre destinazioni") : t("Solo copia locale"),
                      b.destinations ? (b.destinations === 1 ? t("1 destinazione") : t("{p0} destinazioni", { p0: b.destinations })) : ""));
    }
    if (rt && rt.status) {
      steps.push(step(rt.status === "OK" ? "ok" : "alert", rt.status === "OK" ? t("Prova di ripristino riuscita") : t("Prova di ripristino non riuscita"),
                      fmtDateTime(rt.time)));
    } else steps.push(step("wait", t("Prova di ripristino"), t("non ancora eseguita")));
    f("steps").replaceChildren(...steps);
  }

  function renderEvents(list, multi) {
    const box = $("#ov-events [data-f='list']");
    if (!list.length) { box.replaceChildren(el("li", { class: "empty" }, t("Nessun evento nelle ultime 24 ore."))); return; }
    box.replaceChildren(...list.map((e) => {
      const li = el("li", { class: e.severity });
      li.append(el("time", { datetime: e.time }, clock(e.time)));
      const line = el("span");
      if (multi) { line.append(el("strong", {}, e.host)); line.append(document.createTextNode(` · ${e.title}`)); }
      else line.append(el("strong", {}, e.title));
      li.append(line);
      if (e.detail) li.append(el("small", {}, e.detail));
      return li;
    }));
  }

  // vista Server, modo elenco (4.1): le stesse schede della Panoramica
  function renderServerList() {
    if (!last) return;
    $("#srv-list-cards").replaceChildren(...last.hosts.filter((h) => h.enabled || h.kind === "local").map((h) => hostCard(h, last)));
  }
  window.AM.renderServerList = renderServerList;

  // ------------------------------------------------------------------ caricamento
  async function load() {
    if (document.hidden && last) return;
    let d;
    try { d = await api("/api/v1/overview"); }
    catch (e) {
      $("#ov-headline").textContent = t("Dati non disponibili");
      $("#ov-summary").textContent = e.message;
      $("#ov-hero").dataset.level = "alert";
      return;
    }
    last = d;
    renderHero(d);
    renderKpis(d);
    renderTodo(d);
    $("#ov-hosts").replaceChildren(...d.hosts.filter((h) => h.enabled || h.kind === "local").map((h) => hostCard(h, d)));
    $("#ov-hosts").$default = d.hosts.map((h) => `host-${h.id}`);      // ordine di partenza per "Ripristina ordine"
    if (window.AM.applyLayout) window.AM.applyLayout("ov-hosts");
    renderConnection(d.connection);
    renderBackup(d.backup, $("#ov-backup"));
    renderBackup(d.backup, $("#bk-summary"));
    renderServerList();
    renderEvents(d.events, d.hosts.filter((h) => h.enabled).length > 1);
    greeting();
  }

  $("#ov-goto").addEventListener("click", (ev) => {
    ev.preventDefault();
    $("#da-controllare").scrollIntoView({ behavior: "smooth", block: "start" });
  });

  document.addEventListener("DOMContentLoaded", () => {
    every(30_000, load);
    document.addEventListener("hosts-changed", load);                    // anche fuori dalla Panoramica: tiene aggiornato il numero nel menu
    window.AM.onView("panoramica", () => { greeting(); if (last) load(); });
    window.AM.overview = () => last;                 // per la ricerca Ctrl K (servizi dei server)
    setInterval(greeting, 60_000);
  });
})();
