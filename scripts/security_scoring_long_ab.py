#!/usr/bin/env python3
"""Security tam-LLM vs eski harman — uzun A/B (CLI).

  python scripts/security_scoring_long_ab.py           # tum vakalar (~67)
  python scripts/security_scoring_long_ab.py --extended  # sadece yeni batch (~24)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tests.test_security_scoring_long_ab import (  # noqa: E402
    ALL_CASES,
    ARTIFACT_DIR,
    EXTENDED_CASES,
    _ollama_reachable,
    assert_long_ab_quality,
    run_security_long_ab,
    _print_report,
    _write_artifact,
)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extended", action="store_true", help="Sadece extended vakalar")
    args = parser.parse_args()

    if not await _ollama_reachable():
        print("HATA: Ollama kapali veya erisilemiyor.", file=sys.stderr)
        return 2

    cases = EXTENDED_CASES if args.extended else ALL_CASES
    print(f"Calistiriliyor: {len(cases)} vaka...", flush=True)
    rows = await run_security_long_ab(cases, pause_sec=0.35)
    _print_report(rows)
    if args.extended:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        path = ARTIFACT_DIR / "extended_report.json"
        path.write_text(
            json.dumps({"case_count": len(rows), "rows": [asdict(r) for r in rows]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        min_cases = 20
    else:
        path = _write_artifact(rows)
        min_cases = 55
    print(f"JSON: {path}", flush=True)
    try:
        assert_long_ab_quality(rows, min_cases=min_cases)
    except AssertionError as e:
        print(f"BASARISIZ: {e}", file=sys.stderr)
        return 1
    print("BASARILI: tam LLM skoru risky kodda tutarli sekilde daha sert.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
