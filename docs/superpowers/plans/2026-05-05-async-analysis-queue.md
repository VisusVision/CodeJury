# Async Analysis Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move code analysis requests from synchronous FastAPI execution to Redis Streams backed asynchronous jobs.

**Architecture:** FastAPI validates `/api/analyze`, stores an analysis job in Redis, publishes the job ID to a Redis Stream, and returns `job_id`. A standalone worker consumes the stream and reuses `run_analysis_pipeline(...)`. The frontend keeps its current `analyzeCode(...)` surface by polling the new job status endpoint internally.

**Tech Stack:** FastAPI, Pydantic, Redis Streams via `redis.asyncio`, React/Vite TypeScript, unittest/Vitest build checks.

---

### Task 1: Queue Job Store

**Files:**
- Create: `backend/queue/__init__.py`
- Create: `backend/queue/analysis_jobs.py`
- Create: `backend/tests/test_analysis_jobs.py`
- Modify: `requirements.txt`
- Modify: `frontend/backend/requirements.txt`

- [ ] Write failing unit tests for job creation, stream publish, status lookup, completion, and failure.
- [ ] Run `python -m unittest backend.tests.test_analysis_jobs -v` and confirm the missing module/import failure.
- [ ] Implement the Redis-backed queue helpers with fake-client friendly async methods.
- [ ] Run `python -m unittest backend.tests.test_analysis_jobs -v` and confirm pass.

### Task 2: Worker

**Files:**
- Create: `backend/workers/__init__.py`
- Create: `backend/workers/analysis_worker.py`
- Create: `backend/tests/test_analysis_worker.py`

- [ ] Write failing worker tests that process one job successfully and one job failure.
- [ ] Run `python -m unittest backend.tests.test_analysis_worker -v` and confirm failure.
- [ ] Implement `process_job(...)` and an async stream consumer loop.
- [ ] Run `python -m unittest backend.tests.test_analysis_worker -v` and confirm pass.

### Task 3: FastAPI Endpoints

**Files:**
- Modify: `frontend/backend/main.py`
- Create: `backend/tests/test_analysis_queue_api.py`

- [ ] Write failing API tests by calling `analyze_code(...)` and `get_analysis_job(...)` with monkeypatched queue helpers.
- [ ] Run `python -m unittest backend.tests.test_analysis_queue_api -v` and confirm failure.
- [ ] Update `POST /api/analyze` to enqueue analysis jobs.
- [ ] Add `GET /api/analyze/jobs/{job_id}`.
- [ ] Run `python -m unittest backend.tests.test_analysis_queue_api -v` and confirm pass.

### Task 4: Frontend Polling

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] Add typed job response handling.
- [ ] Keep `analyzeCode(...)` returning `Promise<ApiAnalysisResult>` by polling until completion.
- [ ] Preserve legacy direct-result compatibility for older backend responses.

### Task 5: Runtime Docs

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `INSTALL.md`

- [ ] Add Redis to Compose.
- [ ] Document Redis and worker startup.
- [ ] Keep existing frontend/API startup docs intact.

### Task 6: Verification

**Files:**
- Verify all touched files.

- [ ] Run `python -m unittest backend.tests.test_analysis_jobs backend.tests.test_analysis_worker backend.tests.test_analysis_queue_api -v`.
- [ ] Run `python -m py_compile backend\queue\analysis_jobs.py backend\workers\analysis_worker.py frontend\backend\main.py`.
- [ ] Run `npm --prefix frontend run build`.
- [ ] Review `git diff` and `git status --short`.
