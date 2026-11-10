# finto server NUT per le prove
import socketserver, threading
VARS = {"ups.status": "OB DISCHRG", "battery.charge": "87", "battery.runtime": "1260", "ups.load": "23",
        "input.voltage": "0.0", "output.voltage": "230.0", "device.mfr": "EATON", "device.model": "Ellipse PRO 650", "ups.serial": "X1"}
class H(socketserver.StreamRequestHandler):
    def handle(self):
        for raw in self.rfile:
            cmd = raw.decode().strip()
            if cmd == "LIST UPS":
                self.wfile.write(b'BEGIN LIST UPS\nUPS eaton "Eaton Ellipse"\nEND LIST UPS\n')
            elif cmd.startswith("LIST VAR"):
                name = cmd.split()[2]
                if name != "eaton":
                    self.wfile.write(b"ERR UNKNOWN-UPS\n"); continue
                out = f"BEGIN LIST VAR {name}\n" + "".join(f'VAR {name} {k} "{v}"\n' for k, v in VARS.items()) + f"END LIST VAR {name}\n"
                self.wfile.write(out.encode())
            elif cmd == "LOGOUT":
                self.wfile.write(b"OK Goodbye\n"); return
def start(port=34930):
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start(); return srv
