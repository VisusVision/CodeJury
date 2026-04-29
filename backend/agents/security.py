"""
Security Agent -- tam LLM: guvenlik yorumu Ollama ile.

AST/regex ozeti yalnizca prompt ipucu; threats, risk ve skor LLM ciktisindan (LLM zorunlu).

Girdi:  {"source_code": str, "language": str}
Cikti:  {"threats": list, "risk_level": str, "safe": bool,
         "blocked_imports": list, "score": int (0-100)}
"""

import ast
import json
import re

from backend.agents.base import BaseAgent, build_llm_user_suffix, format_assignment_context_for_prompt

# ═══════════════════════════════════════════════════════════════════════════════
# TEHDIT TANIMLARI
# ═══════════════════════════════════════════════════════════════════════════════

_DANGEROUS_FUNCTIONS = {
    "eval":       ("code_injection",    "critical", "eval() rastgele kod calistirir"),
    "exec":       ("code_injection",    "critical", "exec() rastgele kod calistirir"),
    "compile":    ("code_injection",    "high",     "compile() dinamik kod olusturur"),
    "__import__": ("code_injection",    "high",     "__import__() dinamik modul yukler"),
    "globals":    ("sandbox_escape",    "medium",   "globals() global degiskenlere erisir"),
    "getattr":    ("sandbox_escape",    "medium",   "getattr() dinamik attribute erisimi"),
    "setattr":    ("sandbox_escape",    "medium",   "setattr() dinamik attribute degisimi"),
    "delattr":    ("sandbox_escape",    "low",      "delattr() dinamik attribute silme"),
}

_DANGEROUS_IMPORTS = {
    # Sistem erisimi
    "os":           ("system_access",   "critical", "os modulu -- dosya sistemi ve komut erisimi"),
    "subprocess":   ("command_inject",  "critical", "subprocess -- harici komut calistirma"),
    "shutil":       ("system_access",   "high",     "shutil -- dosya kopyalama/silme"),
    "pathlib":      ("file_access",     "low",      "pathlib -- dosya yolu islemleri"),
    # Network
    "socket":       ("network_access",  "critical", "socket -- ag baglantisi acma"),
    "requests":     ("network_access",  "critical", "requests -- HTTP istekleri"),
    "urllib":       ("network_access",  "critical", "urllib -- URL erisimi"),
    "http":         ("network_access",  "high",     "http modulu -- HTTP sunucu/istemci"),
    "ftplib":       ("network_access",  "high",     "ftplib -- FTP erisimi"),
    "smtplib":      ("network_access",  "high",     "smtplib -- e-posta gonderme"),
    # Tehlikeli serializasyon
    "pickle":       ("deserialization", "high",     "pickle -- guvenli olmayan deserialization"),
    "marshal":      ("deserialization", "high",     "marshal -- dusuk seviye serializasyon"),
    "shelve":       ("deserialization", "medium",   "shelve -- pickle tabanli depolama"),
    # Dinamik kod
    "importlib":    ("code_injection",  "high",     "importlib -- dinamik modul yukleme"),
    "ctypes":       ("system_access",   "critical", "ctypes -- C kutuphanelerine direkt erisim"),
    "multiprocessing": ("system_access","high",     "multiprocessing -- yeni proses olusturma"),
    "threading":    ("system_access",   "medium",   "threading -- thread olusturma"),
    # Sandbox kacis
    "inspect":      ("sandbox_escape",  "high",     "inspect -- frame/stack inceleme"),
    "gc":           ("sandbox_escape",  "medium",   "gc -- garbage collector manipulasyonu"),
    "code":         ("sandbox_escape",  "high",     "code modulu -- dinamik code objeleri"),
}

_DANGEROUS_ATTRS = {
    "os.system":        ("command_inject",  "critical", "os.system() -- shell komutu calistirma"),
    "os.popen":         ("command_inject",  "critical", "os.popen() -- shell komutu calistirma"),
    "os.exec":          ("command_inject",  "critical", "os.exec*() -- proses degistirme"),
    "os.remove":        ("file_access",     "high",     "os.remove() -- dosya silme"),
    "os.unlink":        ("file_access",     "high",     "os.unlink() -- dosya silme"),
    "os.rmdir":         ("file_access",     "high",     "os.rmdir() -- klasor silme"),
    "os.makedirs":      ("file_access",     "medium",   "os.makedirs() -- klasor olusturma"),
    "os.environ":       ("info_leak",       "high",     "os.environ -- ortam degiskenleri erisimi"),
    "sys.exit":         ("system_access",   "medium",   "sys.exit() -- programi sonlandirma"),
    "sys._getframe":    ("sandbox_escape",  "high",     "sys._getframe() -- stack frame erisimi"),
}

_ALLOWED_IMPORTS = frozenset({
    "math", "random", "string", "collections", "itertools", "functools",
    "typing", "dataclasses", "enum", "abc", "copy", "operator",
    "heapq", "bisect", "statistics", "decimal", "fractions",
    "re", "json", "csv", "datetime", "time", "textwrap",
    "io", "sys",
})

# ═══════════════════════════════════════════════════════════════════════════════
# SQL INJECTION TESPITI
# ═══════════════════════════════════════════════════════════════════════════════

_SQL_PATTERNS = [
    (r'["\']SELECT\s+.*\+', "SQL string birlestirme ile SELECT sorgusu"),
    (r'["\']INSERT\s+.*\+', "SQL string birlestirme ile INSERT sorgusu"),
    (r'["\']UPDATE\s+.*\+', "SQL string birlestirme ile UPDATE sorgusu"),
    (r'["\']DELETE\s+.*\+', "SQL string birlestirme ile DELETE sorgusu"),
    (r'["\']DROP\s+',       "DROP komutu tespit edildi"),
    (r'f["\'].*SELECT.*\{', "f-string ile SQL sorgusu -- injection riski"),
    (r'f["\'].*INSERT.*\{', "f-string ile SQL sorgusu -- injection riski"),
    (r'f["\'].*UPDATE.*\{', "f-string ile SQL sorgusu -- injection riski"),
    (r'f["\'].*DELETE.*\{', "f-string ile SQL sorgusu -- injection riski"),
    (r'\.format\(.*SELECT',  "format() ile SQL sorgusu -- injection riski"),
    (r'%s.*SELECT|SELECT.*%s', "% formatlama ile SQL -- injection riski"),
    (r'cursor\.execute\(.+\+', "cursor.execute() ile string birlestirme"),
    (r'cursor\.execute\(f["\']', "cursor.execute() ile f-string -- injection riski"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# ANA AJAN
# ═══════════════════════════════════════════════════════════════════════════════


_SECURITY_SYSTEM_PROMPT = """\
You are an expert application security reviewer. The report must follow from your own analysis
of the code. Heuristic/AST lines in the user message are hints only.

Rules:
- Each threat: {"type": str, "severity": "low"|"medium"|"high"|"critical", "line": int|null, "description": str, "detail": str}
- risk_level: "safe"|"low"|"medium"|"high"|"critical"
- score: 0–100 (100 = safest).
- Do not over-penalize typical coursework (e.g. read-only file open, sys.exit) compared to real issues.
- Heavily penalize eval, exec, os.system, subprocess misuse, obvious injection vectors.

Reply with ONLY this JSON shape:
{
  "threats": [...],
  "risk_level": "safe|low|medium|high|critical",
  "safe": true|false,
  "total_threats": 0,
  "critical_count": 0,
  "high_count": 0,
  "blocked_imports": [],
  "score": 0-100
}
"""


def _risk_summary_from_threats(threats: list) -> dict:
    critical = sum(1 for t in threats if t.get("severity") == "critical")
    high = sum(1 for t in threats if t.get("severity") == "high")
    medium = sum(1 for t in threats if t.get("severity") == "medium")
    if critical > 0:
        risk_level = "critical"
    elif high > 0:
        risk_level = "high"
    elif medium > 0:
        risk_level = "medium"
    elif threats:
        risk_level = "low"
    else:
        risk_level = "safe"
    return {
        "risk_level": risk_level,
        "safe": risk_level in ("safe", "low"),
        "critical_count": critical,
        "high_count": high,
        "total_threats": len(threats),
    }


class SecurityAgent(BaseAgent):
    name = "security"
    description = "Guvenlik tehdidi tespiti ve kod guvenlik analizi"

    async def analyze(self, input_data: dict) -> dict:
        source_code = input_data["source_code"]
        language = input_data.get("language", "python")
        report_language = input_data.get("report_language") or "tr"

        programmatic = self._programmatic_analysis(source_code, language)

        truncated = self._truncate_code(source_code)
        summary = {
            "threat_count": len(programmatic["threats"]),
            "critical": programmatic.get("critical_count", 0),
            "high": programmatic.get("high_count", 0),
            "threats": [
                {"type": t["type"], "severity": t["severity"], "line": t.get("line"), "desc": t["description"][:80]}
                for t in programmatic["threats"][:5]
            ],
            "blocked": programmatic.get("blocked_imports", []),
        }
        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))
        user_prompt = (
            f"Code (language tag: {language}):\n```\n{truncated}\n```\n"
            f"{brief}"
            f"Non-binding heuristic hints (AST/regex):\n{json.dumps(summary, ensure_ascii=False, separators=(',',':'))}\n"
            "Task: Produce threats, risk_level, safe, counts, blocked_imports, and score from the code."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        llm_result = await self._call_llm(
            system_prompt=_SECURITY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            required_keys=["threats", "risk_level", "score"],
        )

        llm_th = llm_result.get("threats")
        if not isinstance(llm_th, list):
            llm_th = []
        llm_result["threats"] = llm_th
        rsum = _risk_summary_from_threats(llm_th)
        llm_result["risk_level"] = rsum["risk_level"]
        llm_result["safe"] = rsum["safe"]
        llm_result["critical_count"] = rsum["critical_count"]
        llm_result["high_count"] = rsum["high_count"]
        llm_result["total_threats"] = rsum["total_threats"]

        lbi = llm_result.get("blocked_imports")
        llm_result["blocked_imports"] = list(lbi) if isinstance(lbi, list) else []

        llm_result["score"] = self._safe_int(llm_result.get("score"), 50)

        return llm_result

    def _programmatic_analysis(self, source_code: str, language: str) -> dict:
        """AST/regex ozeti -- yalnizca LLM prompt ipucu."""
        threats: list[dict] = []
        blocked_imports: list[str] = []

        if language.lower() in ("python", "py"):
            threats.extend(_check_python_ast(source_code))
            threats.extend(_check_sql_patterns(source_code))
            threats.extend(_check_dangerous_patterns(source_code))
            blocked_imports = _get_blocked_imports(source_code)
        else:
            threats.extend(_check_generic_patterns(source_code, language))

        critical = sum(1 for t in threats if t["severity"] == "critical")
        high = sum(1 for t in threats if t["severity"] == "high")
        medium = sum(1 for t in threats if t["severity"] == "medium")

        if critical > 0:
            risk_level = "critical"
        elif high > 0:
            risk_level = "high"
        elif medium > 0:
            risk_level = "medium"
        elif threats:
            risk_level = "low"
        else:
            risk_level = "safe"

        score = 100
        score -= critical * 35
        score -= high * 22
        score -= medium * 8
        score -= sum(1 for t in threats if t.get("severity") == "low") * 3
        score = max(0, min(100, score))

        return {
            "threats": threats,
            "risk_level": risk_level,
            "safe": risk_level in ("safe", "low"),
            "total_threats": len(threats),
            "critical_count": critical,
            "high_count": high,
            "blocked_imports": blocked_imports,
            "score": score,
        }


def _check_python_ast(source_code: str) -> list[dict]:
    """AST tabanli tehdit tespiti."""
    threats = []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return threats

    for node in ast.walk(tree):
        # Tehlikeli fonksiyon cagrilari
        if isinstance(node, ast.Call):
            fname = ""
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    fname = f"{node.func.value.id}.{node.func.attr}"
                else:
                    fname = node.func.attr

            if fname in _DANGEROUS_FUNCTIONS:
                cat, sev, desc = _DANGEROUS_FUNCTIONS[fname]
                threats.append({
                    "type": cat,
                    "severity": sev,
                    "line": node.lineno,
                    "description": f"Satir {node.lineno}: {desc}",
                    "detail": f"{fname}() cagrilmis",
                })

            for full_attr, (cat, sev, desc) in _DANGEROUS_ATTRS.items():
                if fname == full_attr or fname.endswith("." + full_attr.split(".")[-1]):
                    threats.append({
                        "type": cat,
                        "severity": sev,
                        "line": node.lineno,
                        "description": f"Satir {node.lineno}: {desc}",
                        "detail": f"{fname}() cagrilmis",
                    })
                    break

            # open() ile dosya erisimi
            if fname == "open":
                mode = "r"
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)

                if any(m in mode for m in ("w", "a", "x")):
                    threats.append({
                        "type": "file_access",
                        "severity": "high",
                        "line": node.lineno,
                        "description": f"Satir {node.lineno}: open() yazma modunda -- dosya yazma erisimi",
                        "detail": f"open(..., '{mode}')",
                    })
                else:
                    threats.append({
                        "type": "file_access",
                        "severity": "medium",
                        "line": node.lineno,
                        "description": f"Satir {node.lineno}: open() -- dosya okuma erisimi",
                        "detail": "open() cagrilmis",
                    })

        # Tehlikeli import'lar
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in _DANGEROUS_IMPORTS:
                    cat, sev, desc = _DANGEROUS_IMPORTS[mod]
                    threats.append({
                        "type": cat,
                        "severity": sev,
                        "line": node.lineno,
                        "description": f"Satir {node.lineno}: import {alias.name} -- {desc}",
                        "detail": f"import {alias.name}",
                    })

        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _DANGEROUS_IMPORTS:
                cat, sev, desc = _DANGEROUS_IMPORTS[mod]
                names = ", ".join(a.name for a in node.names)
                threats.append({
                    "type": cat,
                    "severity": sev,
                    "line": node.lineno,
                    "description": f"Satir {node.lineno}: from {node.module} import {names} -- {desc}",
                    "detail": f"from {node.module} import {names}",
                })

        # __builtins__ erisimi
        if isinstance(node, ast.Attribute) and node.attr == "__builtins__":
            threats.append({
                "type": "sandbox_escape",
                "severity": "critical",
                "line": node.lineno,
                "description": f"Satir {node.lineno}: __builtins__ erisimi -- sandbox kacis girisimi",
                "detail": "__builtins__ kullanilmis",
            })

        # __subclasses__ erisimi
        if isinstance(node, ast.Attribute) and node.attr == "__subclasses__":
            threats.append({
                "type": "sandbox_escape",
                "severity": "critical",
                "line": node.lineno,
                "description": f"Satir {node.lineno}: __subclasses__() -- sinif hiyerarsisi uzerinden kacis",
                "detail": "__subclasses__ kullanilmis",
            })

    return threats


def _check_sql_patterns(source_code: str) -> list[dict]:
    """Regex ile SQL injection kaliplarini arar."""
    threats = []
    lines = source_code.splitlines()

    for i, line in enumerate(lines, 1):
        for pattern, desc in _SQL_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                threats.append({
                    "type": "sql_injection",
                    "severity": "critical",
                    "line": i,
                    "description": f"Satir {i}: {desc}",
                    "detail": line.strip()[:100],
                })
                break

    return threats


def _check_dangerous_patterns(source_code: str) -> list[dict]:
    """Regex ile ek tehlikeli kaliplari arar."""
    threats = []
    lines = source_code.splitlines()

    patterns = [
        # Kaynak kodda sabit credential = kritik (UI'da HATA); skor da dusuk olmali
        (r'password\s*=\s*["\'][^"\']+["\']', "info_leak", "critical",
         "Hardcoded password tespit edildi"),
        (r'api_key\s*=\s*["\'][^"\']+["\']', "info_leak", "critical",
         "Hardcoded API key tespit edildi"),
        (r'secret\s*=\s*["\'][^"\']+["\']', "info_leak", "critical",
         "Hardcoded secret tespit edildi"),
        (r'token\s*=\s*["\'][A-Za-z0-9+/=]{20,}["\']', "info_leak", "critical",
         "Hardcoded token tespit edildi"),
        (r'\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}', "obfuscation", "high",
         "Hex-encoded string -- kod gizleme girisimi"),
        (r'base64\.(b64decode|decodebytes)', "obfuscation", "medium",
         "base64 decode -- gizlenmis kod olabilir"),
        (r'chr\(\d+\)\s*\+\s*chr\(\d+\)', "obfuscation", "high",
         "chr() ile string olusturma -- kod gizleme girisimi"),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, cat, sev, desc in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                threats.append({
                    "type": cat,
                    "severity": sev,
                    "line": i,
                    "description": f"Satir {i}: {desc}",
                    "detail": line.strip()[:80],
                })

    return threats


def _check_generic_patterns(source_code: str, language: str) -> list[dict]:
    """C++/Java icin genel tehdit tespiti."""
    threats = []
    lines = source_code.splitlines()

    patterns = [
        (r'system\s*\(', "command_inject", "critical", "system() -- shell komutu"),
        (r'popen\s*\(', "command_inject", "critical", "popen() -- shell komutu"),
        (r'exec[lv]?p?\s*\(', "command_inject", "critical", "exec*() -- proses calistirma"),
        (r'strcpy\s*\(', "buffer_overflow", "high", "strcpy() -- buffer overflow riski"),
        (r'gets\s*\(', "buffer_overflow", "critical", "gets() -- buffer overflow"),
        (r'sprintf\s*\(', "buffer_overflow", "medium", "sprintf() -- buffer overflow riski"),
        (r'scanf\s*\(.*%s', "buffer_overflow", "high", "scanf(%s) -- buffer overflow"),
        (r'Runtime\.getRuntime\(\)\.exec', "command_inject", "critical", "Runtime.exec() -- komut calistirma"),
        (r'ProcessBuilder', "command_inject", "high", "ProcessBuilder -- proses olusturma"),
    ]

    for i, line in enumerate(lines, 1):
        for pattern, cat, sev, desc in patterns:
            if re.search(pattern, line):
                threats.append({
                    "type": cat,
                    "severity": sev,
                    "line": i,
                    "description": f"Satir {i}: {desc}",
                    "detail": line.strip()[:80],
                })

    return threats


def _get_blocked_imports(source_code: str) -> list[str]:
    """Izin verilmeyen import'larin listesini dondurur."""
    blocked = []
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return blocked

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod not in _ALLOWED_IMPORTS and mod in _DANGEROUS_IMPORTS:
                    blocked.append(alias.name)
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod not in _ALLOWED_IMPORTS and mod in _DANGEROUS_IMPORTS:
                blocked.append(f"from {node.module}")

    return blocked
