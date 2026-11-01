"""Strumento di sviluppo: avvolge i testi italiani degli script in t(). Idempotente.

"testo"            -> t("testo")
`testo ${expr}`    -> t("testo {p0}", { p0: expr })
Salta: HTML, classi CSS (cls:/class:), "use strict", testi già dentro t(), template annidati.
"""
import re
import sys

IT = re.compile(r"[a-zà-ù]{2,}\s+[a-zà-ùA-Z(]|[àèéìòù]|^[A-ZÀ-Ù][a-zà-ù]{3,}$")
SKIP = {"use strict", "Email", "Telegram", "WhatsApp", "Mbps", "Download", "Upload"}


def js_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def template_parts(body):
    """Divide un template literal in testo e ${espressioni}; None se ci sono backtick annidati."""
    out, i, n, text = [], 0, 0, []
    while i < len(body):
        if body.startswith("${", i):
            depth, j = 1, i + 2
            while j < len(body) and depth:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                elif body[j] == "`":
                    return None
                j += 1
            out.append(("".join(text), body[i + 2:j - 1]))
            text = []
            i = j
        else:
            text.append(body[i])
            i += 1
    return out, "".join(text)


def convert_line(line):
    if "querySelector" in line or line.strip().startswith("//") or line.count("`") > 2:
        return line                      # template annidati: a mano
    res, pos = [], 0
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', line):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        before = line[:m.start()]
        skip = (not s or not IT.search(s) or s in SKIP or "<" in s or s.startswith(("/api", "#", ".", "["))
                or re.search(r"(cls|class|className)\s*:\s*$", before) or re.search(r"(^|[^\w.$])t\(\s*$", before)
                or (before.rstrip().endswith(("{", ",")) and line[m.end():].lstrip().startswith(":"))
                or re.search(r"(===|!==|==|!=|case)\s*$", before) or line[m.end():].lstrip().startswith(("===", "!==")))
        if skip:
            continue
        if m.group(1) is not None:
            rep = f"t({js_str(s)})"
        else:
            parts = template_parts(s)
            if parts is None:
                continue
            chunks, tail = parts
            key, vals = "", []
            for k, (txt, expr) in enumerate(chunks):
                key += txt + "{p%d}" % k
                vals.append(f"p{k}: {expr}")
            key += tail
            rep = f"t({js_str(key)}" + (f", {{ {', '.join(vals)} }})" if vals else ")")
        res.append(line[pos:m.start()] + rep)
        pos = m.end()
    res.append(line[pos:])
    return "".join(res)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        lines = open(path, encoding="utf-8").read().split("\n")
        open(path, "w", encoding="utf-8").write("\n".join(convert_line(l) for l in lines))
