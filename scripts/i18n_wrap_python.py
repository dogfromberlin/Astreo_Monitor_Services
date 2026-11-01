"""Strumento di sviluppo: avvolge in _() i testi italiani rivolti all'utente in un modulo Python.

"testo"          -> _("testo")
f"testo {x}"     -> _("testo {p0}", p0=x)        (con formato: p0=f"{x:.1f}")
Salta: docstring, log.*(), chiavi di dict, confronti, indici, argomenti di subprocess/SQL/regex,
testi già dentro _().  Uso: python scripts/i18n_wrap_python.py file.py [--dry]
"""
import ast
import re
import sys

IT = re.compile(r"[a-zà-ù]{2,}\s+[a-zà-ùA-Z(]|[àèéìòù]|^[A-ZÀ-Ù][a-zà-ù]{3,}[.:]?$")
SKIP_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "run", "Popen", "execute", "text", "compile",
              "search", "match", "findall", "sub", "_", "t", "get", "getboolean", "getint", "startswith", "endswith",
              "add_argument_group", "replace", "split", "join", "strftime", "strptime", "sh", "systemctl", "apt",
              "write", "remove_section", "has_section", "set_main_option", "chown", "Path", "open"}


COMMANDS = ("systemctl", "journalctl", "sudo", "docker", "apt", "git", "python", ".venv", "cd ", "ls ", "curl", "smartctl",
            "nginx", "openssl", "mkcert", "id ", "grep", "diff ", "runuser", "psql", "env ")


def is_italian(s: str) -> bool:
    return bool(s) and bool(IT.search(s)) and not s.startswith(("/", "http", "SELECT", "#!") + COMMANDS)


def convert(src: str) -> str:
    tree = ast.parse(src)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Constant, ast.JoinedStr)):
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        p = parents.get(node)
        if isinstance(p, ast.JoinedStr):
            continue
        if isinstance(p, ast.Expr):                     # docstring o stringa isolata
            continue
        if isinstance(p, ast.Call) and isinstance(p.func, (ast.Attribute, ast.Name)):
            fname = p.func.attr if isinstance(p.func, ast.Attribute) else p.func.id
            owner = p.func.value.id if isinstance(p.func, ast.Attribute) and isinstance(p.func.value, ast.Name) else ""
            if fname in SKIP_CALLS or owner in ("log", "re", "subprocess", "os", "shutil"):
                continue
        if isinstance(p, ast.Dict) and node in p.keys:
            continue
        if isinstance(p, (ast.Compare, ast.Subscript)):
            continue
        if isinstance(p, ast.keyword) and p.arg in ("default", "choices", "prog", "metavar", "dest"):
            continue
        if isinstance(p, ast.BinOp):                    # pezzi concatenati: li tratta il chiamante a mano
            pass
        if isinstance(node, ast.Constant):
            if not is_italian(node.value):
                continue
            rep = "_(" + repr(node.value).replace("'", '"') if '"' not in node.value else "_(" + repr(node.value)
            rep = "_(" + _q(node.value) + ")"
        else:
            text, args, k = "", [], 0
            ok = True
            for v in node.values:
                if isinstance(v, ast.Constant):
                    text += v.value.replace("{", "{{").replace("}", "}}")
                elif isinstance(v, ast.FormattedValue):
                    expr = ast.get_source_segment(src, v.value)
                    if v.format_spec is not None or v.conversion != -1:
                        seg = ast.get_source_segment(src, v)
                        expr = "f" + _q(seg)
                    text += "{p%d}" % k
                    args.append(f"p{k}={expr}")
                    k += 1
                else:
                    ok = False
            plain = re.sub(r"\{p\d+\}", " ", text)
            if not ok or not is_italian(plain):
                continue
            rep = "_(" + _q(text) + (", " + ", ".join(args) if args else "") + ")"
        edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, rep))
    lines = src.splitlines(keepends=True)
    offs = [0]
    for line in lines:
        offs.append(offs[-1] + len(line))
    for l1, c1, l2, c2, rep in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        a, b = offs[l1 - 1] + _col(lines[l1 - 1], c1), offs[l2 - 1] + _col(lines[l2 - 1], c2)
        src = src[:a] + rep + src[b:]
    return src


def _col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "ignore"))


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    for path in [a for a in sys.argv[1:] if not a.startswith("--")]:
        src = open(path, encoding="utf-8").read()
        out = convert(src)
        if dry:
            import difflib
            sys.stdout.writelines(difflib.unified_diff(src.splitlines(True), out.splitlines(True), path, path, n=0))
        else:
            open(path, "w", encoding="utf-8").write(out)
