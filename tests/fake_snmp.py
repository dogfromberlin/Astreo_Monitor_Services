import socket, threading, sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from astreo_monitor.ups import snmp as S
VALUES = {S.UPS_MIB["mfr"]: (0x04, b"EATON"), S.UPS_MIB["model"]: (0x04, b"5PX 1500"), S.UPS_MIB["source"]: (0x02, 5),
          S.UPS_MIB["charge"]: (0x02, 76), S.UPS_MIB["minutes"]: (0x02, 14), S.UPS_MIB["load"]: (0x02, 31), S.UPS_MIB["bstatus"]: (0x02, 2),
          S.UPS_MIB["in_v"]: (0x02, 0), S.UPS_MIB["out_v"]: (0x02, 230)}
def enc(tag, v):
    if tag == 0x04: return S._tlv(0x04, v)
    return S._int(v)
def serve(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", port))
    def loop():
        while True:
            data, addr = s.recvfrom(65535)
            _t, body, _ = S._parse(data); items = S._children(body); p = S._children(items[2][1])
            vbs = b""
            for _t2, vb in S._children(p[3][1]):
                (_to, ob), _n = S._children(vb); oid = S._decode_oid(ob)
                val = enc(*VALUES[oid]) if oid in VALUES else S._tlv(0x80, b"")
                vbs += S._tlv(0x30, S._oid(oid) + val)
            pdu = S._tlv(0xA2, S._tlv(0x02, p[0][1]) + S._int(0) + S._int(0) + S._tlv(0x30, vbs))
            s.sendto(S._tlv(0x30, S._int(1) + S._tlv(0x04, b"public") + pdu), addr)
    threading.Thread(target=loop, daemon=True).start()
