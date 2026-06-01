# Assignment Rubric QA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and improve the end-to-end assignment chatbot, AI rubric, and grading behavior using a QA-style matrix of related, partial, unrelated, and risky submissions.

**Architecture:** Use existing backend tests as the primary safety net, then patch the smallest failing helper or agent invariant. Keep UI changes limited to copy/state behavior only if tests expose a frontend-specific issue.

**Tech Stack:** FastAPI backend in `frontend/backend/main.py`, Python agents in `backend/agents`, pytest/unittest backend tests, React/Vite frontend.

---

### Task 1: Establish Current QA Baseline

**Files:**
- Read: `backend/tests/test_assignment_assistant.py`
- Read: `backend/tests/test_rubric_suggestion_constraints.py`
- Read: `backend/tests/test_agent_behavior_matrix.py`
- Read: `backend/tests/test_agent_contracts.py`

- [ ] **Step 1: Run assignment assistant tests**

Run: `python -m pytest backend/tests/test_assignment_assistant.py -q`
Expected: PASS. If it fails, capture the failing test name and assertion.

- [ ] **Step 2: Run rubric constraint tests**

Run: `python -m pytest backend/tests/test_rubric_suggestion_constraints.py -q`
Expected: PASS. If it fails, capture whether the issue is count, point total, stale domain leakage, or invented scope.

- [ ] **Step 3: Run grading/relevance tests**

Run: `python -m pytest backend/tests/test_agent_behavior_matrix.py backend/tests/test_agent_contracts.py -q`
Expected: PASS. If it fails, capture whether related code is under-scored, unrelated code is over-scored, or risky behavior is softened.

### Task 2: Add or Tighten QA Fixtures Only If Needed

**Files:**
- Modify: `backend/tests/test_agent_behavior_matrix.py`
- Modify: `backend/tests/test_agent_contracts.py`
- Use fixtures from: `samples/log_ozetleme_uygun.py`, `samples/log_ozetleme_alakasiz.py`, `samples/log_ozetleme_guvensiz.py`

- [ ] **Step 1: Add failing test for unrelated code if missing**

Add a test that analyzes the log-summary assignment against a clearly unrelated library/book or factorial solution and asserts the final score is low and feedback mentions assignment mismatch.

- [ ] **Step 2: Add failing test for related code if missing**

Add a test that analyzes a complete log-summary CLI implementation and asserts the relevance signal is strong and the final score is not capped as off-topic.

- [ ] **Step 3: Add failing test for risky code if missing**

Add a test that analyzes code using dangerous shell execution or destructive file operations and asserts the security finding remains critical/high even if the assignment involves files.

### Task 3: Patch Backend Behavior Narrowly

**Files:**
- Modify only as needed: `backend/agents/task_relevance.py`
- Modify only as needed: `backend/agents/master_evaluator.py`
- Modify only as needed: `backend/agents/security.py`
- Modify only as needed: `frontend/backend/main.py`

- [ ] **Step 1: Fix rubric scope leakage**

If rubric tests fail because generated/fallback rows invent API/OOP/database/presentation scope, update the sanitizer or fallback description helper in `frontend/backend/main.py` so replacement rows use the assignment title/description terms.

- [ ] **Step 2: Fix relevance scoring**

If unrelated code is over-scored, adjust the deterministic task-capability signal or final off-topic merge in `backend/agents/task_relevance.py` and `backend/agents/master_evaluator.py`.

- [ ] **Step 3: Fix unsafe file handling classification**

If risky code is softened for file-processing assignments, adjust `backend/agents/security.py` so read-only file I/O remains allowed while shell execution, destructive writes, or command injection remain severe.

### Task 4: Verify Full Stack Build

**Files:**
- Read: `frontend/package.json`
- Read: `frontend/vitest.config.ts`

- [ ] **Step 1: Compile core Python files**

Run: `python -m py_compile backend\agents\assignment_safety.py frontend\backend\main.py backend\agents\task_relevance.py backend\agents\master_evaluator.py backend\agents\security.py`
Expected: no output and exit code 0.

- [ ] **Step 2: Build frontend**

Run: `npm --prefix frontend run build`
Expected: Vite build succeeds.

### Task 5: Manual Smoke Test When Services Are Available

**Files:**
- Read: `frontend/package.json`
- Use: local app through Vite/API dev scripts

- [ ] **Step 1: Start local dev stack**

Run: `npm --prefix frontend run dev`
Expected: Vite and API start without port conflicts.

- [ ] **Step 2: Faculty smoke path**

Open the faculty dashboard, create a CSV/log assignment via chatbot, request AI rubric, approve rubric, and confirm the created assignment appears with approved rubric status.

- [ ] **Step 3: Student/analysis smoke path**

Submit one related sample and one unrelated sample. Confirm related receives substantially better score and unrelated feedback calls out task mismatch.

### Self-Review

Spec coverage is complete: assignment creation, rubric generation, related/unrelated/risky submissions, deterministic agent behavior, and build verification are represented. No placeholders remain. File paths match the current repo layout.
