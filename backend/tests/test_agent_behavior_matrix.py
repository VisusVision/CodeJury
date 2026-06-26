import unittest

from backend.agents.security import SecurityAgent
from backend.agents.task_relevance import _capability_match_signal


class TaskCapabilityMatrixTests(unittest.TestCase):
    def test_representative_assignment_shapes_match_expected_code(self):
        cases = [
            (
                "cli_log",
                "Python ile log dosyasi okuyup CLI ozet araci yazin.",
                "import argparse\nfrom pathlib import Path\nPath('x').read_text().splitlines()\n",
                0.75,
            ),
            (
                "api_sqlite",
                "FastAPI ile SQLite ogrenci kayit API endpointleri yazin.",
                "from fastapi import FastAPI\nimport sqlite3\napp=FastAPI()\n@app.post('/students')\ndef create(): sqlite3.connect('x.db')\n",
                0.75,
            ),
            (
                "oop_library",
                "Kitap uye kutuphane siniflariyla OOP odunc alma iade sistemi yazin.",
                "class Kitap: pass\nclass Uye: pass\nclass Kutuphane:\n    def odunc_al(self): pass\n",
                0.75,
            ),
            (
                "bst",
                "BST agac node ekleme arama inorder traversal yazin.",
                "class Node:\n    def __init__(self): self.left=None; self.right=None\ndef inorder(root): inorder(root.left); inorder(root.right)\n",
                0.45,
            ),
            (
                "react",
                "React todo uygulamasi useState form filtreleme yazin.",
                "import React,{useState} from 'react'; export function App(){ const [items,setItems]=useState([]); return <form></form> }",
                0.75,
            ),
            (
                "html_css",
                "HTML CSS responsive portfolio sayfasi header section media query yazin.",
                "<!doctype html><html><style>@media(max-width:600px){.x{display:grid}}</style><body><header></header><section></section></body></html>",
                0.75,
            ),
            (
                "cpp_vector",
                "C++ vector sort min max fonksiyonlari yazin.",
                "#include <vector>\n#include <algorithm>\nvoid f(){std::vector<int> v; std::sort(v.begin(), v.end());}\n",
                0.75,
            ),
            (
                "pytest",
                "pytest ile hesap makinesi fonksiyonlari icin unit test yazin.",
                "import pytest\ndef test_add(): assert add(1,2)==3\n",
                0.75,
            ),
        ]

        unrelated = "def fibonacci(n):\n    return n if n < 2 else fibonacci(n - 1) + fibonacci(n - 2)\n"
        for label, brief, matching_code, minimum in cases:
            with self.subTest(label=label):
                self.assertGreaterEqual(_capability_match_signal(brief, None, matching_code), minimum)
                self.assertLess(_capability_match_signal(brief, None, unrelated), 0.25)

    def test_topic_relevance_separates_off_topic_partial_and_matching_submissions(self):
        cases = [
            (
                "number_file_analysis",
                "Sayilar.txt dosyasindan sayilari okuyun, tek sayilari filtreleyin, ortalama ve medyan hesaplayin.",
                "from pathlib import Path\nnums=[int(x) for x in Path('sayilar.txt').read_text().splitlines()]\nprint(sum(nums)/len(nums))\n",
                "playlist=[]\nplaylist.append({'song':'A','artist':'B'})\nprint(playlist)\n",
                0.70,
                0.30,
            ),
            (
                "api_client",
                "API_URL ortam degiskeninden okunan HTTP API istemcisi yazin; durum kodunu yazdirsin.",
                "import os, urllib.request\nurl=os.environ.get('API_URL')\nprint(urllib.request.urlopen(url, timeout=5).status)\n",
                "def fibonacci(n): return n if n < 2 else fibonacci(n-1)+fibonacci(n-2)\n",
                0.70,
                0.30,
            ),
            (
                "oop_library",
                "Kitap, uye ve kutuphane siniflariyla odunc alma iade sistemi yazin.",
                "class Kitap: pass\nclass Uye: pass\nclass Kutuphane:\n    def odunc_al(self): pass\n",
                "print('hava durumu raporu')\n",
                0.70,
                0.30,
            ),
        ]

        for label, brief, matching, off_topic, min_match, max_off in cases:
            with self.subTest(label=label):
                self.assertGreaterEqual(_capability_match_signal(brief, None, matching), min_match)
                self.assertLess(_capability_match_signal(brief, None, off_topic), max_off)


class SunumDemoRelevanceTests(unittest.TestCase):
    def test_sayilar_brief_matches_analysis_code_not_playlist(self):
        from pathlib import Path

        from backend.agents.assignment_alignment import compute_brief_code_alignment
        from backend.agents.task_relevance import (
            deterministic_task_capability_match,
            obvious_cross_domain_mismatch,
        )

        root = Path(__file__).resolve().parents[2] / "sunum_demo_kodlari"
        brief = (
            "Sayilar.txt dosyasindan sayilari okuyun. Tek sayilari filtreleyin. "
            "Ortalama ve medyan hesaplayin. Sonucu sonuc.txt dosyasina raporlayin."
        )
        uygun = (root / "01_uygun_sayilar_analizi.py").read_text(encoding="utf-8")
        alakasiz = (root / "02_alakasiz_playlist.py").read_text(encoding="utf-8")

        self.assertTrue(obvious_cross_domain_mismatch(brief, alakasiz))
        self.assertFalse(obvious_cross_domain_mismatch(brief, uygun))
        self.assertGreaterEqual(deterministic_task_capability_match(brief, None, uygun), 0.70)
        self.assertLess(deterministic_task_capability_match(brief, None, alakasiz), 0.45)

        uygun_align, uygun_rs = compute_brief_code_alignment(brief, uygun)
        alak_align, alak_rs = compute_brief_code_alignment(brief, alakasiz)
        self.assertGreaterEqual(uygun_align, 0.90)
        self.assertLess(alak_align, 0.30)
        self.assertIn("cross_domain_mismatch", alak_rs)


class SecurityCourseworkMatrixTests(unittest.TestCase):
    def test_expected_coursework_io_and_network_are_low_risk(self):
        agent = SecurityAgent()
        cases = [
            (
                "sqlite",
                "import sqlite3\nconn=sqlite3.connect('students.db')\n",
                "SQLite ogrenci kayit uygulamasi yazin.",
            ),
            (
                "http_client",
                "import requests\ndef fetch(url): return requests.get(url, timeout=5).status_code\n",
                "HTTP API istemcisi yazin; verilen URL icin durum kodu dondursun.",
            ),
            (
                "env_config",
                "import os\nAPI_URL = os.environ.get('API_URL')\n",
                "Ortam degiskeninden API_URL okuyan konfigurasyon araci yazin.",
            ),
            (
                "file_export",
                "def save_report(path, text):\n    open(path, 'w', encoding='utf-8').write(text)\n",
                "Rapor dosyasi yazan CLI araci gelistirin.",
            ),
        ]

        for label, code, brief in cases:
            with self.subTest(label=label):
                result = agent._programmatic_analysis(code, "python", assignment_description=brief)
                self.assertTrue(result["safe"])
                self.assertIn(result["risk_level"], {"safe", "low"})
                self.assertGreaterEqual(result["score"], 90)

    def test_clearly_dangerous_patterns_stay_high_risk(self):
        agent = SecurityAgent()
        cases = [
            (
                "command_execution",
                "import os\ndef run(path): os.system('cat ' + path)\n",
                "Dosya yolu alan CLI araci yazin.",
                "critical",
            ),
            (
                "sql_concat",
                "import sqlite3\ndef f(name):\n    c=sqlite3.connect('x').cursor(); c.execute('SELECT * FROM students WHERE name=' + name)\n",
                "SQLite ogrenci kayit uygulamasi yazin.",
                "critical",
            ),
            (
                "pickle_loads",
                "import pickle\ndef load(data): return pickle.loads(data)\n",
                "Dosya okuma uygulamasi yazin.",
                "high",
            ),
        ]

        for label, code, brief, expected in cases:
            with self.subTest(label=label):
                result = agent._programmatic_analysis(code, "python", assignment_description=brief)
                self.assertFalse(result["safe"])
                self.assertEqual(result["risk_level"], expected)


if __name__ == "__main__":
    unittest.main()
