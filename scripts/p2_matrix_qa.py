"""P2 production-readiness matrix — programmatic calibration across sample scenarios."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_calibration_suite import REPORT_PATH, run_programmatic_suite

P2_REPORT = ROOT / "artifacts" / "qa" / "p2_matrix_summary.json"


async def main() -> int:
    report = await run_programmatic_suite(checkpoint_path=REPORT_PATH)
    P2_REPORT.parent.mkdir(parents=True, exist_ok=True)
    P2_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report.get("summary", {})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"P2 matrix report: {P2_REPORT}")
    passed = int(summary.get("passed_cases", 0))
    total = int(summary.get("total_cases", 0))
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
