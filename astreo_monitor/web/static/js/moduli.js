/* Astreo Monitor - moduli opzionali (Docker, Pi-hole) ed elenchi degli eventi. */
(() => {
  "use strict";
  const { $, $$, api, el, row, fmtNum, fmtDateTime, fmtFull, every, eventState, EVENT_COLOR } = window.AM;
  const mods = { list: [] };

  // ------------------------------------------------------------ moduli
  async function loadModules() {
    try {
      const d = await api("/api/v1/integrations");
      mods.list = d.modules;
      eventState.visible = d.events_visible;
      d.modules.forEach((m) => {
        const panel = $(`#mod-${m.key}`);
        if (panel) panel.hidden = !(m.available && m.visible);
      });
      document.dispatchEvent(new Event("modules-loaded"));
      if (window.AM.isView("server")) refreshModules();
    } catch (e) { console.error("moduli", e); }
  }
  const shown = (key) => mods.list.some((m) => m.key === key && m.available && m.visible);

  async function loadDocker() {
    if (!shown("docker")) return;
    try {
      const d = await api("/api/v1/docker");
      $("#docker-info").textContent = d.reason;
      $("#docker-empty").hidden = d.containers.length > 0;
      $("#docker-table").hidden = d.containers.length === 0;
      $("#docker-table tbody").replaceChildren(...d.containers.map((c) => {
        const led = el("span", { class: `led ${c.state === "running" ? "up" : "down"}` });
        const name = el("div"); name.append(led, document.createTextNode(` ${c.name}`));
        return row([
          { node: name, label: "Container" }, { text: c.image, label: "Immagine", cls: "cmd", title: c.image },
          { text: c.status + (c.health ? ` (${c.health})` : ""), label: "Stato", cls: c.state === "running" ? "" : "alert" },
          { text: c.cpu || "–", cls: "num", label: "CPU" }, { text: c.mem || "–", label: "Memoria" },
          { text: c.restart_count, cls: `num ${c.restart_count ? "warn" : ""}`, label: "Riavvii" },
        ]);
      }));
    } catch (e) { console.error("docker", e); }
  }

  function stat(label, value, sub) {
    const a = el("article", { class: "stat" });
    a.append(el("h3", {}, label));
    const p = el("p", { class: "value" }, value);
    a.append(p);
    if (sub) a.append(el("p", { class: "sub" }, sub));
    return a;
  }
  async function loadPihole() {
    if (!shown("pihole")) return;
    try {
      const d = await api("/api/v1/pihole");
      const msg = $("#pihole-msg");
      msg.hidden = true;
      if (!d.configured || d.error) {
        $("#pihole-stats").replaceChildren();
        msg.textContent = d.error ? `Pi-hole non leggibile: ${d.error}` : "Imposta la password per le app in Impostazioni → Moduli per vedere le statistiche.";
        msg.hidden = false;
        return;
      }
      const on = d.blocking === "enabled";
      $("#pihole-info").textContent = on ? "blocco attivo" : `blocco ${d.blocking}`;
      $("#pihole-info").className = on ? "" : "warn-text";
      const upd = d.gravity_updated ? fmtDateTime(new Date(d.gravity_updated * 1000).toISOString()) : "–";
      $("#pihole-stats").replaceChildren(
        stat("Richieste oggi", fmtNum(d.queries_total, 0), `${fmtNum(d.unique_domains, 0)} domini diversi`),
        stat("Bloccate", fmtNum(d.queries_blocked, 0), `${fmtNum(d.percent_blocked, 1)}%`),
        stat("Client attivi", fmtNum(d.clients_active, 0), `su ${fmtNum(d.clients_total, 0)}`),
        stat("Domini in blocco", fmtNum(d.domains_blocked, 0), `liste aggiornate ${upd}`),
        stat("Da cache / inoltrate", `${fmtNum(d.cached, 0)} / ${fmtNum(d.forwarded, 0)}`),
      );
    } catch (e) { console.error("pihole", e); }
  }
  function refreshModules() { loadDocker(); loadPihole(); }

  // ------------------------------------------------------- elenchi eventi
  function renderEvents(panel, events) {
    if (!panel) return;
    panel.hidden = !eventState.visible;
    if (!eventState.visible) return;
    const kinds = eventState.kinds || {};
    const present = [...new Set(events.map((e) => e.kind))];
    const bar = $("[data-events-filters]", panel);
    bar.replaceChildren(...present.map((k) => {
      const b = el("button", { type: "button", class: `chip ${eventState.hidden.has(k) ? "off" : ""}` });
      b.style.setProperty("--chip", EVENT_COLOR[k] || "#e8b85c");
      b.textContent = `${kinds[k] || k} (${events.filter((e) => e.kind === k).length})`;
      b.addEventListener("click", () => {
        if (eventState.hidden.has(k)) eventState.hidden.delete(k); else eventState.hidden.add(k);
        window.AM.redrawEvents();
      });
      return b;
    }));
    const list = $("[data-events-list]", panel);
    const vis = window.AM.visibleEvents(events);
    list.replaceChildren(...(vis.length ? [...vis].reverse().slice(0, 100).map((e) => {
      const li = el("li");
      li.style.setProperty("--chip", EVENT_COLOR[e.kind] || "#e8b85c");
      li.append(el("time", {}, fmtFull(e.time)), el("strong", {}, e.title), el("span", {}, e.detail || ""));
      return li;
    }) : [el("li", { class: "empty" }, events.length ? "Tutti gli eventi sono nascosti dai filtri." : "Nessun evento nel periodo.")]));
    panel.$events = events;
  }
  document.addEventListener("events-filter", () => {
    $$(".events-panel").forEach((p) => { if (p.$events) renderEvents(p, p.$events); });
  });

  window.AM.renderEvents = renderEvents;
  window.AM.loadModules = loadModules;
  document.addEventListener("DOMContentLoaded", () => {
    loadModules();
    every(60_000, refreshModules, "server");
    window.AM.onView("server", refreshModules);
  });
})();
