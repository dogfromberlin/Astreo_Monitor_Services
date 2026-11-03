"""4.0: agenti Linux e Windows (coda locale, invio, risposta del centrale)."""
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest
import requests

from astreo_monitor.agent import run as agent_run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIVED = []
REPLY = {"code": 200}


class Central(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECEIVED.append({"auth": self.headers.get("Authorization"), "body": body})
        self.send_response(REPLY["code"])
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "accepted": len(body["items"]), "services": ["ssh.service"]}).encode())


@pytest.fixture(scope="module")
def central():
    srv = HTTPServer(("127.0.0.1", 0), Central)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def make_agent(tmp_path, url):
    (tmp_path / "token").write_text("agt_" + "x" * 30)
    (tmp_path / "agent.ini").write_text(f"[agent]\ncentral = {url}\ntoken_file = {tmp_path}/token\n"
                                        f"ca_file = {tmp_path}/ca.crt\nstate_dir = {tmp_path}/state\n")
    return agent_run.Agent(str(tmp_path / "agent.ini"))


def test_agente_linux_coda_e_invio(tmp_path, central):
    RECEIVED.clear()
    a = make_agent(tmp_path, central)
    items = a.collect(agent_run.dt.datetime.now().replace(microsecond=0))
    assert [i["type"] for i in items] == ["metrics"] or items[0]["type"] == "metrics"
    m = [i for i in items if i["type"] == "metrics"][0]
    assert 0 <= m["cpu_pct"] <= 100 and m["mem_used_pct"] > 0
    assert m["disks"] and all({"mountpoint", "used_pct", "free_mb"} <= set(d) for d in m["disks"])
    # centrale irraggiungibile: i dati restano in coda
    a.enqueue(items)
    with mock.patch.object(agent_run.requests, "post", side_effect=requests.ConnectionError("giù")):
        assert a.send() == 0
    assert len(os.listdir(a.queue)) == len(items)
    # torna raggiungibile: si svuota la coda e si ricevono i servizi da controllare
    assert a.send() == len(items)
    assert os.listdir(a.queue) == [] and a.state["services"] == ["ssh.service"]
    assert RECEIVED[-1]["auth"] == "Bearer agt_" + "x" * 30 and RECEIVED[-1]["body"]["agent"]["kind"] == "linux"


def test_agente_linux_dati_rifiutati_scartati(tmp_path, central):
    a = make_agent(tmp_path, central)
    a.enqueue([{"type": "metrics", "time": "2026-01-01T00:00:00"}])
    REPLY["code"] = 400
    try:
        a.send()
    finally:
        REPLY["code"] = 200
    assert os.listdir(a.queue) == []          # non si riprova all'infinito un dato rifiutato


def test_agente_linux_coda_oltre_24_ore(tmp_path, central):
    a = make_agent(tmp_path, central)
    old = os.path.join(a.queue, f"{(agent_run.time.time_ns() - 25 * 3600 * 10**9)}-000.json")
    open(old, "w").write("{}")
    assert a.pending() == [] and not os.path.exists(old)


PWSH = shutil.which("pwsh") or ("/tmp/pwsh/pwsh" if os.path.exists("/tmp/pwsh/pwsh") else None)
WIN = os.path.join(ROOT, "agent", "windows")


@pytest.mark.skipif(not PWSH, reason="PowerShell non disponibile")
def test_script_windows_senza_errori_di_sintassi():
    cmd = ("foreach ($f in Get-ChildItem *.ps1) { $t=$null; $e=$null; "
           "[void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t, [ref]$e); "
           "if ($e.Count) { $f.Name + ': ' + $e[0].Message } }")
    out = subprocess.run([PWSH, "-NoProfile", "-Command", cmd], cwd=WIN, capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == "", out.stdout


STUBS = r"""
$global:Boot = [datetime]'2026-11-01T08:00:00'
function Get-CimInstance { param($ClassName, $Filter, $ErrorAction)
  switch ($ClassName) {
    'Win32_OperatingSystem' { [pscustomobject]@{ LastBootUpTime = $global:Boot; TotalVisibleMemorySize = 8388608; FreePhysicalMemory = 2097152; Caption = 'Microsoft Windows 11 Pro'; Version = '10.0.22631' } }
    'Win32_PerfFormattedData_PerfOS_Processor' { [pscustomobject]@{ PercentProcessorTime = 20 } }
    'Win32_PageFileUsage' { [pscustomobject]@{ AllocatedBaseSize = 2048; CurrentUsage = 512 } }
    'Win32_LogicalDisk' {
      $c = [pscustomobject]@{ DeviceID = 'C:'; Size = 100GB; FreeSpace = 25GB; FileSystem = 'NTFS'; VolumeName = 'Sistema' }
      $d = [pscustomobject]@{ DeviceID = 'D:'; Size = 2000GB; FreeSpace = 100GB; FileSystem = 'NTFS'; VolumeName = 'Dati' }
      if ($Filter -eq 'DriveType=3') { $c, $d } elseif ($Filter -like "*'D:'*") { $d } else { $c } }
  } }
function Get-Service { param($Name, $ErrorAction) [pscustomobject]@{ DisplayName = "Nome di $Name"; Status = 'Running' } }
function Start-Sleep { param($Milliseconds) }
$env:SystemDrive = 'C:'; $env:COMPUTERNAME = 'PC-UFFICIO'
"""


@pytest.mark.skipif(not PWSH, reason="PowerShell non disponibile")
def test_agente_windows_con_comandi_simulati(tmp_path, central):
    """Logica dell'agente Windows (coda, metriche, servizi ricevuti dal centrale) con i comandi di Windows simulati."""
    RECEIVED.clear()
    (tmp_path / "agent.json").write_text(json.dumps({"central": central, "token": "agt_" + "w" * 30, "ca_file": ""}))
    (tmp_path / "stubs.ps1").write_text(STUBS)
    script = os.path.join(WIN, "astreo-agent.ps1")
    for _ in range(2):
        out = subprocess.run([PWSH, "-NoProfile", "-Command", f". '{tmp_path}/stubs.ps1'; & '{script}' -ConfigPath '{tmp_path}/agent.json'"],
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0, out.stdout + out.stderr
    first, second = RECEIVED[0]["body"], RECEIVED[1]["body"]
    assert first["agent"]["kind"] == "windows" and first["agent"]["os"].startswith("Microsoft Windows 11")
    m = [i for i in first["items"] if i["type"] == "metrics"][0]
    assert m["cpu_pct"] == 20 and m["mem_used_pct"] == 75.0 and m["disk_used_pct"] == 75.0 and m["swap_used_pct"] == 25.0
    assert [(d["mountpoint"], d["label"], d["used_pct"]) for d in m["disks"]] == [("C:", "Sistema", 75.0), ("D:", "Dati", 95.0)]
    svc = [i for i in second["items"] if i["type"] == "services"][0]["services"]       # elenco ricevuto al primo invio
    assert svc == [{"unit": "ssh.service", "label": "Nome di ssh.service", "up": True, "state": "running"}]
    assert RECEIVED[0]["auth"] == "Bearer agt_" + "w" * 30
    assert os.listdir(tmp_path / "queue") == []
