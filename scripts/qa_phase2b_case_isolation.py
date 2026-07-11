"""Phase 2B case isolation smoke against the real sandbox pool."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASE_CODE = '''
import sys
from pathlib import Path

mode = sys.stdin.read().strip()
path = Path("state.txt")
if mode == "mutate":
    path.write_text(path.read_text(encoding="utf-8") + "mutated\\n", encoding="utf-8")
    print("case-one")
else:
    print(path.read_text(encoding="utf-8").strip())
'''

MISMATCH_CODE = "print('wrong')\n"

ZERO_DIV_CODE = "a=int(input())\nb=int(input())\nprint(a//b)\n"

TIMEOUT_CODE = "while True:\n    pass\n"


def _running_compose_services() -> set[str]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _start_compose_services(services: list[str]) -> None:
    if not services:
        return
    subprocess.run(["docker", "compose", "up", "-d", *services], cwd=ROOT, check=True)


def _stop_compose_services(services: list[str]) -> None:
    if not services:
        return
    subprocess.run(["docker", "compose", "stop", *services], cwd=ROOT, check=False)


def _task_containers(owner_id: str) -> list[str]:
    result = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=agentgrade.pool_owner={owner_id}",
            "--format",
            "{{.ID}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _assert_case(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed{': ' + detail if detail else ''}")


def _run_smoke(*, manage_services: bool) -> int:
    from backend.sandbox.executor import run_in_sandbox
    from backend.sandbox.pool_manager import initialize_pool, shutdown_pool

    owner_id = f"qa-phase2b-case-{uuid.uuid4()}"
    os.environ["SANDBOX_POOL_OWNER"] = owner_id
    os.environ.setdefault("SANDBOX_IMAGE", "agentgrade-sandbox:phase2b")
    os.environ.setdefault("SANDBOX_POOL_SIZE", "1")
    os.environ.setdefault("SANDBOX_POOL_BASE_PORT", "8281")

    started_by_script: list[str] = []
    if manage_services:
        already_running = _running_compose_services()
        to_start = [svc for svc in ("docker",) if svc not in already_running]
        # Docker engine itself is required; compose file has no separate sandbox service.
        if to_start:
            started_by_script = to_start

    pool = None
    try:
        pool = initialize_pool()
        if pool is None or not pool.wait_until_ready(60.0):
            raise RuntimeError("sandbox pool did not become ready")

        isolation = run_in_sandbox(
            CASE_CODE,
            "python",
            test_cases=[
                {
                    "id": "case-1",
                    "name": "mutate fixture",
                    "stdin": "mutate\n",
                    "expected_stdout": "case-one\n",
                    "files": [{"name": "state.txt", "content": "seed\n"}],
                    "source": "manual",
                    "oracle": "teacher",
                },
                {
                    "id": "case-2",
                    "name": "read untouched fixture",
                    "stdin": "read\n",
                    "expected_stdout": "seed\n",
                    "files": [{"name": "state.txt", "content": "seed\n"}],
                    "source": "manual",
                    "oracle": "teacher",
                },
            ],
        )
        iso_cases = {row["id"]: row for row in isolation.get("test_results", [])}
        _assert_case(
            "fixture isolation",
            iso_cases.get("case-1", {}).get("passed") is True
            and iso_cases.get("case-2", {}).get("passed") is True,
            str(iso_cases),
        )

        mismatch = run_in_sandbox(
            MISMATCH_CODE,
            "python",
            test_cases=[
                {
                    "id": "mismatch",
                    "name": "mismatch",
                    "stdin": "",
                    "expected_stdout": "expected-only\n",
                    "source": "manual",
                    "oracle": "teacher",
                }
            ],
        )
        mismatch_case = mismatch["test_results"][0]
        _assert_case(
            "output mismatch",
            mismatch_case.get("passed") is False and mismatch_case.get("status") == "fail",
            str(mismatch_case),
        )

        zero_div = run_in_sandbox(
            ZERO_DIV_CODE,
            "python",
            test_cases=[
                {
                    "id": "zero-div",
                    "name": "zero division",
                    "stdin": "10\n0\n",
                    "expected_stdout": "ok\n",
                    "source": "manual",
                    "oracle": "teacher",
                }
            ],
        )
        zero_case = zero_div["test_results"][0]
        _assert_case(
            "zero division",
            zero_case.get("status") == "error" and zero_case.get("error_type") == "ZeroDivisionError",
            str(zero_case),
        )

        timeout = run_in_sandbox(
            TIMEOUT_CODE,
            "python",
            test_cases=[
                {
                    "id": "timeout",
                    "name": "timeout",
                    "stdin": "",
                    "expected_stdout": "",
                    "source": "manual",
                    "oracle": "teacher",
                }
            ],
        )
        timeout_case = timeout["test_results"][0]
        _assert_case(
            "timeout",
            timeout_case.get("status") == "error" and timeout_case.get("error_type") == "Timeout",
            str(timeout_case),
        )

        adversarial = run_in_sandbox(
            MISMATCH_CODE,
            "python",
            test_cases=[
                {
                    "id": "adversarial",
                    "name": "adversarial passed",
                    "stdin": "",
                    "expected_stdout": "expected-only\n",
                    "source": "manual",
                    "oracle": "teacher",
                }
            ],
        )
        # Container may still emit passed=True in legacy rows; backend must fail.
        adv_case = adversarial["test_results"][0]
        _assert_case(
            "backend authority",
            adv_case.get("passed") is False,
            str(adv_case),
        )

        print("PASS", flush=True)
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    finally:
        try:
            shutdown_pool()
        except Exception:
            pass
        for container_id in _task_containers(owner_id):
            subprocess.run(["docker", "rm", "-f", container_id], check=False)
        if started_by_script:
            _stop_compose_services(started_by_script)
        if "SANDBOX_POOL_OWNER" in os.environ and os.environ["SANDBOX_POOL_OWNER"] == owner_id:
            del os.environ["SANDBOX_POOL_OWNER"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2B per-case fixture isolation smoke")
    parser.add_argument(
        "--manage-services",
        action="store_true",
        help="Reserved for compose-managed dependencies; Docker engine must already be available",
    )
    args = parser.parse_args()
    return _run_smoke(manage_services=args.manage_services)


if __name__ == "__main__":
    raise SystemExit(main())
