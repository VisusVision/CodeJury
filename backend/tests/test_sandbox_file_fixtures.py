"""Sandbox fixture injection for file-based assignments."""

from __future__ import annotations

import unittest

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


class InferSandboxFilesTests(unittest.TestCase):
    def test_detects_scores_csv_from_path(self):
        files = infer_sandbox_files(assignment_brief="CSV odev", source_code=_CSV_CODE)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "scores.csv")
        self.assertIn("name,score", files[0]["content"])

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


class SimulateSandboxFilesTests(unittest.TestCase):
    def test_simulate_writes_fixture_before_run(self):
        files = infer_sandbox_files(assignment_brief="", source_code=_CSV_CODE)
        result = _simulate_sandbox(_CSV_CODE, files=files)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("rows=2", result["stdout"])

    def test_simulate_without_fixtures_fails_for_missing_csv(self):
        result = _simulate_sandbox(_CSV_CODE, files=[])
        self.assertNotEqual(result["exit_code"], 0)


class RunInSandboxPayloadTests(unittest.TestCase):
    def test_run_in_sandbox_accepts_files_kwarg(self):
        files = infer_sandbox_files(assignment_brief="", source_code=_CSV_CODE)
        result = run_in_sandbox(_CSV_CODE, "python", files=files)
        self.assertIn("exit_code", result)


if __name__ == "__main__":
    unittest.main()
