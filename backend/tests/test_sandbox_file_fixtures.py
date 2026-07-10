"""Sandbox fixture injection for file-based assignments."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.sandbox.errors import SandboxUnavailableError
from backend.sandbox.executor import _simulate_sandbox, run_in_sandbox
from backend.sandbox.fixtures import infer_sandbox_files


_CSV_CODE = '''
from pathlib import Path
import csv

def main():
    path = Path("scores.csv")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    print(f"rows={len(rows)}")

if __name__ == "__main__":
    main()
'''


_TXT_CODE = '''
from pathlib import Path

def main():
    text = Path("sayilar.txt").read_text(encoding="utf-8")
    print(text.splitlines()[0])

if __name__ == "__main__":
    main()
'''


class InferSandboxFilesTests(unittest.TestCase):
    def test_detects_scores_csv_from_path(self):
        files = infer_sandbox_files(assignment_brief="CSV odev", source_code=_CSV_CODE)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "scores.csv")
        self.assertIn("name,score", files[0]["content"])

    def test_detects_txt_input_from_assignment_and_source(self):
        files = infer_sandbox_files(
            assignment_brief="sayilar.txt dosyasini okuyup sonuc.txt dosyasina rapor yazin",
            source_code=_TXT_CODE,
        )
        names = [item["name"] for item in files]
        self.assertIn("sayilar.txt", names)
        self.assertNotIn("sonuc.txt", names)
        content = next(item["content"] for item in files if item["name"] == "sayilar.txt")
        self.assertIn("abc", content)
        self.assertIn("-3", content)

    def test_returns_empty_when_no_file_paths(self):
        code = "print('hello')\n"
        self.assertEqual(infer_sandbox_files(assignment_brief="", source_code=code), [])

    def test_skips_write_only_csv_outputs(self):
        code = '''
from pathlib import Path
import csv

def main():
    out = Path("report.csv")
    with out.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(["a"])
'''
        self.assertEqual(infer_sandbox_files(assignment_brief="", source_code=code), [])

    def test_skips_write_only_txt_outputs(self):
        code = '''
from pathlib import Path

def main():
    Path("sonuc.txt").write_text("rapor", encoding="utf-8")
'''
        self.assertEqual(
            infer_sandbox_files(
                assignment_brief="sayilar.txt okuyup sonuc.txt yazin",
                source_code=code,
            ),
            [],
        )

    def test_skips_output_named_txt_constants(self):
        code = '''
from pathlib import Path

GIRIS_DOSYASI = "sayilar.txt"
CIKIS_DOSYASI = "sonuc.txt"

def main():
    metin = Path(GIRIS_DOSYASI).read_text(encoding="utf-8")
    Path(CIKIS_DOSYASI).write_text(metin, encoding="utf-8")
'''
        files = infer_sandbox_files(
            assignment_brief="sayilar.txt okuyup sonuc.txt dosyasina yazin",
            source_code=code,
        )
        self.assertEqual([item["name"] for item in files], ["sayilar.txt"])


class SimulateSandboxFilesTests(unittest.TestCase):
    def test_simulate_writes_fixture_before_run(self):
        files = infer_sandbox_files(assignment_brief="", source_code=_CSV_CODE)
        result = _simulate_sandbox(_CSV_CODE, files=files)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("rows=2", result["stdout"])

    def test_simulate_writes_txt_fixture_before_run(self):
        files = infer_sandbox_files(
            assignment_brief="sayilar.txt dosyasini okuyun",
            source_code=_TXT_CODE,
        )
        result = _simulate_sandbox(_TXT_CODE, files=files)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("10", result["stdout"])

    def test_simulate_without_fixtures_fails_for_missing_csv(self):
        result = _simulate_sandbox(_CSV_CODE, files=[])
        self.assertNotEqual(result["exit_code"], 0)


class RunInSandboxPayloadTests(unittest.TestCase):
    def test_run_in_sandbox_raises_when_pool_unavailable(self):
        files = infer_sandbox_files(assignment_brief="", source_code=_CSV_CODE)
        with patch("backend.sandbox.pool_manager.wait_for_pool_ready", return_value=None):
            with self.assertRaises(SandboxUnavailableError):
                run_in_sandbox(_CSV_CODE, "python", files=files)


if __name__ == "__main__":
    unittest.main()
