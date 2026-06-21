"""Programmatic before/after comparison for P0 sandbox fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.sandbox.executor import _simulate_sandbox, run_in_sandbox
from backend.sandbox.fixtures import infer_sandbox_files

OUT = ROOT / "artifacts" / "qa" / "after"

CODE_NO_SELF_SEED = '''
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = infer_sandbox_files(assignment_brief="", source_code=CODE_NO_SELF_SEED)
    sim_without = _simulate_sandbox(CODE_NO_SELF_SEED, files=[])
    sim_with = _simulate_sandbox(CODE_NO_SELF_SEED, files=files)
    pool_result = run_in_sandbox(CODE_NO_SELF_SEED, "python", files=files)

    report = {
        "simulate_without_fixtures": {
            "exit_code": sim_without.get("exit_code"),
            "stderr_preview": str(sim_without.get("stderr", ""))[:200],
        },
        "simulate_with_fixtures": {
            "exit_code": sim_with.get("exit_code"),
            "stdout": sim_with.get("stdout"),
        },
        "pool_with_fixtures": {
            "exit_code": pool_result.get("exit_code"),
            "stdout": pool_result.get("stdout"),
            "fixtures_provided": pool_result.get("fixtures_provided"),
        },
        "inferred_files": files,
    }
    (OUT / "sandbox_fixture_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
