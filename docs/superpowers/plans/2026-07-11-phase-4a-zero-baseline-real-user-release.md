# Faz 4A Zero-Baseline Real-User Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every tolerated backend failure and prove the complete AgentGrade Python workflow with real PostgreSQL, Redis, worker, Docker sandbox, the active real LLM provider, and teacher/student browser journeys.

**Architecture:** Gate 4A.1 fixes the eight baseline failures with isolated TDD changes. Gate 4A.2 adds a typed, secret-safe release ledger plus a real-run auditor and an orchestrator that composes existing Phase 1/2B/3 QA scripts. Gate 4A.3 executes real teacher/student UI journeys and records only non-secret browser evidence; Gate 4A.4 audits private/student results, cleanup, CI, and documentation.

**Tech Stack:** Python 3.11+, pytest/unittest, Pydantic v2, FastAPI, asyncpg/PostgreSQL, redis.asyncio, React 18, TypeScript, Vitest, Vite, Docker, in-app Browser, real Ollama or NVIDIA NIM selected from `.env`.

## Global Constraints

- Target branch is `develop`; start from commit `a778163` or a descendant containing Faz 3 remediation `7761b8c`.
- `DEMO_MODE=0` is mandatory for release acceptance.
- Use the active provider selected by `.env`; never force Ollama when NVIDIA NIM is active.
- Real LLM acceptance asserts schemas, roles, metadata, evidence, and guardrails; never exact prose or exact model-generated scores.
- Backend full pytest must finish with zero failures; do not add xfail, skip, allow-failure, or a baseline allowlist.
- Preserve Faz 1 fail-closed sandbox, Faz 2A authorization/projection, Faz 2B formal-test authority, and Faz 3 algorithm guardrails.
- Do not change teacher registration, role policy, rubric/final-score wiring, or C++/Java support in this phase.
- Existing user profiles and passwords must not be mutated.
- Never write credentials, cookies, CSRF tokens, hidden I/O, oracle data, or private prompts to source, logs, commands, screenshots, or artifacts.
- Browser evidence belongs under ignored `artifacts/phase4a/$runId/`; no runtime artifact is committed.
- Cleanup may delete only records whose assignment/course name begins with the exact `phase4a-<uuid>` run ID and Redis job keys explicitly recorded by that run.
- Before each commit run focused tests and `git diff --check`; stage only the task files.
- Push is not authorized.

## File Responsibility Map

### Existing behavior and tests

- `backend/tests/test_agent_contracts.py`: safe/low SecurityAgent contract.
- `frontend/backend/main.py`: concrete assignment-title vocabulary and rubric provider-neutral prompt.
- `backend/tests/test_assignment_assistant.py`: near-duplicate suggestion contract.
- `backend/agents/master_evaluator.py`: existing alignment cap table; production values remain unchanged.
- `backend/tests/test_llm_pipeline_integration.py`: exact boundary characterization for the cap table.
- `backend/llm/ollama_client.py`: explicit general/coder request role and provider/model routing.
- `backend/agents/base.py`: all agent JSON calls declare the coder role.
- `backend/agents/assignment_safety.py` and `backend/agents/task_relevance.py`: general reasoning calls declare the general role.
- `backend/tests/test_ollama_model_routing.py`: environment-independent routing, fallback, and token-floor matrix.
- `backend/tests/test_rubric_suggestion_constraints.py`: provider-neutral count prompt contract.

### New release qualification domain

- `backend/ops/release_qualification.py`: frozen ledger/evidence models, safe serialization, result invariants.
- `backend/tests/test_release_qualification.py`: redaction, completeness, browser evidence, agent matrix tests.
- `scripts/qa_phase4a_run_audit.py`: reads recorded Redis jobs and PostgreSQL ownership, audits results, optionally performs ownership-checked cleanup.
- `backend/tests/test_phase4a_run_audit.py`: pure audit and cleanup-plan tests with fakes.
- `scripts/qa_phase4a_release.py`: subprocess orchestration of full suites and existing Phase QA scripts.
- `backend/tests/test_phase4a_release_cli.py`: command inventory, fail-fast behavior, browser evidence requirement, secret-safe output.
- `docs/PHASE4A_REAL_USER_RUNBOOK.md`: exact service, browser, evidence, audit, and cleanup sequence.
- `LOCAL_QUICKSTART.md`: one-command Faz 4A gates and expected ledger.

---

## Gate 4A.1 — Zero Baseline

### Task 1: Correct Stale Security and Alignment Test Contracts

**Files:**
- Modify: `backend/tests/test_agent_contracts.py:1832-1848`
- Modify: `backend/tests/test_llm_pipeline_integration.py:156-164`

**Interfaces:**
- Consumes: `SecurityAgent._programmatic_analysis` and `MasterEvaluatorAgent._alignment_score_cap`.
- Produces: environment-independent assertions matching the current approved safe-risk enum and alignment ceiling table.

- [ ] **Step 1: Reproduce both baseline failures without editing production code**

```powershell
python -m pytest -q `
  backend/tests/test_agent_contracts.py::SecurityAgentContractTests::test_expected_http_client_use_is_calibrated `
  backend/tests/test_llm_pipeline_integration.py::MasterEvaluatorGuardTests::test_alignment_score_cap_thresholds
```

Expected: two failures. The SecurityAgent result is `risk_level="safe"` and `safe=True`; the old test compares enum strings lexicographically. The cap function returns `18.0` for `0.15`, consistent with its current `<0.18` boundary.

- [ ] **Step 2: Replace the invalid lexical security assertion**

```python
self.assertTrue(result["safe"])
self.assertIn(result["risk_level"], {"safe", "low"})
self.assertEqual(result["critical_count"], 0)
self.assertEqual(result["high_count"], 0)
```

- [ ] **Step 3: Replace the single stale cap assertion with the complete boundary table**

```python
def test_alignment_score_cap_thresholds(self):
    cap = MasterEvaluatorAgent._alignment_score_cap
    cases = (
        (0.0, 18.0),
        (0.179999, 18.0),
        (0.18, 28.0),
        (0.299999, 28.0),
        (0.30, 42.0),
        (0.449999, 42.0),
        (0.45, 65.0),
        (0.699999, 65.0),
        (0.70, 100.0),
        (1.0, 100.0),
    )
    for factor, expected in cases:
        with self.subTest(factor=factor):
            self.assertEqual(cap(factor), expected)
```

- [ ] **Step 4: Run GREEN and related guard suites**

```powershell
python -m pytest -q `
  backend/tests/test_agent_contracts.py `
  backend/tests/test_llm_pipeline_integration.py `
  backend/tests/test_agent_behavior_matrix.py
git diff --check
```

Expected: all selected tests pass; no production file changes in this task.

- [ ] **Step 5: Commit Task 1**

```powershell
git add backend/tests/test_agent_contracts.py backend/tests/test_llm_pipeline_integration.py
git diff --cached --check
git commit -m "test(contracts): align release baselines"
```

### Task 2: Preserve Concrete Hash Assignments and Provider-Neutral Rubric Prompts

**Files:**
- Modify: `frontend/backend/main.py:705-745,2697-2792,7351-7392`
- Modify: `backend/tests/test_assignment_assistant.py:280-306`
- Modify: `backend/tests/test_rubric_suggestion_constraints.py:13-53`

**Interfaces:**
- Consumes: `_is_generic_assignment_title`, `_clean_assignment_suggestion_items`, and `suggest_rubric`.
- Produces: concrete hash-table suggestions survive filtering; rubric prompts contain an explicit exact count and do not override the active provider.

- [ ] **Step 1: Reproduce the two remaining non-routing failures**

```powershell
python -m pytest -q `
  backend/tests/test_assignment_assistant.py::AssignmentSuggestionDiversityTests::test_clean_assignment_suggestion_items_drops_near_duplicate_descriptions `
  backend/tests/test_rubric_suggestion_constraints.py::RubricSuggestionConstraintTests::test_hard_assignment_gets_more_criteria_and_required_rows
```

Expected: assignment cleaner returns one row instead of two because `Hash Tablosu Sayaci` is treated as a generic three-word title; rubric prompt lacks the explicit English `exactly` contract and forces `provider_override="ollama"`.

- [ ] **Step 2: Add a focused title classifier RED test**

```python
def test_hash_table_title_is_concrete_not_generic(self):
    from frontend.backend.main import _is_generic_assignment_title

    self.assertFalse(_is_generic_assignment_title("Hash Tablosu Sayaci"))
    self.assertTrue(_is_generic_assignment_title("Programlama Odevi"))
```

- [ ] **Step 3: Add `hash` to the concrete domain-token allowlist**

```python
for token in (
    "csv", "api", "log", "stack", "sqlite", "hash", "kitap", "kutuphane",
    "frekans", "client", "endpoint", "lifo", "sayi",
)
```

- [ ] **Step 4: Strengthen the rubric prompt test before implementation**

```python
prompt = chat.await_args.kwargs["user_prompt"]
self.assertIn("exactly", prompt.lower())
self.assertIn(f"{len(criteria)} criteria", prompt.lower())
self.assertNotIn("provider_override", chat.await_args.kwargs)
self.assertEqual(chat.await_args.kwargs["model"], settings.ollama_general_model)
```

- [ ] **Step 5: Make the user prompt bilingual and provider-neutral**

```python
user_prompt = (
    f"Odev basligi: {title}\n"
    f"Odev aciklamasi:\n{desc or '(bos)'}\n\n"
    f"{build_project_context(title, desc).prompt_block()}\n"
    "Rubrik yalnizca bu odev icin gecerli olmali. Her kriter aciklamasinda odevde gecen "
    "somut terimleri (dosya, sinif, endpoint, rapor sutunu, CLI argumani, vb.) kullan.\n"
    f"Istenen kriter sayisi: {criterion_count}\n"
    f"Produce exactly {criterion_count} criteria; max_score total must be exactly 100.\n"
    f"Her max_score {_RUBRIC_MIN_POINTS}-{_RUBRIC_MAX_POINTS} arasi tam sayi."
)

result = await chat_json(
    system_prompt=_RUBRIC_SUGGEST_SYSTEM,
    user_prompt=user_prompt,
    temperature=0.32,
    num_predict=_rubric_num_predict_for_count(criterion_count),
    model=_llm_cfg.ollama_general_model,
)
```

Also replace the Ollama-specific 502 detail with `Aktif LLM provider rubrik JSON uretemedi.` so a real NIM failure does not misdiagnose the provider.

- [ ] **Step 6: Run GREEN**

```powershell
python -m pytest -q `
  backend/tests/test_assignment_assistant.py `
  backend/tests/test_rubric_suggestion_constraints.py `
  backend/tests/test_ollama_model_routing.py::OllamaModelRoutingTests::test_rubric_suggester_uses_general_model
python -m py_compile frontend/backend/main.py
git diff --check
```

- [ ] **Step 7: Commit Task 2**

```powershell
git add frontend/backend/main.py backend/tests/test_assignment_assistant.py backend/tests/test_rubric_suggestion_constraints.py
git diff --cached --check
git commit -m "fix(assignments): stabilize suggestion contracts"
```

### Task 3: Make LLM Role Routing Explicit

**Files:**
- Modify: `backend/llm/ollama_client.py:116-165,453-770`
- Modify: `backend/agents/base.py:130-270`
- Modify: `backend/agents/assignment_safety.py:520-550`
- Modify: `backend/agents/task_relevance.py:430-510`
- Modify: `frontend/backend/main.py` at every `chat_json` call
- Modify: `backend/tests/test_ollama_model_routing.py`

**Interfaces:**
- Consumes: current provider settings and logical Ollama/NIM model settings.
- Produces: `LLMRole = Literal["general", "coder"]`; `chat_json`, `chat_json_with_metadata`, and `chat_text` accept `role: LLMRole | None = None`.
- Contract: explicit role always wins; legacy model inference works only when general/coder logical model names are distinct; ambiguous equal names default to `general` unless the caller declares `coder`.

- [ ] **Step 1: Add RED tests for equal logical model names**

```python
async def test_equal_logical_models_route_by_explicit_role(self):
    with (
        patch.object(settings, "ollama_general_model", "shared-local"),
        patch.object(settings, "ollama_coder_model", "shared-local"),
        patch.object(settings, "llm_general_provider", "nvidia_nim"),
        patch.object(settings, "llm_coder_provider", "ollama"),
        patch.object(settings, "nvidia_nim_api_key", "secret"),
        patch("backend.llm.ollama_client._do_nvidia_nim_request", new=AsyncMock(return_value={"general": True})) as nim,
        patch("backend.llm.ollama_client._do_request", new=AsyncMock(return_value={"coder": True})) as ollama,
    ):
        general = await chat_json(
            system_prompt="Return JSON.", user_prompt="{}", model="shared-local",
            role="general", use_cache=False,
        )
        coder = await chat_json(
            system_prompt="Return JSON.", user_prompt="{}", model="shared-local",
            role="coder", use_cache=False,
        )

    self.assertEqual(general, {"general": True})
    self.assertEqual(coder, {"coder": True})
    nim.assert_awaited_once()
    ollama.assert_awaited_once()
```

Add parallel tests for `chat_text`, coder NIM model selection, and the NIM token floor with `role="general"`.

- [ ] **Step 2: Define the role type and role resolver**

```python
from typing import Literal

LLMRole = Literal["general", "coder"]


def _resolve_role(model: str | None, role: LLMRole | None) -> LLMRole:
    if role in {"general", "coder"}:
        return role
    if (
        model is not None
        and settings.ollama_coder_model != settings.ollama_general_model
        and model == settings.ollama_coder_model
    ):
        return "coder"
    return "general"


def _provider_for_role(role: LLMRole) -> str:
    default = _llm_provider()
    if role == "coder":
        return _normalize_provider(settings.llm_coder_provider) or default
    return _normalize_provider(settings.llm_general_provider) or default


def _model_for_role(role: LLMRole, *, nim: bool) -> str:
    if nim:
        return settings.nvidia_nim_coder_model if role == "coder" else settings.nvidia_nim_general_model
    return settings.ollama_coder_model if role == "coder" else settings.ollama_general_model
```

- [ ] **Step 3: Thread `role` through the three public clients**

```python
async def chat_json(
    system_prompt: str,
    user_prompt: str,
    schema_hint: dict[str, Any] | None = None,
    temperature: float = 0.0,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    role: LLMRole | None = None,
    use_cache: bool = True,
    provider_override: str | None = None,
) -> dict | None:
    if not settings.ollama_enabled:
        return None
    result = await _chat_json_request(
        system_prompt,
        user_prompt,
        schema_hint,
        temperature,
        num_predict,
        model=model,
        role=role,
        use_cache=use_cache,
        provider_override=provider_override,
    )
    return result.data
```

Apply the same keyword to `chat_json_with_metadata`, `chat_text`, and `_chat_json_request`. Compute `resolved_role = _resolve_role(model, role)` once, then derive provider and selected model from that role. Include role in the cache key and diagnostics metadata so equal logical model strings cannot cross-contaminate caches.

- [ ] **Step 4: Make agent and product call sites explicit**

```diff
# backend/agents/base.py — every analysis and repair call
-            model=settings.ollama_coder_model,
+            model=settings.ollama_coder_model,
+            role="coder",

# assignment safety, task relevance, rubric/assistant/resource calls
-            model=settings.ollama_general_model,
+            model=settings.ollama_general_model,
+            role="general",
```

Do not add `provider_override="ollama"` to any product call. Provider override remains available only for an intentional caller-owned route.

- [ ] **Step 5: Update all routing tests to declare semantic role**

Every general-provider test passes `role="general"`; every coder-provider test passes `role="coder"`. Keep explicit tests proving legacy inference when local model names are distinct and safe general fallback when they are equal.

- [ ] **Step 6: Run the routing GREEN matrix**

```powershell
python -m pytest -q backend/tests/test_ollama_model_routing.py backend/tests/test_agent_contracts.py
python -m py_compile backend/llm/ollama_client.py backend/agents/base.py backend/agents/assignment_safety.py backend/agents/task_relevance.py frontend/backend/main.py
git diff --check
```

Expected: all prior NIM routing/token-floor failures are green under the repository `.env`, including when general and coder logical model names are equal.

- [ ] **Step 7: Commit Task 3**

```powershell
git add backend/llm/ollama_client.py backend/agents/base.py backend/agents/assignment_safety.py backend/agents/task_relevance.py frontend/backend/main.py backend/tests/test_ollama_model_routing.py
git diff --cached --check
git commit -m "fix(llm): route requests by explicit role"
```

### Task 4: Close Gate 4A.1 With Zero Backend Failures

**Files:**
- No file changes. A failure returns execution to the owning Task 1, 2, or 3; never patch in this gate.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: a fresh zero-failure backend ledger; no baseline exceptions.

- [ ] **Step 1: Run the formerly failing names together**

```powershell
python -m pytest -q `
  backend/tests/test_agent_contracts.py::SecurityAgentContractTests::test_expected_http_client_use_is_calibrated `
  backend/tests/test_assignment_assistant.py::AssignmentSuggestionDiversityTests::test_clean_assignment_suggestion_items_drops_near_duplicate_descriptions `
  backend/tests/test_llm_pipeline_integration.py::MasterEvaluatorGuardTests::test_alignment_score_cap_thresholds `
  backend/tests/test_ollama_model_routing.py::OllamaModelRoutingTests::test_chat_json_routes_coder_model_to_nvidia_nim_payload `
  backend/tests/test_ollama_model_routing.py::OllamaModelRoutingTests::test_chat_text_routes_to_nvidia_nim_payload `
  backend/tests/test_ollama_model_routing.py::OllamaModelRoutingTests::test_hybrid_provider_routes_general_to_nim_and_coder_to_ollama `
  backend/tests/test_ollama_model_routing.py::NimTokenFloorTests::test_nim_request_raises_caller_tokens_to_floor `
  backend/tests/test_rubric_suggestion_constraints.py::RubricSuggestionConstraintTests::test_hard_assignment_gets_more_criteria_and_required_rows
```

Expected: `8 passed`.

- [ ] **Step 2: Run full backend twice**

```powershell
python -m pytest -q backend/tests --tb=short
python -m pytest -q backend/tests --tb=short
```

Expected both times: zero failed, three or fewer skipped. A flaky second run blocks Gate 4A.1.

- [ ] **Step 3: Run frontend and build**

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run build
python -m compileall -q backend frontend/backend scripts
git diff --check
```

Expected: all commands exit 0.

---

## Gate 4A.2 — Typed Release Qualification

### Task 5: Add Secret-Safe Release Ledger Contracts

**Files:**
- Create: `backend/ops/release_qualification.py`
- Create: `backend/tests/test_release_qualification.py`

**Interfaces:**
- Produces: `Phase4ABrowserEvidence`, `Phase4ACheck`, `Phase4AReleaseLedger`, `audit_analysis_pair(private_result, student_result)`, and `safe_ledger_lines(ledger)`.
- Consumed by: Tasks 6-8.

- [ ] **Step 1: Write frozen model and redaction RED tests**

```python
def test_release_ledger_requires_every_gate() -> None:
    with pytest.raises(ValidationError):
        Phase4AReleaseLedger(run_id="phase4a-123", checks=())


def test_safe_lines_never_emit_secrets() -> None:
    ledger = _complete_ledger(detail="password=SECRET cookie=COOKIE hidden=HIDDEN")
    text = "\n".join(safe_ledger_lines(ledger))
    assert "SECRET" not in text
    assert "COOKIE" not in text
    assert "HIDDEN" not in text


def test_analysis_pair_requires_all_agents_and_no_student_private_keys() -> None:
    private, student = _result_pair()
    audit = audit_analysis_pair(private, student)
    assert audit.agent_contract_failed is False
    assert audit.student_private_data_leak is False
```

- [ ] **Step 2: Implement strict contracts**

```python
REQUIRED_CHECKS = (
    "BASELINE_FAILURE_COUNT",
    "BACKEND_FULL_SUITE_FAILED",
    "FRONTEND_SUITE_FAILED",
    "FRONTEND_BUILD_FAILED",
    "POSTGRES_READY",
    "REDIS_READY",
    "WORKER_READY",
    "SANDBOX_REAL_EXECUTION_FAILED",
    "REAL_LLM_PROVIDER_MISMATCH",
    "TEACHER_JOURNEY_FAILED",
    "STUDENT_JOURNEY_FAILED",
    "AGENT_CONTRACT_FAILED",
    "FORMAL_AUTHORITY_OVERRIDDEN",
    "ALGORITHM_GUARDRAIL_OVERRIDDEN",
    "STUDENT_PRIVATE_DATA_LEAK",
    "UNAUTHORIZED_ACCESS_SUCCEEDED",
    "CLEANUP_RESIDUE_FOUND",
)

REQUIRED_AGENT_IDS = frozenset({
    "code_quality", "algorithm", "ai_authorship", "seniority",
    "guideline", "security", "testing", "evidence", "master",
})


class Phase4ABrowserEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str = Field(pattern=r"^phase4a-[0-9a-f-]{36}$")
    assignment_id: str
    job_ids: tuple[str, str, str]
    teacher_journey_passed: bool
    student_journey_passed: bool
    unauthorized_checks_passed: bool
    screenshots: tuple[str, ...] = ()


class Phase4ACheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    safe_value: bool | int | str
    passed: bool
    detail_code: str = ""


class Phase4AReleaseLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    provider: str
    model: str
    checks: tuple[Phase4ACheck, ...]
```

Add a model validator requiring every `REQUIRED_CHECKS` name exactly once.

- [ ] **Step 3: Implement structural analysis auditing**

`audit_analysis_pair` must require the agent IDs above, `reportStatus="ready"`, `algorithmResult`, formal testing totals, and server-owned score guardrail fields. It must recursively reject student keys matching:

```python
STUDENT_FORBIDDEN_KEYS = frozenset({
    "stdin", "input", "expected", "expected_stdout", "actual", "stderr", "diff",
    "files", "fixtures", "oracle_validation", "cacheKey", "cache_key", "setId",
    "expectationId", "expectationVersion", "expectedSource", "extractorProvider",
    "extractorModel", "verifierProvider", "verifierModel", "verificationReason",
})
```

Do not use substring matching for ordinary student prose; inspect structure and explicit high-entropy sentinels supplied by the audit caller.

- [ ] **Step 4: Implement secret-safe console serialization**

`safe_ledger_lines` outputs only `CHECK_NAME=<safe_value>` plus provider/model names. It never serializes raw details, browser DOM, private results, credentials, cookies, source code, test I/O, or prompts.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_release_qualification.py
python -m py_compile backend/ops/release_qualification.py
git diff --check
git add backend/ops/release_qualification.py backend/tests/test_release_qualification.py
git diff --cached --check
git commit -m "feat(ops): add release qualification ledger"
```

### Task 6: Add Real-Run Audit and Ownership-Checked Cleanup

**Files:**
- Create: `scripts/qa_phase4a_run_audit.py`
- Create: `backend/tests/test_phase4a_run_audit.py`

**Interfaces:**
- Consumes: `Phase4ABrowserEvidence`, Redis keys `analysis_job:{job_id}`, PostgreSQL assignments, generated sets, expectations, and `audit_analysis_pair`.
- Produces: `audit_browser_run(evidence_path, *, cleanup: bool) -> Phase4AReleaseLedger` and an ownership-checked cleanup plan.

- [ ] **Step 1: Write RED tests for ownership and residue**

```python
def test_cleanup_refuses_assignment_without_exact_run_prefix() -> None:
    with pytest.raises(UnsafeCleanupTarget):
        build_cleanup_plan(
            run_id="phase4a-11111111-1111-4111-8111-111111111111",
            assignment={"id": "a1", "name": "Existing Assignment"},
            job_ids=("j1", "j2", "j3"),
        )


def test_cleanup_plan_contains_only_recorded_jobs() -> None:
    plan = build_cleanup_plan(
        run_id=RUN_ID,
        assignment={"id": "a1", "name": f"{RUN_ID} Algorithm QA"},
        job_ids=("j1", "j2", "j3"),
    )
    assert plan.redis_keys == (
        "analysis_job:j1", "analysis_job:j2", "analysis_job:j3",
    )
```

- [ ] **Step 2: Implement evidence loading without secrets**

```python
def load_browser_evidence(path: Path) -> Phase4ABrowserEvidence:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Phase4ABrowserEvidence.model_validate(payload)
```

The evidence file contains IDs and booleans only. It never contains login values, cookies, CSRF tokens, code bodies, private report data, or hidden test data.

- [ ] **Step 3: Implement Redis job audit**

For each recorded job ID, read only `analysis_job:{id}`. Decode `private_result` and `student_result`, require `status=completed`, run `audit_analysis_pair`, and collect structural booleans. Never print the decoded payload.

- [ ] **Step 4: Implement PostgreSQL ownership verification and cleanup**

Use:

```python
def _asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")
```

Before deletion, fetch assignment `id`, `name`, and `created_by`; require `name.startswith(run_id)`. In one transaction, delete the assignment by exact UUID and rely on verified foreign-key cascades. After commit, assert no rows remain for the assignment in `rubrics`, `assignment_test_cases`, `generated_test_sets`, or `algorithm_expectations`. Delete only the three recorded Redis job keys and exact run-prefixed cache/lock keys discovered by `SCAN`. If any residue remains, set `CLEANUP_RESIDUE_FOUND=True` and exit non-zero.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_phase4a_run_audit.py backend/tests/test_release_qualification.py
python -m py_compile scripts/qa_phase4a_run_audit.py
git diff --check
git add scripts/qa_phase4a_run_audit.py backend/tests/test_phase4a_run_audit.py
git diff --cached --check
git commit -m "test(ops): audit real release runs"
```

### Task 7: Compose the Existing QA Gates Into One Release Command

**Files:**
- Create: `scripts/qa_phase4a_release.py`
- Create: `backend/tests/test_phase4a_release_cli.py`

**Interfaces:**
- Consumes: existing Phase QA scripts, full test/build commands, `qa_phase4a_run_audit.py`, and optional browser evidence.
- Produces: `python scripts/qa_phase4a_release.py --manage-services --browser-evidence <path>`.

- [ ] **Step 1: Write command-inventory RED test**

```python
def test_release_command_inventory_is_complete() -> None:
    names = [spec.name for spec in build_release_commands(browser_evidence=Path("evidence.json"))]
    assert names == [
        "backend_full",
        "frontend_full",
        "frontend_build",
        "compileall",
        "pool_smoke",
        "phase2b_cache",
        "phase2b_case_isolation",
        "phase2b_e2e",
        "phase3_expectation",
        "phase4a_run_audit",
    ]
```

Add tests that the first failed command stops execution, missing browser evidence fails in final mode, `--system-only` omits only the browser audit, and captured output is summarized by status code without echoing raw stdout containing sentinels.

- [ ] **Step 2: Implement immutable command specs**

```python
@dataclass(frozen=True, slots=True)
class ReleaseCommand:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int


def build_release_commands(browser_evidence: Path | None) -> tuple[ReleaseCommand, ...]:
    commands = (
        ReleaseCommand("backend_full", (PYTHON, "-m", "pytest", "-q", "backend/tests", "--tb=short"), 900),
        ReleaseCommand("frontend_full", (NPM, "--prefix", "frontend", "test", "--", "--run"), 300),
        ReleaseCommand("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), 300),
        ReleaseCommand("compileall", (PYTHON, "-m", "compileall", "-q", "backend", "frontend/backend", "scripts"), 180),
        ReleaseCommand("pool_smoke", (PYTHON, "scripts/qa_pool_smoke.py"), 300),
        ReleaseCommand("phase2b_cache", (PYTHON, "scripts/qa_phase2b_cache_smoke.py", "--manage-services"), 300),
        ReleaseCommand("phase2b_case_isolation", (PYTHON, "scripts/qa_phase2b_case_isolation.py", "--manage-services"), 300),
        ReleaseCommand("phase2b_e2e", (PYTHON, "scripts/qa_phase2b_e2e.py", "--manage-services"), 600),
        ReleaseCommand("phase3_expectation", (PYTHON, "scripts/qa_phase3_algorithm_expectation.py", "--manage-services"), 600),
    )
    if browser_evidence is None:
        return commands
    return commands + (
        ReleaseCommand("phase4a_run_audit", (PYTHON, "scripts/qa_phase4a_run_audit.py", "--evidence", str(browser_evidence), "--cleanup"), 300),
    )
```

Resolve `PYTHON` from `sys.executable`; resolve npm as `npm.cmd` on Windows and `npm` elsewhere.

- [ ] **Step 3: Implement fail-fast subprocess execution**

Use:

```python
completed = subprocess.run(
    list(spec.argv),
    cwd=ROOT,
    timeout=spec.timeout_seconds,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    check=False,
)
```

On success print only `f"{spec.name}=PASS"`; on failure print `f"{spec.name}=FAIL"`, exit code, and a sanitized final 20-line diagnostic that removes values matching `password|cookie|csrf|authorization|hidden|expected_stdout|stdin` key patterns.

- [ ] **Step 4: Preserve initial service state**

The orchestrator delegates service ownership to existing `--manage-services` QA scripts and verifies `docker compose ps` after each command. It never stops a service that was running before the command. A residue check failure marks the release failed.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_phase4a_release_cli.py
python -m py_compile scripts/qa_phase4a_release.py
git diff --check
git add scripts/qa_phase4a_release.py backend/tests/test_phase4a_release_cli.py
git diff --cached --check
git commit -m "test(release): compose phase qualification"
```

---

## Gate 4A.3 — Real Teacher and Student Browser Journeys

### Task 8: Add the Real-User Runbook and Evidence Contract

**Files:**
- Create: `docs/PHASE4A_REAL_USER_RUNBOOK.md`
- Modify: `LOCAL_QUICKSTART.md`
- Test: `backend/tests/test_release_qualification.py`

**Interfaces:**
- Consumes: live app at `http://localhost:8080`, API at `http://localhost:8000`, existing teacher/student credentials supplied outside the repository, and `Phase4ABrowserEvidence`.
- Produces: ignored `artifacts/phase4a/$runId/browser-evidence.json` and screenshots containing no credentials or hidden values.

- [ ] **Step 1: Add evidence example validation test**

```python
def test_browser_evidence_example_is_valid_and_secret_free() -> None:
    payload = json.loads(Path("docs/examples/phase4a-browser-evidence.example.json").read_text())
    evidence = Phase4ABrowserEvidence.model_validate(payload)
    serialized = evidence.model_dump_json()
    assert "password" not in serialized.lower()
    assert "cookie" not in serialized.lower()
    assert "csrf" not in serialized.lower()
```

Create `docs/examples/phase4a-browser-evidence.example.json` with synthetic UUIDs only.

- [ ] **Step 2: Document exact service startup**

```powershell
docker compose up -d postgres redis
docker build -t agentgrade-sandbox sandbox-images/agentgrade
npm run dev:full
npm --prefix frontend run verify:health
```

Expected health: `analysis_ready=true`, at least one ready worker, sandbox `ready`, active LLM enabled.

- [ ] **Step 3: Document exact teacher journey**

The runbook requires:

1. Login through the teacher UI; never place credentials in the URL or console.
2. Generate `$runId = "phase4a-$([guid]::NewGuid())"` and use it as the assignment-name prefix.
3. Open assignment assistant and obtain a real-LLM suggestion.
4. Create a Python assignment for Two Sum with expected linear/hash approach.
5. Generate a rubric with the real LLM, review it, and save it approved.
6. Add one public and one hidden manual case.
7. Request AI test suggestions and promote at least one verified case.
8. Open the read-only algorithm expectation panel.

- [ ] **Step 4: Document exact student journey**

Submit these three semantic variants through the UI, without storing full source in evidence:

1. Correct `dict`-based linear Two Sum.
2. Correct nested-loop quadratic Two Sum.
3. A submission that raises a runtime exception for a formal case.

For each, wait for queue completion, open the report, verify all agent cards render, and complete any mandatory evaluation feedback before starting the next submission.

- [ ] **Step 5: Document teacher-private and authorization checks**

After the student jobs finish:

- Teacher opens each result and sees authorized hidden/provenance details.
- Student report shows public evidence and aggregate hidden counts only.
- Student cannot open teacher routes or another job ID.
- Teacher cannot access an assignment owned by another teacher; use a known unrelated ID and expect 404.
- Logout causes protected routes to redirect/login and API mutation calls to return 401/403.

- [ ] **Step 6: Record evidence without secrets**

The browser evidence file contains only run ID, assignment ID, three job IDs, journey booleans, and screenshot relative paths. Screenshots must be taken after password fields are gone and must not display hidden test content.

- [ ] **Step 7: Run docs/example GREEN and commit**

```powershell
python -m pytest -q backend/tests/test_release_qualification.py
git diff --check
git add docs/PHASE4A_REAL_USER_RUNBOOK.md docs/examples/phase4a-browser-evidence.example.json LOCAL_QUICKSTART.md backend/tests/test_release_qualification.py
git diff --cached --check
git commit -m "docs(release): add real-user acceptance runbook"
```

### Task 9: Execute the Real Browser Journey

**Files:**
- Runtime only: `artifacts/phase4a/$runId/browser-evidence.json`
- Runtime only: `artifacts/phase4a/$runId/*.png`

**Interfaces:**
- Consumes: Task 8 runbook and live services.
- Produces: one complete `Phase4ABrowserEvidence` artifact for Task 10.

- [ ] **Step 1: Start and verify real services**

Run the Task 8 startup commands. Do not continue until `/api/health` reports analysis readiness and the active provider/model expected from `.env`.

- [ ] **Step 2: Use the in-app Browser for the teacher journey**

Follow every teacher step in the runbook. Record the generated assignment ID from visible navigation/API state, not from cookies or local storage.

- [ ] **Step 3: Use the in-app Browser for the student journey**

Run all three submissions sequentially. Record only job IDs and pass/fail observations; never save full source or hidden results in the artifact.

- [ ] **Step 4: Use the in-app Browser for role and privacy checks**

Verify student DOM lacks hidden/provenance labels and teacher DOM includes authorized detail. Test logout and cross-role navigation.

- [ ] **Step 5: Create and validate browser evidence**

```powershell
$evidence = "artifacts/phase4a/$runId/browser-evidence.json"
python -c "from pathlib import Path; from backend.ops.release_qualification import Phase4ABrowserEvidence; import json,sys; Phase4ABrowserEvidence.model_validate(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))); print('BROWSER_EVIDENCE_VALID=True')" $evidence
```

Expected: `BROWSER_EVIDENCE_VALID=True`. This task creates no git commit.

---

## Gate 4A.4 — Combined Release Sign-Off

### Task 10: Audit, Clean Up, and Run the Final Release Gate

**Files:**
- No planned file changes. A failure returns to the task that owns the failing behavior.
- Do not commit runtime artifacts.

**Interfaces:**
- Consumes: browser evidence from Task 9 and every previous gate.
- Produces: final zero-failure Phase 4A ledger and zero run-owned residue.

- [ ] **Step 1: Audit results before cleanup**

```powershell
$evidence = "artifacts/phase4a/$runId/browser-evidence.json"
python scripts/qa_phase4a_run_audit.py `
  --evidence $evidence
```

Expected: all three Redis jobs completed; required agent matrix present; student projection contains no forbidden structure or sentinels; formal and algorithm authority checks pass.

- [ ] **Step 2: Run the combined release orchestrator with cleanup**

```powershell
python scripts/qa_phase4a_release.py `
  --manage-services `
  --browser-evidence $evidence
```

Expected: every command prints `PASS`; final ledger has `BASELINE_FAILURE_COUNT=0` and all failure/leak/override/residue flags `False`.

- [ ] **Step 3: Verify service state and repository cleanliness**

```powershell
docker compose ps
git status --short --branch
git diff --check
```

Expected: service state matches the pre-run snapshot; no run-owned assignment/job/cache residue; only pre-existing untracked `.cursor/`, `.superpowers/`, `cursor_sandbox_testing_and_analysis.md`, and `frontend/README.md` remain.

- [ ] **Step 4: Run CI-equivalent commands once more**

```powershell
python -m pytest -q backend/tests --tb=short
npm --prefix frontend test -- --run
npm --prefix frontend run build
python -m compileall -q backend frontend/backend scripts
```

Expected: all commands exit 0, backend has zero failures.

- [ ] **Step 5: Final scope audit**

```powershell
git diff --name-only a778163..HEAD
rg -n "xfail|allow-failure|continue-on-error" .github backend/tests
rg -n "provider_override=\"ollama\"" backend frontend/backend
rg -n "PHASE4A_.*PASSWORD|emre123|230501013" . ':!.git'
```

Expected: no baseline suppression, no forced provider in product calls, and no credential value in tracked or untracked task artifacts. If the final credential scan finds the user-owned conversation markdown, do not modify or stage it; confirm no task-created file contains the value.

- [ ] **Step 6: Commit any final documentation-only correction**

If `LOCAL_QUICKSTART.md` required a command/count correction after the real run:

```powershell
git add LOCAL_QUICKSTART.md
git diff --cached --check
git commit -m "docs(release): finalize phase 4a evidence"
```

If no tracked correction is needed, create no empty commit.

- [ ] **Step 7: Independent final review**

Reviewer reads `a778163..HEAD`, reruns the eight former failures, inspects explicit role routing under equal local model names, reruns the full backend/frontend gates, checks browser evidence schema, and adversarially validates cleanup ownership and student projection before Faz 4A is declared closed.

## Execution Handoff

Execute Tasks 1-10 in order. Gate 4A.1 must be zero-failure before release tooling is added. Each task receives a fresh diff review and focused verification; no report from an implementation worker is accepted without rerunning its commands. The real browser journey is mandatory and cannot be replaced by API-only or mocked tests. Push is not performed without explicit authorization.
