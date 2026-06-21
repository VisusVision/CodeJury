"""
Security Agent -- LLM birincil; kritik/high tehditlerde kural tavanı (min).

AST/regex hem prompt ipucu hem birlesik tehdit listesine katilir. Skor once LLM'den gelir;
critical/high varsa score = min(llm_score, rule_score) — skoru yukari ceken harman yok.

Girdi:  {"source_code": str, "language": str}
Cikti:  {"threats": list, "risk_level": str, "safe": bool,
         "blocked_imports": list, "score": int, "score_model": int, "score_rule": int,
         "score_rule_capped": bool (opsiyonel)}
"""

import ast
import json
import re

from backend.agents.base import BaseAgent, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.json_output_schema import SECURITY_OUTPUT_SCHEMA

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

_SERVICE_HINT_TOKENS = (
    "api",
    "endpoint",
    "sunucu",
    "server",
    "http",
    "rest",
    "web",
    "istemci",
    "request",
)

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

        programmatic = self._programmatic_analysis(
            source_code,
            language,
            assignment_description=str(input_data.get("assignment_description") or ""),
        )

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
            required_keys=[
                "threats",
                "risk_level",
                "safe",
                "total_threats",
                "critical_count",
                "high_count",
                "blocked_imports",
                "score",
            ],
            output_json_schema=SECURITY_OUTPUT_SCHEMA,
        )

        llm_th = llm_result.get("threats")
        if not isinstance(llm_th, list):
            llm_th = []
        llm_th = self._calibrate_coursework_threats(
            llm_th,
            source_code=source_code,
            assignment_description=str(input_data.get("assignment_description") or ""),
        )
        merged_th = _merge_threat_lists(llm_th, programmatic["threats"])
        llm_result["threats"] = merged_th
        rsum = _risk_summary_from_threats(merged_th)
        llm_result["risk_level"] = rsum["risk_level"]
        llm_result["safe"] = rsum["safe"]
        llm_result["critical_count"] = rsum["critical_count"]
        llm_result["high_count"] = rsum["high_count"]
        llm_result["total_threats"] = rsum["total_threats"]

        lbi = llm_result.get("blocked_imports")
        prog_blocked = programmatic.get("blocked_imports") or []
        merged_blocked = list(dict.fromkeys(
            [x for x in (list(lbi) if isinstance(lbi, list) else []) + list(prog_blocked) if x]
        ))
        llm_result["blocked_imports"] = merged_blocked

        llm_score = self._safe_int(llm_result.get("score"), 50)
        rule_score = _score_from_threats(merged_th)
        final_score, capped = _final_security_score(llm_score, rule_score, merged_th)
        llm_result["score"] = final_score
        llm_result["score_model"] = max(0, min(100, llm_score))
        llm_result["score_rule"] = rule_score
        if capped:
            llm_result["score_rule_capped"] = True

        return llm_result

    @staticmethod
    def _calibrate_coursework_threats(
        threats: list,
        *,
        source_code: str,
        assignment_description: str,
    ) -> list[dict]:
        out: list[dict] = []
        brief_l = (assignment_description or "").lower()
        src_l = (source_code or "").lower()
        service_assignment = any(token in brief_l for token in _SERVICE_HINT_TOKENS)
        service_code = (
            "serve_forever" in src_l
            or "httpserver(" in src_l
            or "app.run(" in src_l
            or "uvicorn.run(" in src_l
        )
        api_context = service_assignment or service_code
        http_client_assignment = any(
            token in brief_l
            for token in (
                "istemci",
                "client",
                "api istemcisi",
                "http istek",
                "url",
                "durum kodu",
                "status code",
                "fetch",
            )
        )
        file_assignment = any(
            token in brief_l
            for token in (
                "dosya",
                "file",
                "log",
                "csv",
                "json",
                "path",
                "yol",
                "oku",
                "okuyup",
                "read",
                "cli",
                "arguman",
            )
        )
        config_assignment = any(
            token in brief_l
            for token in (
                "ortam degisken",
                "environment",
                "env",
                "konfigurasyon",
                "config",
                "api_url",
            )
        )
        file_output_assignment = file_assignment and any(
            token in brief_l
            for token in (
                "yaz",
                "yazan",
                "yazdir",
                "kaydet",
                "export",
                "disa aktar",
                "rapor dosyasi",
                "cikti dosyasi",
                "csv",
            )
        )
        destructive_or_execution = any(
            token in src_l
            for token in (
                "os.system",
                "os.popen",
                "subprocess",
                "eval(",
                "exec(",
                "os.remove",
                "os.unlink",
                "os.rmdir",
                "shutil.rmtree",
            )
        )
        has_specific_os_command_threat = any(
            isinstance(raw, dict)
            and (
                str(raw.get("type", "")).lower() == "command_inject"
                or "os.system" in str(raw.get("description", "")).lower()
                or "os.system" in str(raw.get("detail", "")).lower()
                or "os.popen" in str(raw.get("description", "")).lower()
                or "os.popen" in str(raw.get("detail", "")).lower()
            )
            for raw in threats
        )

        for raw in threats:
            if not isinstance(raw, dict):
                continue
            t = dict(raw)
            desc = str(t.get("description", "")).lower()
            detail = str(t.get("detail", "")).lower()
            t_type = str(t.get("type", "")).lower()
            sev = str(t.get("severity", "medium")).lower()

            if has_specific_os_command_threat and t_type == "system_access" and "import os" in detail:
                continue

            # Coursework API/server projects frequently and legitimately use HTTP modules.
            if api_context and t_type == "network_access":
                if "http" in desc or "http" in detail:
                    if sev == "high":
                        t["severity"] = "medium"
                    elif sev == "critical":
                        t["severity"] = "high"
                    t["description"] = str(t.get("description", "")) + " (odev baglaminda beklenen ag kullanimi olabilir)"

            if http_client_assignment and t_type == "network_access":
                if "requests" in detail or "urllib" in detail:
                    t["severity"] = "low"
                    t["description"] = str(t.get("description", "")) + " (odev baglaminda beklenen HTTP istemci kullanimi)"

            if file_assignment and not destructive_or_execution:
                if file_output_assignment and t_type == "file_access" and "open(..., 'w')" in detail:
                    t["severity"] = "low"
                    t["description"] = str(t.get("description", "")) + " (odev baglaminda beklenen dosya yazma/cikti uretimi)"
                if t_type == "file_access" and (
                    "open() -- dosya okuma" in desc
                    or "pathlib" in desc
                    or "read_text" in detail
                    or "open() cagrilmis" in detail
                ):
                    t["severity"] = "low"
                    t["description"] = str(t.get("description", "")) + " (odev baglaminda beklenen salt-okuma dosya islemi)"
                if t_type == "system_access" and "import os" in detail:
                    t["type"] = "file_path_access"
                    t["severity"] = "low"
                    t["description"] = str(t.get("description", "")) + " (odev baglaminda yol/dosya yardimcisi olabilir)"

            if config_assignment and not destructive_or_execution:
                if t_type in {"system_access", "info_leak"} and ("import os" in detail or "os.environ" in detail):
                    t["type"] = "configuration_access"
                    t["severity"] = "low"
                    t["description"] = str(t.get("description", "")) + " (odev baglaminda beklenen konfigurasyon/env okuma)"

            # Regex control-char cleanup is not code obfuscation.
            if t_type == "obfuscation":
                line_no = t.get("line")
                if isinstance(line_no, int) and line_no > 0:
                    lines = source_code.splitlines()
                    line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
                else:
                    line = ""
                line_l = line.lower()
                if "re.sub(" in line_l and "\\x" in line_l and "[" in line_l:
                    t["severity"] = "low"
                    t["description"] = "Regex kontrol karakter temizligi (obfuscation degil)"
                    t["type"] = "input_sanitization_pattern"

            out.append(t)
        return out

    def _programmatic_analysis(
        self,
        source_code: str,
        language: str,
        assignment_description: str = "",
    ) -> dict:
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

        threats = self._calibrate_coursework_threats(
            threats,
            source_code=source_code,
            assignment_description=assignment_description,
        )
        rsum = _risk_summary_from_threats(threats)
        score = _score_from_threats(threats)

        return {
            "threats": threats,
            "risk_level": rsum["risk_level"],
            "safe": rsum["safe"],
            "total_threats": rsum["total_threats"],
            "critical_count": rsum["critical_count"],
            "high_count": rsum["high_count"],
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
                if fname == "getattr" and _is_constant_safe_getattr(node):
                    sev = "low"
                    desc = "getattr() sabit ve guvenli alan adi ile kullanilmis"
                    cat = "dynamic_attribute_access"
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


def _is_constant_safe_getattr(node: ast.Call) -> bool:
    """Benign model/DTO alan okuma ile sandbox kacak girisimini ayir."""
    if len(node.args) < 2:
        return False
    attr_arg = node.args[1]
    if not isinstance(attr_arg, ast.Constant) or not isinstance(attr_arg.value, str):
        return False
    attr_name = attr_arg.value.strip()
    if not attr_name:
        return False
    if attr_name.startswith("__") or attr_name.endswith("__"):
        return False
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", attr_name))


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
        (r'hashlib\.(md5|sha1)\s*\(', "weak_crypto", "high",
         "MD5/SHA1 sifre hash -- zayif kriptografi"),
        (r'\.run\s*\(\s*[^)]*debug\s*=\s*True', "debug_enabled", "high",
         "debug=True -- bilgi sizintisi riski"),
        (r'debug\s*=\s*True', "debug_enabled", "high",
         "debug=True -- bilgi sizintisi riski"),
        (r'random\.(random|randint|choice)\s*\(', "weak_random", "medium",
         "random modulu guvenlik tokeni icin uygun degil"),
        (r'\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}', "obfuscation", "high",
         "Hex-encoded string -- kod gizleme girisimi"),
        (r'base64\.(b64decode|decodebytes)', "obfuscation", "medium",
         "base64 decode -- gizlenmis kod olabilir"),
        (r'chr\(\d+\)\s*\+\s*chr\(\d+\)', "obfuscation", "high",
         "chr() ile string olusturma -- kod gizleme girisimi"),
    ]

    for i, line in enumerate(lines, 1):
        line_l = line.lower()
        # Common sanitation pattern in student assignments; not obfuscation.
        if "re.sub(" in line_l and "\\x" in line_l and "[" in line_l:
            pass
        for pattern, cat, sev, desc in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                if cat == "obfuscation" and "re.sub(" in line_l and "\\x" in line_l and "[" in line_l:
                    continue
                threats.append({
                    "type": cat,
                    "severity": sev,
                    "line": i,
                    "description": f"Satir {i}: {desc}",
                    "detail": line.strip()[:80],
                })

    return threats


def _merge_threat_lists(*threat_lists: list) -> list[dict]:
    """LLM + AST tehditlerini satir/tip bazinda birlestir."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for threats in threat_lists:
        if not isinstance(threats, list):
            continue
        for raw in threats:
            if not isinstance(raw, dict):
                continue
            t = dict(raw)
            key = (
                t.get("line"),
                str(t.get("type", "")).lower(),
                str(t.get("description", ""))[:72],
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(t)
    return out


def _has_severe_threats(threats: list[dict]) -> bool:
    for t in threats:
        if not isinstance(t, dict):
            continue
        if str(t.get("severity", "")).lower() in ("critical", "high"):
            return True
    return False


def _final_security_score(
    llm_score: int,
    rule_score: int,
    threats: list[dict],
) -> tuple[int, bool]:
    """
    Birincil skor LLM. critical/high tehdit varsa skoru yukari cekmeyen tavan: min(llm, rule).
    """
    llm_score = max(0, min(100, int(llm_score)))
    rule_score = max(0, min(100, int(rule_score)))
    if _has_severe_threats(threats):
        final = min(llm_score, rule_score)
        return final, final < llm_score
    return llm_score, False


def _score_from_threats(threats: list[dict]) -> int:
    score = 100
    for t in threats:
        sev = str(t.get("severity", "")).lower()
        if sev == "critical":
            score -= 30
        elif sev == "high":
            score -= 16
        elif sev == "medium":
            score -= 7
        elif sev == "low":
            score -= 2
    return max(0, min(100, int(round(score))))


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
