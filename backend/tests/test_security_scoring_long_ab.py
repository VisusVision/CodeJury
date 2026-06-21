"""
Security: tam LLM skoru vs eski harman (0.45*model + 0.55*kural) — genis A/B.

Tum samples/*.py + sentetik guvenli/guvensiz parcalar. Canli Ollama gerekir.

Calistirma (varsayilan pytest koleksiyonunda ATLANIR — ~11 dk):
  $env:AGENTGRADE_SECURITY_LONG_AB=1
  python -m pytest backend/tests/test_security_scoring_long_ab.py -v -s

  python scripts/security_scoring_long_ab.py
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx

from backend.agents.security import SecurityAgent
from backend.core.config import settings

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts" / "security_ab_long"

Tier = Literal["safe", "risky", "neutral"]


def _old_blend(model: int, rule: int) -> int:
    return max(0, min(100, round(0.45 * model + 0.55 * rule)))


def _read_sample(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# Odev kisa aciklamalari (calibration suite ile uyumlu)
_BRIEF_LIBRARY = (
    "Kitap, uye ve kutuphane siniflariyla OOP tabanli odunc alma-iade sistemi. "
    "Hata durumlari kontrollu ele alinmali."
)
_BRIEF_LOG = (
    "Log dosyasini okuyup seviye bazli ozet cikaracak CLI. "
    "Bozuk satirlari raporlayin, hata satirlarini ayri listede dondurun."
)
_BRIEF_REPORT = (
    "Ogrenci skorlarini alip gecme durumunu hesaplayan ve sonucu CSV rapor dosyasina "
    "yazan CLI. Cikti UTF-8, klasor yoksa olusturulmali."
)
_BRIEF_API = (
    "Ortam degiskeninden API_URL okuyan, verilen path icin HTTP durum kodu alan "
    "ve gecersiz konfigurasyonu anlasilir hatayla reddeden API istemcisi."
)
_BRIEF_DATA = (
    "SQLite tablosu, POST /clean ve PUT /beautify endpointleri. "
    "Hata durumlarinda uygun mesajlar ve log."
)
_BRIEF_BST = (
    "Ekleme, arama ve inorder/preorder/postorder dolasim destekleyen ikili arama agaci. "
    "Kose durumlari ele alinmali."
)
_BRIEF_GENERIC = "Python odev teslimi; guvenlik ve kod kalitesi degerlendirmesi."


@dataclass(frozen=True)
class SecurityAbCase:
    label: str
    tier: Tier
    brief: str
    language: str = "python"
    rel_path: str | None = None
    inline_code: str | None = None


FILE_CASES: list[SecurityAbCase] = [
    SecurityAbCase("FILE library_uygun", "safe", _BRIEF_LIBRARY, rel_path="samples/library_system_uygun.py"),
    SecurityAbCase("FILE library_alakasiz", "neutral", _BRIEF_LIBRARY, rel_path="samples/library_system_alakasiz.py"),
    SecurityAbCase("FILE log_uygun", "safe", _BRIEF_LOG, rel_path="samples/log_ozetleme_uygun.py"),
    SecurityAbCase("FILE log_guvensiz", "risky", _BRIEF_LOG, rel_path="samples/log_ozetleme_guvensiz.py"),
    SecurityAbCase("FILE log_alakasiz", "neutral", _BRIEF_LOG, rel_path="samples/log_ozetleme_alakasiz.py"),
    SecurityAbCase("FILE rapor_uygun", "safe", _BRIEF_REPORT, rel_path="samples/rapor_export_uygun.py"),
    SecurityAbCase("FILE rapor_guvensiz", "risky", _BRIEF_REPORT, rel_path="samples/rapor_export_guvensiz.py"),
    SecurityAbCase("FILE veri_uygun", "safe", _BRIEF_DATA, rel_path="samples/veri_guzellestirme_temizleme_uygun.py"),
    SecurityAbCase("FILE veri_alakasiz", "neutral", _BRIEF_DATA, rel_path="samples/veri_guzellestirme_temizleme_alakasiz.py"),
    SecurityAbCase("FILE api_uygun", "safe", _BRIEF_API, rel_path="samples/api_config_client_uygun.py"),
    SecurityAbCase("FILE api_alakasiz", "neutral", _BRIEF_API, rel_path="samples/api_config_client_alakasiz.py"),
    SecurityAbCase("FILE bst_uygun", "safe", _BRIEF_BST, rel_path="samples/ornek_odev_ikili_agac.py"),
    SecurityAbCase("FILE kitap_alakali", "safe", _BRIEF_LIBRARY, rel_path="samples/kitap_kutuphanesi_alakali.py"),
    SecurityAbCase("FILE kitap_alakasiz", "neutral", _BRIEF_LIBRARY, rel_path="samples/kitap_kutuphanesi_alakasiz.py"),
    SecurityAbCase("FILE yayinci_uyumlu", "safe", _BRIEF_GENERIC, rel_path="samples/kitap_yayincisi_uyumlu.py"),
    SecurityAbCase("FILE yayinci_uyumsuz", "neutral", _BRIEF_GENERIC, rel_path="samples/kitap_yayincisi_uyumsuz.py"),
    SecurityAbCase("FILE test1_temiz", "safe", _BRIEF_GENERIC, rel_path="samples/test1_temiz.py"),
    SecurityAbCase("FILE test2_sorunlu", "neutral", "Basit hesap makinesi CLI.", rel_path="samples/test2_sorunlu.py"),
    SecurityAbCase("FILE test3_runtime", "neutral", "Ortalama hesaplama; bos liste runtime hatasi.", rel_path="samples/test3_runtime.py"),
    SecurityAbCase("FILE demo_mixed", "risky", "JSON kategori ozeti; uretimde sır gizlenmeli.", rel_path="samples/demo_mixed_quality.py"),
    SecurityAbCase("FILE faktoriyel", "safe", "Faktoriyel hesaplama odevi.", rel_path="samples/faktoriyel_odev.py"),
]

INLINE_CASES: list[SecurityAbCase] = [
    # --- riskli sentetik ---
    SecurityAbCase(
        "SYN eval_filter",
        "risky",
        _BRIEF_LOG,
        inline_code='def f(line, expr):\n    return eval(expr, {}, {"line": line})\n',
    ),
    SecurityAbCase(
        "SYN exec_user",
        "risky",
        _BRIEF_GENERIC,
        inline_code='def run(cmd):\n    exec(cmd)\n',
    ),
    SecurityAbCase(
        "SYN os_system",
        "risky",
        _BRIEF_REPORT,
        inline_code='import os\ndef export(p, t):\n    os.system("echo "+t+" > "+p)\n',
    ),
    SecurityAbCase(
        "SYN subprocess_shell",
        "risky",
        _BRIEF_GENERIC,
        inline_code='import subprocess\ndef ping(host):\n    subprocess.call(f"ping -c 1 {host}", shell=True)\n',
    ),
    SecurityAbCase(
        "SYN pickle_loads",
        "risky",
        "Serilestirilmis veri yukleyici.",
        inline_code='import pickle\ndef load(b):\n    return pickle.loads(b)\n',
    ),
    SecurityAbCase(
        "SYN sql_fstring",
        "risky",
        _BRIEF_DATA,
        inline_code='def find_user(cur, uid):\n    cur.execute(f"SELECT * FROM users WHERE id={uid}")\n',
    ),
    SecurityAbCase(
        "SYN path_traversal",
        "risky",
        _BRIEF_REPORT,
        inline_code='def read_any(path):\n    return open(path).read()\n',
    ),
    SecurityAbCase(
        "SYN hardcoded_secret",
        "risky",
        _BRIEF_API,
        inline_code='API_KEY = "sk-live-abc123"\ndef headers():\n    return {"Authorization": API_KEY}\n',
    ),
    SecurityAbCase(
        "SYN verify_false",
        "risky",
        _BRIEF_API,
        inline_code='import requests\ndef get(url):\n    return requests.get(url, verify=False)\n',
    ),
    SecurityAbCase(
        "SYN yaml_unsafe",
        "risky",
        "YAML config yukleyici.",
        inline_code='import yaml\ndef load_cfg(s):\n    return yaml.load(s, Loader=yaml.Loader)\n',
    ),
    SecurityAbCase(
        "SYN bare_except_pass",
        "risky",
        _BRIEF_GENERIC,
        inline_code='def work():\n    try:\n        return 1/0\n    except:\n        pass\n',
    ),
    SecurityAbCase(
        "SYN md5_password",
        "risky",
        "Kullanici sifre hash.",
        inline_code='import hashlib\ndef hash_pw(p):\n    return hashlib.md5(p.encode()).hexdigest()\n',
    ),
    SecurityAbCase(
        "SYN shell_true_chain",
        "risky",
        _BRIEF_LOG,
        inline_code='import os\nuser = input("host: ")\nos.system("nslookup " + user)\n',
    ),
    SecurityAbCase(
        "SYN tempfile_race",
        "risky",
        _BRIEF_REPORT,
        inline_code='import tempfile\np = tempfile.mktemp()\nopen(p,"w").write("x")\n',
    ),
    # --- guvenli sentetik ---
    SecurityAbCase(
        "SYN clean_pathlib",
        "safe",
        _BRIEF_LOG,
        inline_code='from pathlib import Path\ndef read_log(p: Path) -> str:\n    return p.read_text(encoding="utf-8")\n',
    ),
    SecurityAbCase(
        "SYN clean_env",
        "safe",
        _BRIEF_API,
        inline_code='import os\ndef api_url():\n    return os.environ.get("API_URL", "")\n',
    ),
    SecurityAbCase(
        "SYN clean_sql_param",
        "safe",
        _BRIEF_DATA,
        inline_code='def find_user(cur, uid):\n    cur.execute("SELECT * FROM users WHERE id=?", (uid,))\n',
    ),
    SecurityAbCase(
        "SYN clean_bst",
        "safe",
        _BRIEF_BST,
        inline_code=(
            "class Node:\n    def __init__(self, v):\n        self.v, self.l, self.r = v, None, None\n"
            "def insert(r, v):\n    if r is None: return Node(v)\n    if v < r.v: r.l = insert(r.l, v)\n"
            "    else: r.r = insert(r.r, v)\n    return r\n"
        ),
    ),
    SecurityAbCase(
        "SYN clean_hello",
        "safe",
        _BRIEF_GENERIC,
        inline_code='def greet(name: str) -> str:\n    return f"Hello, {name}"\n',
    ),
    SecurityAbCase(
        "SYN clean_context",
        "safe",
        _BRIEF_REPORT,
        inline_code='from pathlib import Path\ndef write_csv(path: Path, rows):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    path.write_text("a\\n", encoding="utf-8")\n',
    ),
    SecurityAbCase(
        "SYN clean_hash_pbkdf2",
        "safe",
        "Sifre hash (guvenli yontem).",
        inline_code='import hashlib, os\ndef hash_pw(p, salt=None):\n    salt = salt or os.urandom(16)\n    return hashlib.pbkdf2_hmac("sha256", p.encode(), salt, 100_000)\n',
    ),
    SecurityAbCase(
        "SYN clean_subprocess_list",
        "safe",
        _BRIEF_GENERIC,
        inline_code='import subprocess\ndef list_dir():\n    return subprocess.run(["ls"], capture_output=True, text=True)\n',
    ),
]

# Ek matris: C++/Java, web/SSTI, zayif kripto, kenar durumlar
EXTENDED_CASES: list[SecurityAbCase] = [
    SecurityAbCase(
        "SYN compile_expr",
        "risky",
        _BRIEF_LOG,
        inline_code='def filt(expr, ctx):\n    return compile(expr, "<s>", "eval")\n',
    ),
    SecurityAbCase(
        "SYN dynamic_import",
        "risky",
        _BRIEF_GENERIC,
        inline_code='def load(mod):\n    return __import__(mod)\n',
    ),
    SecurityAbCase(
        "SYN ssti_jinja",
        "risky",
        "Flask sablon motoru odevi.",
        inline_code='from jinja2 import Template\ndef render(user):\n    return Template(user).render()\n',
    ),
    SecurityAbCase(
        "SYN flask_debug_on",
        "risky",
        "Flask REST API odevi.",
        inline_code='from flask import Flask\napp = Flask(__name__)\napp.run(debug=True)\n',
    ),
    SecurityAbCase(
        "SYN weak_token",
        "risky",
        _BRIEF_API,
        inline_code='import random\ndef token():\n    return str(random.randint(0, 999999))\n',
    ),
    SecurityAbCase(
        "SYN log_secret",
        "risky",
        _BRIEF_API,
        inline_code='import logging\ndef login(user, password):\n    logging.info("login %s pw=%s", user, password)\n',
    ),
    SecurityAbCase(
        "SYN tarfile_slip",
        "risky",
        _BRIEF_REPORT,
        inline_code='import tarfile\ndef extract(path):\n    tarfile.open(path).extractall("/tmp/out")\n',
    ),
    SecurityAbCase(
        "SYN marshal_loads",
        "risky",
        "Binary config yukleyici.",
        inline_code='import marshal\ndef load(b):\n    return marshal.loads(b)\n',
    ),
    SecurityAbCase(
        "SYN input_shell",
        "risky",
        _BRIEF_LOG,
        inline_code='import os\nhost = input("Host: ")\nos.popen("ping " + host)\n',
    ),
    SecurityAbCase(
        "SYN chmod_world",
        "risky",
        _BRIEF_REPORT,
        inline_code='import os\ndef publish(p):\n    os.chmod(p, 0o777)\n',
    ),
    SecurityAbCase(
        "SYN django_raw",
        "risky",
        _BRIEF_DATA,
        inline_code='def q(User, name):\n    return User.objects.extra(where=[f"name=\'{name}\'"])\n',
    ),
    SecurityAbCase(
        "SYN sha1_password",
        "risky",
        "Kullanici sifre hash.",
        inline_code='import hashlib\ndef hash_pw(p):\n    return hashlib.sha1(p.encode()).hexdigest()\n',
    ),
    SecurityAbCase(
        "SYN ssl_disabled",
        "risky",
        _BRIEF_API,
        inline_code='import ssl\nctx = ssl.create_default_context()\nctx.check_hostname = False\nctx.verify_mode = ssl.CERT_NONE\n',
    ),
    SecurityAbCase(
        "CPP system_inject",
        "risky",
        "C++ sistem komutu odevi.",
        language="cpp",
        inline_code='#include <cstdlib>\nint main() {\n    system("rm -rf /tmp/x");\n    return 0;\n}\n',
    ),
    SecurityAbCase(
        "CPP strcpy_buf",
        "risky",
        "C++ string isleme.",
        language="cpp",
        inline_code='#include <cstring>\nvoid copy(char *dst, const char *src) { strcpy(dst, src); }\n',
    ),
    SecurityAbCase(
        "JAVA runtime_exec",
        "risky",
        "Java process calistirma.",
        language="java",
        inline_code='class R {\n  void run(String c) throws Exception {\n    Runtime.getRuntime().exec(c);\n  }\n}\n',
    ),
    SecurityAbCase(
        "JAVA sql_concat",
        "risky",
        _BRIEF_DATA,
        language="java",
        inline_code='String q(String id) {\n  return "SELECT * FROM t WHERE id=" + id;\n}\n',
    ),
    SecurityAbCase(
        "SYN clean_secrets_vault",
        "safe",
        _BRIEF_API,
        inline_code='import os\ndef token():\n    return os.environ["API_TOKEN"]\n',
    ),
    SecurityAbCase(
        "SYN clean_requests_timeout",
        "safe",
        _BRIEF_API,
        inline_code='import requests\ndef get(url):\n    return requests.get(url, timeout=10, verify=True)\n',
    ),
    SecurityAbCase(
        "SYN clean_no_log_secret",
        "safe",
        _BRIEF_API,
        inline_code='import logging\ndef login(user):\n    logging.info("login attempt user=%s", user)\n',
    ),
    SecurityAbCase(
        "SYN clean_shutil_copy",
        "safe",
        _BRIEF_REPORT,
        inline_code='import shutil\nfrom pathlib import Path\ndef backup(src: Path, dst: Path):\n    shutil.copy2(src, dst)\n',
    ),
    SecurityAbCase(
        "SYN clean_bcrypt",
        "safe",
        "Sifre hash.",
        inline_code='import bcrypt\ndef hash_pw(p: bytes) -> bytes:\n    return bcrypt.hashpw(p, bcrypt.gensalt())\n',
    ),
    SecurityAbCase(
        "CPP safe_iostream",
        "safe",
        "C++ hello world.",
        language="cpp",
        inline_code='#include <iostream>\nint main() { std::cout << "hi"; return 0; }\n',
    ),
    SecurityAbCase(
        "JAVA prepared_stmt",
        "safe",
        _BRIEF_DATA,
        language="java",
        inline_code='// PreparedStatement with placeholder\nString sql = "SELECT * FROM users WHERE id=?";\n',
    ),
    SecurityAbCase(
        "SYN borderline_eval_comment",
        "neutral",
        _BRIEF_LOG,
        inline_code='# eval is dangerous; we use ast.literal_eval instead\nimport ast\ndef parse(s):\n    return ast.literal_eval(s)\n',
    ),
    SecurityAbCase(
        "SYN borderline_os_path",
        "neutral",
        _BRIEF_REPORT,
        inline_code='from pathlib import Path\ndef safe_name(name: str) -> Path:\n    return Path("out") / Path(name).name\n',
    ),
]

ALL_CASES = FILE_CASES + INLINE_CASES + EXTENDED_CASES


def _long_ab_enabled() -> bool:
    return os.environ.get("AGENTGRADE_SECURITY_LONG_AB", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


@dataclass
class SecurityAbRow:
    label: str
    tier: Tier
    new_score: int
    old_blend: int
    score_model: int
    score_rule: int
    delta_old_minus_new: int
    risk_level: str
    threat_count: int
    safe: bool


async def _ollama_reachable() -> bool:
    if not settings.ollama_enabled:
        return False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def run_security_long_ab(
    cases: list[SecurityAbCase] | None = None,
    *,
    retries: int = 3,
    pause_sec: float = 0.4,
) -> list[SecurityAbRow]:
    agent = SecurityAgent()
    cases = cases or ALL_CASES
    rows: list[SecurityAbRow] = []

    for case in cases:
        if case.rel_path:
            code = _read_sample(case.rel_path)
        else:
            code = case.inline_code or ""
        last_err: Exception | None = None
        result = None
        for attempt in range(retries):
            try:
                result = await agent.analyze({
                    "source_code": code,
                    "language": case.language,
                    "assignment_description": case.brief,
                    "report_language": "tr",
                })
                break
            except Exception as exc:
                last_err = exc
                await asyncio.sleep(1.5 * (attempt + 1))
        if result is None:
            raise RuntimeError(f"{case.label}: LLM basarisiz: {last_err}") from last_err

        model = int(result.get("score_model", 50))
        rule = int(result.get("score_rule", 50))
        new = int(result.get("score", 50))
        old = _old_blend(model, rule)
        rows.append(SecurityAbRow(
            label=case.label,
            tier=case.tier,
            new_score=new,
            old_blend=old,
            score_model=model,
            score_rule=rule,
            delta_old_minus_new=old - new,
            risk_level=str(result.get("risk_level", "")),
            threat_count=len(result.get("threats") or []),
            safe=bool(result.get("safe", True)),
        ))
        await asyncio.sleep(pause_sec)
    return rows


def _print_report(rows: list[SecurityAbRow]) -> None:
    print("\n" + "=" * 72, flush=True)
    print("SECURITY LONG A/B — tam LLM (NEW) vs eski harman (OLD)", flush=True)
    print("=" * 72, flush=True)
    for r in rows:
        mark = ""
        if r.tier == "risky" and r.new_score <= r.old_blend:
            mark = " [NEW daha iyi]"
        elif r.tier == "risky" and r.new_score > r.old_blend:
            mark = " [OLD yumuşatti]"
        elif r.tier == "safe" and r.new_score >= r.old_blend - 5:
            mark = " [OK]"
        print(
            f"  {r.label:28} tier={r.tier:7} NEW={r.new_score:3} OLD={r.old_blend:3} "
            f"model={r.score_model:3} rule={r.score_rule:3} d={r.delta_old_minus_new:+3} "
            f"risk={r.risk_level:8} thr={r.threat_count}{mark}",
            flush=True,
        )

    risky = [r for r in rows if r.tier == "risky"]
    safe = [r for r in rows if r.tier == "safe"]
    neutral = [r for r in rows if r.tier == "neutral"]

    def _pct(n: int, d: int) -> str:
        return f"{100 * n / d:.0f}%" if d else "n/a"

    risky_new_stricter = sum(1 for r in risky if r.new_score <= r.old_blend)
    risky_big_gap = sum(1 for r in risky if r.old_blend - r.new_score >= 10)
    safe_ok = sum(1 for r in safe if r.new_score >= r.old_blend - 8)

    print("-" * 72, flush=True)
    print(f"  Toplam vaka: {len(rows)} (risky={len(risky)}, safe={len(safe)}, neutral={len(neutral)})", flush=True)
    if risky:
        print(
            f"  Risky: NEW<=OLD {_pct(risky_new_stricter, len(risky))} "
            f"({risky_new_stricter}/{len(risky)}), gap>=10: {risky_big_gap}",
            flush=True,
        )
        print(
            f"  Risky medyan: NEW={statistics.median([r.new_score for r in risky]):.0f} "
            f"OLD={statistics.median([r.old_blend for r in risky]):.0f}",
            flush=True,
        )
    if safe:
        print(f"  Safe: NEW>=OLD-8 {_pct(safe_ok, len(safe))} ({safe_ok}/{len(safe)})", flush=True)
        print(
            f"  Safe medyan: NEW={statistics.median([r.new_score for r in safe]):.0f} "
            f"OLD={statistics.median([r.old_blend for r in safe]):.0f}",
            flush=True,
        )
    print("=" * 72 + "\n", flush=True)


def _write_artifact(rows: list[SecurityAbRow]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_DIR / "latest_report.json"
    payload = {
        "case_count": len(rows),
        "rows": [asdict(r) for r in rows],
        "summary": {
            "risky_new_stricter": sum(1 for r in rows if r.tier == "risky" and r.new_score <= r.old_blend),
            "risky_count": sum(1 for r in rows if r.tier == "risky"),
            "safe_ok": sum(1 for r in rows if r.tier == "safe" and r.new_score >= r.old_blend - 8),
            "safe_count": sum(1 for r in rows if r.tier == "safe"),
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def assert_long_ab_quality(rows: list[SecurityAbRow], *, min_cases: int = 55) -> None:
    risky = [r for r in rows if r.tier == "risky"]
    safe = [r for r in rows if r.tier == "safe"]
    assert len(rows) >= min_cases, f"Beklenen genis matris (>={min_cases}), got {len(rows)}"
    assert len(risky) >= 10, f"Yeterli risky vaka yok: {len(risky)}"

    stricter = sum(1 for r in risky if r.new_score <= r.old_blend)
    min_ratio = 0.70 if len(risky) >= 28 else 0.75
    assert stricter / len(risky) >= min_ratio, (
        f"Risky kodda NEW daha sert olmali (>={min_ratio:.0%}): {stricter}/{len(risky)}"
    )
    med_new = statistics.median([r.new_score for r in risky])
    med_old = statistics.median([r.old_blend for r in risky])
    assert med_new <= med_old, f"Risky medyan NEW ({med_new}) > OLD ({med_old})"

    total_lift = sum(max(0, r.old_blend - r.new_score) for r in risky)
    min_lift = 50 if len(risky) >= 28 else 40
    assert total_lift >= min_lift, f"Risky toplam skor dususu yetersiz: {total_lift}"

    if len(safe) >= 8:
        ok = sum(1 for r in safe if r.new_score >= r.old_blend - 8)
        assert ok / len(safe) >= 0.65, f"Safe kodda NEW cok dusmemeli: {ok}/{len(safe)}"


@unittest.skipUnless(
    _long_ab_enabled(),
    "Uzun canli A/B icin: $env:AGENTGRADE_SECURITY_LONG_AB=1 veya scripts/security_scoring_long_ab.py",
)
class SecurityLongAbTests(unittest.IsolatedAsyncioTestCase):
    """67 vaka: samples + sentetik + extended; canli LLM ile uzun A/B."""

    async def asyncSetUp(self):
        if not await _ollama_reachable():
            self.skipTest("Ollama erisilemiyor veya ollama_enabled=false")

    async def test_long_ab_extended_batch_llm_vs_blend(self):
        """Yeni eklenen vakalar (~24); tam kosudan once hizli dogrulama."""
        rows = await run_security_long_ab(EXTENDED_CASES, pause_sec=0.35)
        _print_report(rows)
        ext_path = ARTIFACT_DIR / "extended_report.json"
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ext_path.write_text(
            json.dumps({"case_count": len(rows), "rows": [asdict(r) for r in rows]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  Extended rapor: {ext_path}", flush=True)
        assert_long_ab_quality(rows, min_cases=20)

    async def test_long_ab_all_cases_llm_vs_blend(self):
        rows = await run_security_long_ab(ALL_CASES)
        _print_report(rows)
        path = _write_artifact(rows)
        print(f"  Rapor: {path}", flush=True)
        assert_long_ab_quality(rows)


if __name__ == "__main__":
    unittest.main()
