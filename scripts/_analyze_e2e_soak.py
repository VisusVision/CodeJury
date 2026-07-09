"""Aggregate e2e faculty soak results from latest_summary.json or a run directory."""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "artifacts" / "qa" / "e2e_soak" / "latest_summary.json"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if path.is_dir():
        path = path / "soak_summary.json"
    if not path.exists():
        print(f"Not found: {path}", file=sys.stderr)
        raise SystemExit(1)

    summary = json.loads(path.read_text(encoding="utf-8"))
    run_dir = Path(summary.get("run_dir", path.parent))
    cycles: list[dict] = []
    for f in sorted(run_dir.glob("cycle_*.json")):
        cycles.append(json.loads(f.read_text(encoding="utf-8")))

    by_scenario: dict[str, list] = defaultdict(list)
    by_label: dict[str, list] = defaultdict(list)
    for c in cycles:
        for row in c.get("analysis", []):
            by_scenario[c["scenario_id"]].append(row)
            by_label[row["label"]].append(row)

    report = {
        "summary_path": str(path),
        "total_cycles": len(cycles),
        "passed_cycles": sum(1 for c in cycles if c.get("all_passed") and not c.get("error")),
        "error_cycles": sum(1 for c in cycles if c.get("error")),
        "avg_cycle_s": round(statistics.mean(c.get("elapsed_s", 0) for c in cycles), 1) if cycles else 0,
        "by_scenario": {},
        "by_label": {},
        "top_failures": summary.get("failures", [])[:20],
    }

    for sid, rows in sorted(by_scenario.items()):
        report["by_scenario"][sid] = {
            "n": len(rows),
            "pass_rate": round(sum(1 for r in rows if r.get("passed")) / len(rows), 2),
            "total_avg": round(statistics.mean(r["total"] for r in rows), 1),
        }

    for label, rows in sorted(by_label.items()):
        report["by_label"][label] = {
            "n": len(rows),
            "pass_rate": round(sum(1 for r in rows if r.get("passed")) / len(rows), 2),
            "total_min": min(r["total"] for r in rows),
            "total_max": max(r["total"] for r in rows),
            "total_avg": round(statistics.mean(r["total"] for r in rows), 1),
            "align_avg": round(statistics.mean(r["align"] for r in rows), 3),
        }

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
