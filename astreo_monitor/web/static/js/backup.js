/* Astreo Monitor - Impostazioni → Backup: stato, esecuzione immediata, destinazioni rclone. */
(() => {
  "use strict";
  const { t, $, api, el, toast, fmtNum, fmtFull } = window.AM;

  function stat(label, value, sub) {
    const a = el("article", { class: "stat" });
    a.append(el("h3", {}, label), el("p", { class: "value" }, value));
    if (sub) a.append(el("p", { class: "sub" }, sub));
    return a;
  }
  const size = (n) => (n == null ? "–" : n > 1e9 ? `${fmtNum(n / 1e9, 2)} GB` : `${fmtNum(n / 1e6, 1)} MB`);

  async function load() {
    let d;
    try { d = await api("/api/v1/backup"); } catch (e) { toast(e.message, "error"); return; }
    const last = d.last || {};
    const dbs = last.databases || [];
    $("#bk-stats").replaceChildren(
      stat(t("Esito"), last.status || "–", last.time ? fmtFull(last.time) : t("mai eseguito")),
      stat(t("Database"), String(dbs.length), dbs.map((x) => x.database).join(", ")),
      stat(t("Dimensione"), size(dbs.reduce((a, x) => a + (x.zst_bytes || 0), 0)), t("compressi")),
      stat(t("Prossimo backup"), d.timer && d.timer.next_run ? fmtFull(d.timer.next_run) : "–"),
    );
    const res = [];
    if (last.release) res.push({ ok: true, text: t("GitHub: {p0}", { p0: last.release }) });
    (last.destinations || []).forEach((x) => res.push({ ok: x.ok, text: x.ok ? t("Copia verificata su {p0}", { p0: x.path })
      : t("Copia su {p0} non riuscita: {p1}", { p0: x.dest, p1: x.error }) }));
    (last.errors || []).filter((e) => !e.startsWith("rclone ")).forEach((e) => res.push({ ok: false, text: e }));
    $("#bk-dest-results").replaceChildren(...res.map((r) => el("li", { class: r.ok ? "ok" : "ko" }, r.text)));
    $("#bk-where").textContent = [
      d.local_dir ? t("Copie locali in {p0} (ne conservo {p1})", { p0: d.local_dir, p1: d.local_keep }) : "",
      d.github_repo ? t("GitHub: {p0} (ne conservo {p1})", { p0: d.github_repo, p1: d.github_keep }) : t("GitHub: non configurato"),
    ].filter(Boolean).join(" · ");
    $("#bk-rclone").textContent = !d.rclone.available ? t("rclone non è installato: sudo apt install rclone")
      : d.rclone.remotes.length ? t("Remote configurati: {p0}", { p0: d.rclone.remotes.join(" ") })
      : t("Nessun remote configurato: si creano con «rclone config» come utente dei servizi (docs/it/backup.md).");
    const s = await api("/api/v1/settings");
    $('#form-backup [data-key="backup.rclone_destinations"]').value = (s.values["backup.rclone_destinations"] || "").replace(/,\s*/g, "\n");
    $('#form-backup [data-key="backup.rclone_keep"]').value = s.values["backup.rclone_keep"];
  }

  async function save(ev) {
    ev.preventDefault();
    const dests = $('#form-backup [data-key="backup.rclone_destinations"]').value.split("\n").map((x) => x.trim()).filter(Boolean);
    try {
      await api("/api/v1/settings", { method: "PUT", json: {
        "backup.rclone_destinations": dests.join("\n"),
        "backup.rclone_keep": Number($('#form-backup [data-key="backup.rclone_keep"]').value) } });
      toast(t("Impostazioni del backup salvate"));
    } catch (e) { toast(e.message, "error"); }
  }

  async function testAll() {
    const dests = $('#form-backup [data-key="backup.rclone_destinations"]').value.split("\n").map((x) => x.trim()).filter(Boolean);
    const out = $("#bk-test-results");
    if (!dests.length) { out.replaceChildren(el("li", {}, t("Nessuna destinazione da provare"))); return; }
    out.replaceChildren(...dests.map((x) => el("li", { "data-dest": x }, t("{p0}: prova in corso…", { p0: x }))));
    for (const x of dests) {
      const li = [...out.children].find((n) => n.dataset.dest === x);
      try {
        const r = await api("/api/v1/backup/test", { method: "POST", json: { dest: x } });
        li.className = r.ok ? "ok" : "ko";
        li.textContent = `${x}: ${r.detail}`;
      } catch (e) { li.className = "ko"; li.textContent = `${x}: ${e.message}`; }
    }
  }

  async function runNow() {
    try {
      await api("/api/v1/backup/run", { method: "POST", json: {} });
      toast(t("Backup avviato: l'esito compare qui e nei Controlli entro qualche minuto."));
      setTimeout(load, 60_000);
    } catch (e) { toast(e.message, "error"); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.AM.IS_VIEWER) return;
    $("#form-backup").addEventListener("submit", save);
    $("#bk-test").addEventListener("click", testAll);
    $("#bk-run").addEventListener("click", runNow);
    document.addEventListener("subtab", (ev) => { if (ev.detail.sub === "backup") load(); });
  });
})();
