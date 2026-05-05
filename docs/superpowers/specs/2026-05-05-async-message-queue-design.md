# Async Message Queue Design

Date: 2026-05-05
Project: AgentGrade / CodeJury
Status: Draft for review

## Goal

Add asynchronous message-queue communication between long-running system components, starting with the code analysis pipeline.

The first implementation should satisfy this requirement:

> Sistem bilesenleri arasindaki iletisim, asenkron mesaj kuyruklari (orn. RabbitMQ, Kafka veya Redis Pub/Sub) uzerinden saglanmalidir.

The initial scope is the `/api/analyze` flow because it is the clearest long-running boundary in the current architecture. React should submit an analysis request, FastAPI should enqueue a job, a worker should process it outside the request lifecycle, and the UI should poll job status until the result is ready.

## Current State

Current request flow:

```text
React UI
  -> POST /api/analyze
  -> FastAPI runs run_analysis_pipeline(...)
  -> FastAPI returns full analysis result
```

The backend already runs several independent agents in parallel with `asyncio.gather`, and sandbox execution is called from the same FastAPI process through `run_in_executor`. This gives concurrency inside one request, but it does not decouple API request handling from long-running work.

## Recommended Approach

Use Redis Streams for the first queue implementation.

Reasons:

- Small operational footprint for local development and demos.
- Easy to add to the existing `docker-compose.yml`.
- Python client support is mature.
- Good fit for job queues, consumer groups, status polling, and retry metadata.
- Lower complexity than RabbitMQ or Kafka for the current project size.

RabbitMQ remains a good future option if the system needs richer routing, dead-letter exchanges, or multiple specialized worker pools. Kafka is not recommended for the first version because this is job processing, not high-volume event streaming.

## Target Flow

```text
React UI
  -> POST /api/analyze
  -> FastAPI validates request and creates analysis job
  -> FastAPI publishes job_id to Redis stream
  -> FastAPI returns { job_id, status: "queued" }

Analysis Worker
  -> blocks on Redis stream consumer group
  -> loads job payload
  -> marks job "running"
  -> calls run_analysis_pipeline(...)
  -> stores result
  -> marks job "completed" or "failed"

React UI
  -> GET /api/analyze/jobs/{job_id}
  -> receives queued/running/completed/failed state
  -> renders result when completed
```

## Components

### Redis

Add a `redis` service to `docker-compose.yml`.

Default local URL:

```text
redis://localhost:6379/0
```

### Backend Config

Add settings:

```text
redis_url = "redis://localhost:6379/0"
analysis_queue_name = "analysis_jobs"
analysis_job_ttl_seconds = 86400
analysis_worker_poll_timeout_seconds = 5
```

### Queue Module

Add a small backend module, for example:

```text
backend/queue/analysis_jobs.py
```

Responsibilities:

- Create job IDs.
- Serialize and store job payloads.
- Publish job IDs to the analysis stream.
- Read and update job status.
- Store successful results or failure details.
- Hide Redis implementation details from FastAPI and the worker.

Suggested Redis keys:

```text
stream:analysis_jobs                 -> Redis stream of analysis job messages
group:analysis_workers               -> Redis consumer group for workers
analysis_job:{job_id}                -> Redis hash or JSON payload
```

### Worker Script

Add:

```text
backend/workers/analysis_worker.py
```

Responsibilities:

- Connect to Redis.
- Wait for job messages from the Redis stream.
- Mark jobs as `running`.
- Call `run_analysis_pipeline(...)`.
- Persist `completed` result or `failed` error.
- Keep processing until interrupted.

The worker should import and reuse the existing pipeline function instead of duplicating agent orchestration logic.

### FastAPI Endpoints

Change:

```text
POST /api/analyze
```

New behavior:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

Add:

```text
GET /api/analyze/jobs/{job_id}
```

Example queued/running response:

```json
{
  "job_id": "uuid",
  "status": "running",
  "created_at": "2026-05-05T12:00:00Z",
  "updated_at": "2026-05-05T12:00:05Z"
}
```

Example completed response:

```json
{
  "job_id": "uuid",
  "status": "completed",
  "result": {
    "...": "existing analysis result shape"
  }
}
```

Example failed response:

```json
{
  "job_id": "uuid",
  "status": "failed",
  "error": "Analiz tamamlanamadi. Lutfen tekrar deneyin."
}
```

### Frontend

Update `frontend/src/services/api.ts` and the analysis UI flow.

Expected behavior:

- Submit code with `POST /api/analyze`.
- Receive `job_id`.
- Poll `GET /api/analyze/jobs/{job_id}` every 1-2 seconds.
- Stop polling when status is `completed` or `failed`.
- Render the existing report UI when `completed`.
- Show a clear Turkish error toast when `failed`.

## Job Status Model

Allowed statuses:

```text
queued
running
completed
failed
```

Recommended fields:

```text
job_id
status
request
result
error
created_at
updated_at
started_at
finished_at
attempts
```

## Demo Mode and Database Mode

First implementation can store job status in Redis for both demo and database modes. This avoids adding a database migration before the queue behavior is proven.

Later, if analysis history needs durable reporting, add an `analysis_jobs` table and treat Redis as the transport while PostgreSQL becomes the source of truth for status and results.

## Error Handling

FastAPI:

- Return `503` if Redis is unavailable when submitting a job.
- Return `404` if a job ID does not exist.
- Return clear Turkish error details for UI display.

Worker:

- Catch pipeline exceptions per job.
- Store a safe user-facing error.
- Store technical error details only in logs.
- Increment `attempts`.

Retry policy for first implementation:

- No automatic retry by default.
- Mark failed jobs as `failed`.
- Add retry later if failures are commonly transient.

## Operational Commands

Development startup should eventually support three processes:

```text
docker compose up -d redis postgres
npm --prefix frontend run dev
python backend/workers/analysis_worker.py
```

If the project keeps `npm run dev:full`, add worker startup to that script or document it as a separate terminal command.

## Test Plan

Backend unit tests:

- Job creation stores request payload.
- Enqueue writes job ID to the Redis stream.
- Status endpoint returns queued/running/completed/failed.
- Missing job returns 404.
- Redis outage on submit returns 503.

Worker tests:

- Worker processes one queued job and stores completed result.
- Worker stores failed status when pipeline raises.
- Existing `run_analysis_pipeline(...)` behavior is preserved.

Frontend tests or smoke checks:

- Submit action receives `job_id`.
- UI polls status endpoint.
- Completed job renders existing report.
- Failed job shows Turkish error toast.

Verification commands:

```powershell
python -m py_compile backend\queue\analysis_jobs.py backend\workers\analysis_worker.py frontend\backend\main.py
npm --prefix frontend run build
```

## Implementation Phases

### Phase 1: Queue Infrastructure

- Add Redis to Docker Compose.
- Add Redis settings.
- Add Python Redis dependency.
- Add queue module with create/enqueue/get/update helpers.

### Phase 2: API Contract

- Update `POST /api/analyze` to enqueue jobs.
- Add `GET /api/analyze/jobs/{job_id}`.
- Keep existing analysis result schema unchanged inside completed job results.

### Phase 3: Worker

- Add worker script.
- Reuse `run_analysis_pipeline(...)`.
- Add logs for queued, running, completed, failed transitions.

### Phase 4: Frontend Polling

- Update API service methods.
- Update analysis screen to poll by `job_id`.
- Preserve current report rendering after completion.

### Phase 5: Verification and Documentation

- Add targeted backend tests.
- Run py_compile and frontend build.
- Update README/INSTALL startup docs with Redis and worker steps.

## Out of Scope for First Version

- Kafka.
- RabbitMQ exchange/routing topology.
- Durable PostgreSQL `analysis_jobs` table.
- WebSocket/SSE push updates.
- Advanced retry and dead-letter queue behavior.
- Multiple specialized worker pools per agent.

## Open Decisions

1. Whether to keep `POST /api/analyze` fully asynchronous immediately, or add a temporary compatibility mode that can still run synchronously when Redis is disabled.
2. Whether upload-history analysis should also move to the queue in the first implementation or remain synchronous until `/api/analyze` is stable.
3. Whether `npm run dev:full` should launch the worker automatically.

## Recommendation

Implement Redis-backed async analysis jobs first, keep the existing pipeline function intact, and expose job status through polling. This gives the project a real asynchronous messaging boundary while keeping the migration small, testable, and reversible.
