"""Docker sandbox pool smoke: init pool, run one execute, shutdown."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_pool_smoke(
    *,
    pool_size: int = 2,
    base_port: int = 8181,
    timeout_s: float = 60.0,
) -> int:
    from backend.ops.runtime_diagnostics import try_initialize_sandbox_pool
    from backend.sandbox.executor import run_in_sandbox
    from backend.sandbox.pool_manager import shutdown_pool

    mode = try_initialize_sandbox_pool(
        pool_size=pool_size,
        base_port=base_port,
        timeout_s=timeout_s,
    )
    try:
        if mode != "pool":
            print("[pool-smoke] sandbox pool unavailable", flush=True)
            return 1

        result = run_in_sandbox("print('pool-smoke-ok')\n", "python")
        stdout = str(result.get("stdout") or "")
        backend = str(result.get("execution_backend") or "")

        if "pool-smoke-ok" not in stdout:
            print(f"[pool-smoke] unexpected stdout: {stdout!r}", flush=True)
            return 1
        if backend != "pool":
            print(f"[pool-smoke] expected execution_backend=pool, got {backend!r}", flush=True)
            return 1

        print("[pool-smoke] PASS", flush=True)
        return 0
    finally:
        shutdown_pool()


def main() -> int:
    return run_pool_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
