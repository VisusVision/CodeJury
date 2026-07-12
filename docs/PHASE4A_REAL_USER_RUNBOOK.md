# Phase 4A Real-User Acceptance Runbook

This runbook records a **real teacher and student browser journey** for Phase 4A release qualification. Credentials are supplied outside the repository and must never appear in URLs, console output, screenshots, or evidence files.

**Prerequisites:** `.env` with `DEMO_MODE=0`, Docker Desktop running, real LLM provider configured, and existing teacher/student accounts ready.

**UI:** `http://localhost:8080`  
**API health:** `http://127.0.0.1:8001/api/health` (default dev port; override with `HEALTH_URL` if needed)

---

## 1. Service discovery and startup

Verified compose services (`docker compose config --services`):

- `postgres`
- `redis`

Start infrastructure and build the sandbox image:

```powershell
docker compose up -d postgres redis
docker build -t agentgrade-sandbox sandbox-images/agentgrade
```

Start the full dev stack (Vite frontend + API + analysis worker):

```powershell
npm run dev:full
```

Verify health from a second terminal:

```powershell
npm --prefix frontend run verify:health
```

**Expected health signals:**

| Check | Expected |
|-------|----------|
| `DEMO_MODE` | `0` in `.env` (not in-memory demo persistence) |
| PostgreSQL | Compose service `postgres` running |
| Redis | Compose service `redis` running |
| Analysis worker | `analysis_ready: true`, `ready_worker_count >= 1` |
| Sandbox pool | `sandbox.pool_ready: true`, `sandbox.mode: "pool"` |
| Frontend | `http://localhost:8080` loads login page |
| Active LLM | Health payload shows enabled provider; assignment/rubric AI calls succeed |

If `analysis_ready` is `false`, confirm Docker Desktop is running, the sandbox image was built, and the worker process started by `npm run dev:full` is healthy.

---

## 2. Teacher journey (steps 1–8)

Use credentials **only** in the login form. Never paste them into the URL, browser console, or evidence files.

1. **Login** as teacher through the UI.
2. **Create a run ID** and use it as the assignment name prefix:

   ```powershell
   $runId = "phase4a-$([guid]::NewGuid())"
   ```

3. Open the **assignment assistant** and obtain a real-LLM suggestion (do not store prompt text in evidence).
4. Create a **Python Two Sum** assignment expecting a linear/hash-map approach.
5. **Generate a rubric** with the real LLM, review it, and **save it approved**.
6. Add **one public** and **one hidden** manual test case.
7. Request **AI test suggestions** and **promote** at least one verified case to faculty tests.
8. Open the **read-only algorithm expectation** panel and confirm it loads.

---

## 3. Student journey (three sequential submissions)

Login as the authorized student. Submit these three semantic variants **through the UI** without storing full source code in evidence:

| # | Variant | Purpose |
|---|---------|---------|
| 1 | Correct `dict`-based linear Two Sum | Expected approach |
| 2 | Correct nested-loop quadratic Two Sum | Working but worse complexity |
| 3 | Submission that raises a runtime exception on a formal case | Failure path |

For **each** submission:

1. Upload/submit and wait for queue completion (poll until report is ready).
2. Open the report and verify **all agent cards** render.
3. Complete any **mandatory evaluation feedback** before starting the next submission.

**Student visibility (binding):** Public test cases may show `input`, `expected`, and `actual` in the student report. Hidden cases remain redacted (status/count only). Evidence files must not contain I/O values or source code.

---

## 4. Authorization and privacy checks

After all three student jobs finish:

| Check | Expected |
|-------|----------|
| Teacher opens each result | Sees authorized hidden details and provenance |
| Student report | Public evidence + aggregate hidden counts only |
| Student opens teacher routes | Blocked (redirect/login) |
| Student opens another job ID | Denied |
| Teacher opens another teacher's assignment | `404` for a known unrelated assignment ID |
| Logout | Protected routes redirect/login; API mutations return `401`/`403` |

---

## 5. Record evidence (no secrets)

Create the evidence directory:

```powershell
New-Item -ItemType Directory -Force -Path "artifacts/phase4a/$runId"
```

Save `artifacts/phase4a/$runId/browser-evidence.json` with **only**:

- `run_id`, `assignment_id`, three `job_ids`
- `teacher_journey_passed`, `student_journey_passed`, `unauthorized_checks_passed`
- Relative `screenshots` paths (files in the same directory)

**Rules:**

- Use synthetic UUIDs in the schema example; real runs use actual IDs from the UI/API.
- Take screenshots **after** password fields are cleared.
- Screenshots must not display hidden test content, credentials, or full submission source.
- Validate before proceeding:

  ```powershell
  $evidence = "artifacts/phase4a/$runId/browser-evidence.json"
  python -c "from pathlib import Path; from backend.ops.release_qualification import Phase4ABrowserEvidence; import json,sys; p=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); [p.__setitem__(f, tuple(p[f])) for f in ('job_ids','screenshots') if isinstance(p.get(f), list)]; Phase4ABrowserEvidence.model_validate(p); print('BROWSER_EVIDENCE_VALID=True')" $evidence
  ```

Example shape: [`docs/examples/phase4a-browser-evidence.example.json`](examples/phase4a-browser-evidence.example.json)

---

## 6. Audit before cleanup

```powershell
$evidence = "artifacts/phase4a/$runId/browser-evidence.json"
python scripts/qa_phase4a_run_audit.py --evidence $evidence
```

Expected: all three Redis jobs completed; required agent matrix present; student projection has no forbidden structure; formal and algorithm authority checks pass.

---

## 7. Cleanup

Re-run audit with ownership-checked cleanup (only run-owned data):

```powershell
python scripts/qa_phase4a_run_audit.py --evidence $evidence --cleanup
```

Confirm no run-owned assignment, job, cache, or lock residue remains. Runtime artifacts under `artifacts/phase4a/` stay gitignored.

---

## 8. Final release command

```powershell
python scripts/qa_phase4a_release.py `
  --manage-services `
  --browser-evidence $evidence
```

Expected: every step prints `PASS`; final ledger shows `BASELINE_FAILURE_COUNT=0` and all failure/leak/override/residue flags `false`.

Post-run verification:

```powershell
docker compose ps
git status --short --branch
git diff --check
```

---

## Quick reference

| Artifact | Path |
|----------|------|
| Browser evidence | `artifacts/phase4a/<run-id>/browser-evidence.json` |
| Screenshots | `artifacts/phase4a/<run-id>/*.png` |
| Example schema | `docs/examples/phase4a-browser-evidence.example.json` |
| Release orchestrator | `scripts/qa_phase4a_release.py` |
| Run audit | `scripts/qa_phase4a_run_audit.py` |
