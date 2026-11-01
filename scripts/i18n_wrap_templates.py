"""Strumento di sviluppo: avvolge i testi dei modelli HTML in {{ _("...") }}. Idempotente."""
import re
import sys

ATTRS = ("title", "placeholder", "aria-label")


def jinja_str(s: str) -> str:
    s = " ".join(s.split())          # chiave su una riga: il browser comprime comunque gli spazi
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def wrap(html: str) -> str:
    out, i = [], 0
    for m in re.finditer(r"<(script|style)\b.*?</\1>", html, re.S | re.I):     # salta script e stili
        out.append(_wrap(html[i:m.start()]))
        out.append(m.group(0))
        i = m.end()
    out.append(_wrap(html[i:]))
    return "".join(out)


def _wrap(chunk: str) -> str:
    def text(m):
        lead, body, trail = m.group(1), m.group(2), m.group(3)
        if not re.search(r"[A-Za-zÀ-ù]{2}", body) or "{{" in body or "{%" in body or body.strip().startswith(("&", "–")):
            return m.group(0)
        return f">{lead}{{{{ _({jinja_str(body)}) }}}}{trail}<"
    chunk = re.sub(r">(\s*)([^<>]*?[^\s<>])(\s*)<", text, chunk)

    def attr(m):
        name, val = m.group(1), m.group(2)
        if "{{" in val or not re.search(r"[A-Za-zÀ-ù]{2}", val):
            return m.group(0)
        return f'{name}="{{{{ _({jinja_str(val)}) }}}}"'
    return re.sub(r'\b(%s)="([^"]*)"' % "|".join(ATTRS), attr, chunk)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        src = open(path, encoding="utf-8").read()
        open(path, "w", encoding="utf-8").write(wrap(src))
