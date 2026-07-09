"""Re-run previously failing E2E soak scenarios (text_freq, api_client, data_clean_api)."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.e2e_coder_soak import (  # noqa: E402
    QA_DIR,
    SCENARIOS,
    _force_env,
    _init_sandbox_pool,
    _run_cycle,
)


FAILED_IDS = ("text_freq", "api_client", "data_clean_api")


async def main() -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", action="store_true")
    parser.add_argument("--only", nargs="*", default=list(FAILED_IDS))
    args = parser.parse_args()
    target_ids = tuple(args.only)

    _force_env()
    shutdown_pool = None
    if args.pool:
        _init_sandbox_pool(
            pool_size=int(os.getenv("SANDBOX_POOL_SIZE", "3")),
            base_port=int(os.getenv("SANDBOX_POOL_BASE_PORT", "8181")),
            timeout_s=float(os.getenv("SANDBOX_POOL_TIMEOUT", "30")),
        )
        from backend.sandbox.pool_manager import shutdown_pool as _shutdown_pool

        shutdown_pool = _shutdown_pool

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = QA_DIR / f"rerun_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    from backend.core.config import settings

    print(
        f"[rerun] failed scenarios via chatbot={settings.llm_general_provider} "
        f"nim={settings.nvidia_nim_general_model} coder={settings.ollama_coder_model}",
        flush=True,
    )

    results = []
    try:
        for idx, scenario in enumerate(
            [s for s in SCENARIOS if s.id in target_ids],
            start=1,
        ):
            result = await _run_cycle(idx, scenario)
            results.append(result)
            out = run_dir / f"cycle_{idx:02d}_{scenario.id}.json"
            out.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
            status = "PASS" if result.all_passed and not result.error else "FAIL"
            print(f"[rerun] {scenario.id} -> {status} t={result.elapsed_s}s", flush=True)

        summary = {
            "run_dir": str(run_dir),
            "passed": sum(1 for r in results if r.all_passed and not r.error),
            "failed": sum(1 for r in results if not r.all_passed or r.error),
            "results": [
                {
                    "scenario": r.scenario_id,
                    "passed": r.all_passed and not r.error,
                    "title": r.assignment_title,
                    "analysis": r.analysis,
                    "error": r.error,
                }
                for r in results
            ],
        }
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 0 if summary["failed"] == 0 else 1
    finally:
        if shutdown_pool is not None:
            shutdown_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
