# CodeJury

Multi-agent system for assessment and self-paced learning in programming.
Instructors describe assignments in any language; agents resolve ambiguities,
build rubrics, style/security checks, and unit tests. Submissions run inside
isolated Docker sandboxes and a chief agent delivers a unified evaluation
report with rubric-based scoring and a final letter grade.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Node](https://img.shields.io/badge/Node.js-18+-339933.svg)](https://nodejs.org/)
[![Docker](https://img.shields.io/badge/Docker-required-2496ED.svg)](https://www.docker.com/)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-black.svg)](https://ollama.com/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Commercial License](https://img.shields.io/badge/Commercial-Available-brightgreen.svg)](#license)
[![Status](https://img.shields.io/badge/Status-Alpha-orange.svg)](#roadmap)

---

## Overview

**CodeJury** is an AI-powered platform that automates the full lifecycle of
programming assignments — authoring, evaluation, and feedback — for both
**formal assessment** (courses, exams, certifications) and **self-paced
learning**.

Instructors no longer need to write detailed assignment specifications,
rubrics, or unit tests by hand. They simply express the assignment idea in
**any natural language** as a *vibe description*. From there, a coordinated
jury of AI agents takes over: one clarifies the assignment with the
instructor, others build the rubric, style guide, security checklist, and
test suite. The student's submission is finally executed inside a sandbox
and consolidated into a unified evaluation report by a chief agent.

The reference implementation in this repository runs every student
submission inside a **pool of pre-warmed Docker containers**, performs
parallel static and dynamic analysis with **seven specialised agents**, and
produces a **rubric-aligned letter grade** powered by a local Ollama LLM.

## Why CodeJury?

| Without CodeJury | With CodeJury |
|---|---|
| Instructors write specs, rubrics, and tests manually | Instructor writes a short vibe description; agents build the rest |
| Single rubric, single perspective | A jury of agents — each specialised in style, security, correctness, and testing |
| Inconsistent grading across submissions | Sandbox-executed, criterion-based, repeatable evaluation |
| Feedback is generic and slow | Per-criterion verdicts synthesised into a structured report |
| Suited only for grading | Equally usable for self-paced learning and practice |

## Key Features

- **Vibe-Description Authoring** — Instructors describe assignments in any natural language; no template required.
- **Interactive Refinement Agent** — Detects ambiguities and resolves them with the instructor through a guided dialog.
- **Auto-Generated Artifacts** — Once the assignment is finalised, the system produces:
  - A structured **assignment specification**
  - A weighted **grading rubric**
  - A **coding-style guide** tailored to the task
  - A **code-security checklist**
  - A complete **unit test suite**
- **Jury-Based Evaluation** — Independent agents review the student's submission against each artifact in parallel.
- **Sandboxed Execution** — A pool of hardened Docker containers runs untrusted student code with strict CPU, memory and network isolation.
- **Chief Synthesis Agent** — Aggregates all jury verdicts into a single human-readable report with a final letter grade.
- **Dual Mode**
  - **Assessment** — for instructors, courses, exams, and bootcamps.
  - **Self-paced learning** — students request feedback on their own attempts at any pace.
- **Multi-language Support** — Python 3, C++ 17, and Java 21 student submissions, all in the same pipeline.
- **Cloud-Native** — Runs fully online; designed to be Kubernetes-ready.
- **Language-Agnostic Pedagogy** — Instructions, rubrics, and feedback can be authored and delivered in any natural language.

## Architecture

```
                 Student uploads code (React UI)
                              |
                              v
                  FastAPI Backend (port 8001)
                              |
        +---------------------+----------------------+
        |                                            |
        v                                            v
  Static Analysis Agents (parallel)        Sandbox Container Pool
   - CodeQualityAgent                       agentgrade-sandbox:8181
   - SeniorityAgent                         agentgrade-sandbox:8182
   - GuidelineAgent                                  ...   x10
   - SecurityAgent                                    |
   - AssignmentAlignmentAgent                         v
        |                                       TestAgent
        +-------------------+------------------+
                            |
                            v
                      EvidenceAgent
                            |
                            v
                  MasterEvaluatorAgent
                  (rubric + letter grade)
```

### Sandbox Pool

At startup the backend pre-warms **10** `agentgrade-sandbox` containers.
Each container ships with Python 3, G++ and OpenJDK 21.

For every analysis request:

1. An idle container is leased from the pool.
2. The submission is delivered via `POST /api/execute`.
3. Code is executed inside the container as an isolated subprocess.
4. The result is returned as JSON.
5. The container is wiped and returned to the pool.

### Security Layers

| Layer | Protection |
|---|---|
| Docker `read_only` | Filesystem writes denied |
| `tmpfs /tmp` | Temp files capped at 50 MB |
| `mem_limit: 512m` | Per-container RAM cap |
| `pids_limit: 64` | Process count cap |
| `no-new-privileges` | Privilege escalation blocked |
| `cap_drop: ALL` | All Linux capabilities dropped |
| `unshare(CLONE_NEWNET)` | Full network isolation |
| `RLIMIT_CPU` / `RLIMIT_AS` | Per-process CPU + memory limits |

## How It Works

```
+----------------------------------------------------------------------+
|  PHASE 1 - ASSIGNMENT AUTHORING                                      |
|                                                                      |
|   Instructor                                                         |
|      |  vibe description                                             |
|      v                                                               |
|   +---------------------+    questions    +---------------------+    |
|   | Refinement Agent    | <-------------> |     Instructor      |    |
|   +---------------------+    answers      +---------------------+    |
|      |                                                               |
|      v                                                               |
|   +---------------------+                                            |
|   | Finalised Spec      |                                            |
|   +---------------------+                                            |
+----------------------------------------------------------------------+
                            |
                            v
+----------------------------------------------------------------------+
|  PHASE 2 - ARTIFACT GENERATION (parallel)                            |
|                                                                      |
|   +-------------+ +-------------+ +-------------+ +-------------+    |
|   | Rubric      | | Style Guide | | Security    | | Unit Test   |    |
|   | Agent       | | Agent       | | Agent       | | Agent       |    |
|   +-------------+ +-------------+ +-------------+ +-------------+    |
+----------------------------------------------------------------------+
                            |
                            v
+----------------------------------------------------------------------+
|  PHASE 3 - STUDENT EVALUATION                                        |
|                                                                      |
|   Student submission                                                 |
|      |                                                               |
|      v                                                               |
|   +-------------------------------------------------------------+    |
|   |  Jury (parallel reviewers)                                  |    |
|   |   - Style verdict     - Security verdict                    |    |
|   |   - Rubric verdict    - Test verdict (sandboxed run)        |    |
|   +-------------------------------------------------------------+    |
|      |                                                               |
|      v                                                               |
|   +---------------------+                                            |
|   | Chief Agent         |  -> consolidated report + letter grade     |
|   +---------------------+                                            |
|                            |                                         |
|                            v                                         |
|              Student & Instructor receive report                     |
+----------------------------------------------------------------------+
```

## The Jury

| Agent | Role |
|---|---|
| **Refinement Agent** | Removes ambiguity from the instructor's vibe description through interactive Q&A. |
| **Rubric Agent** | Produces a weighted grading rubric aligned with the finalised specification. |
| **Code Quality Agent** | Static analysis of structure, complexity and readability (AST-based). |
| **Style / Guideline Agent** | Defines and enforces a language-appropriate coding-style guide. |
| **Seniority Agent** | Estimates the implied seniority level of the submitted code. |
| **Security Agent** | Checks for unsafe patterns, injection risks, and unsafe API usage. |
| **Assignment Alignment Agent** | Confirms the submission actually addresses the assignment. |
| **Test Agent** | Generates and runs unit tests against the student submission in a sandbox. |
| **Evidence Agent** | Cross-references each verdict with concrete evidence from the source. |
| **Master Evaluator Agent** | Synthesises all verdicts into a single report and computes the final letter grade. |

## Supported Languages

| Language | Compilation | Static Analysis |
|---|---|---|
| Python 3 | — | AST-based (S/C/D/E codes) |
| C++ 17 | `g++ -Wall -O2` | GCC warnings |
| Java 21 | `javac -Xlint:all` | javac warnings |

> **Note:** Java submissions must declare the entry class as `Main`.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2 |
| Frontend | React 18 + Vite + TypeScript + TailwindCSS + shadcn/ui |
| Agent runtime | LLM-based multi-agent orchestration |
| LLM | Ollama (general: `qwen2.5:7b`, code agents: `qwen2.5-coder:7b`) |
| Sandboxing | Docker container pool (per-submission isolation) |
| Database | PostgreSQL 16 (optional — `DEMO_MODE=1` runs without it) |
| Message Queue | Redis Streams for asynchronous analysis jobs |
| Orchestration | docker compose (dev), Kubernetes-ready (prod) |
| Storage | Object storage for submissions and reports |

## Installation

> **Detailed setup, troubleshooting and manual steps:** see [INSTALL.md](./INSTALL.md).

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker Desktop (or Docker Engine + `docker compose v2`)
- Ollama with `qwen2.5:7b` and `qwen2.5-coder:7b` models pulled

A read-only verifier ships with the repo:

```bash
npm run check:prereqs
```

This script inspects Python, Node, npm, Docker, `docker compose` and the
local Ollama service, then prints a colour-coded summary. It exits with a
non-zero code if any **mandatory** prerequisite is missing — making it
suitable for CI smoke tests.

### Automated Setup (recommended)

```bash
# Clone the repository
git clone https://github.com/VisusVision/CodeJury.git
cd CodeJury

# Verify prerequisites (does not install anything)
npm run check:prereqs

# Full install: deps + sandbox image + Postgres + Ollama model pull
npm run setup

# Demo mode: skip Docker/Ollama steps and set DEMO_MODE=1
npm run setup:demo

# Start the application
npm run dev:full
```

`npm run setup` automatically dispatches to `scripts/install.ps1`
(Windows) or `scripts/install.sh` (Linux/macOS). Both scripts:

1. Detect missing prerequisites and **warn loudly** — for example, if
   Docker is not installed they print a clear message and skip the
   sandbox/Postgres steps instead of failing silently.
2. Create a Python `.venv`, install `requirements.txt`.
3. Run `npm install` in `frontend/`.
4. Build the `agentgrade-sandbox` Docker image.
5. Bring up PostgreSQL and Redis via `docker compose up -d postgres redis`.
6. Pull the default Ollama model.
7. Print a coloured summary of warnings and errors.

Open the app at <http://localhost:8080>.

### Manual Setup

```bash
# 1. Dependencies
cd frontend && npm install
cd ..
python -m venv .venv
# Windows: .\.venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 2. PostgreSQL + Redis (Docker recommended)
docker compose up -d postgres redis

# 3. Sandbox image (one-time, requires Docker)
docker build -t agentgrade-sandbox sandbox-images/agentgrade/

# 4. Pull the default LLM
ollama pull qwen2.5:7b
ollama pull qwen2.5-coder:7b

# 5. Start the app, API, worker, and local services
npm run dev:full
```

> **Demo Mode:** set `DEMO_MODE=1` in `.env` to run the entire stack
> without PostgreSQL. Pre-seeded credentials —
> Instructor: `demo@agentgrade.local` / `demo123`,
> Student: `20240001` / `11111111111`.

## Environment Variables (`.env`)

```env
# Sandbox Pool
SANDBOX_IMAGE=agentgrade-sandbox
SANDBOX_POOL_SIZE=10
SANDBOX_POOL_BASE_PORT=8181
SANDBOX_POOL_TIMEOUT=30.0

# Database (PostgreSQL — optional under DEMO_MODE)
DATABASE_URL=postgresql://semas:12345@localhost:5432/agent_db

# Redis Streams analysis queue
REDIS_URL=redis://localhost:6379/0
ANALYSIS_QUEUE_NAME=stream:analysis_jobs
ANALYSIS_CONSUMER_GROUP=group:analysis_workers

# Ollama LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_GENERAL_MODEL=qwen2.5:7b
OLLAMA_CODER_MODEL=qwen2.5-coder:7b
OLLAMA_ENABLED=true
OLLAMA_TIMEOUT=900.0

# Demo Mode (no PostgreSQL required)
DEMO_MODE=1
```

## Project Structure

```
CodeJury/
├── package.json                  # Root workspace + setup scripts
├── requirements.txt              # Python dependencies
├── docker-compose.yml            # Dev-time PostgreSQL and Redis services
├── INSTALL.md                    # Full setup & troubleshooting guide
├── scripts/
│   ├── install.ps1               # Windows installer (auto-detects prerequisites)
│   ├── install.sh                # Linux/macOS installer
│   ├── check-prereqs.mjs         # Read-only prerequisite verifier
│   └── run-installer.mjs         # Cross-platform dispatcher
├── sandbox-images/
│   └── agentgrade/               # Single sandbox image (Python + C++ + Java)
│       ├── Dockerfile
│       ├── core/executor.py      # Process isolation (rlimit, unshare)
│       ├── core/orchestrator.py  # Pipeline runner
│       ├── languages/runners.py  # Per-language runners
│       └── api/server.py         # HTTP API (GET /health, POST /execute)
├── backend/
│   ├── agents/                   # The Jury (10+ agents)
│   ├── llm/ollama_client.py      # Ollama client
│   ├── sandbox/                  # Pool-based sandbox executor
│   └── core/config.py            # Application settings
├── samples/                      # Example student submissions
└── frontend/
    ├── src/                      # React + Vite + TypeScript
    ├── backend/main.py           # FastAPI dev entry point
    └── scripts/dev-api.mjs       # Hot-reload uvicorn launcher
```

## Workflows

### Instructor

1. Sign up as **Instructor** from the landing page.
2. Add a **Department** (e.g. *Computer Engineering*).
3. Add a **Course** (e.g. *Data Structures / CS201*).
4. Add an **Assignment**: title, description, deadline.
5. Approve the auto-generated **rubric** (students cannot see it until approved).
6. Review student submissions from the assignment page.

### Student

1. Sign in as **Student** (student number + national ID).
2. Browse your courses and assignments.
3. Upload a Python / C++ / Java file.
4. Receive the analysis report and final grade.

## Use Cases

- **University courses** — automate weekly programming assignment grading.
- **Coding bootcamps** — give students immediate, structured feedback at scale.
- **Technical hiring** — standardised take-home assessments with explainable scoring.
- **Certification programs** — repeatable, auditable evaluation.
- **Self-study** — learners build their own assignments and get jury-grade feedback.
- **Multilingual education** — assignments and feedback in the learner's native language.

## Roadmap

- [x] Multi-agent jury with parallel static + dynamic analysis
- [x] Docker container pool for sandboxed execution
- [x] Rubric-based letter grading
- [x] Cross-platform installer (PowerShell + Bash) with prerequisite checks
- [ ] Public alpha release
- [ ] Plagiarism / similarity detection agent
- [ ] LMS integration (Moodle, Canvas)
- [ ] Multi-file projects and build-system support
- [ ] Voice-based vibe description input
- [ ] Personalised learning paths from accumulated student reports
- [ ] Instructor analytics dashboard

## License

CodeJury is **dual-licensed**:

- **AGPL-3.0** — free for personal, academic, and non-commercial use, as well
  as for commercial use where derivative works are released under AGPL-3.0.
  See [LICENSE](LICENSE).
- **Commercial License** — required for proprietary/commercial use without
  releasing derivative work under AGPL-3.0. See
  [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

For commercial licensing inquiries, please contact: **<your-email>**

## Contributing

Contributions are welcome. Because CodeJury is offered under a
dual-licensing model, contributors will be asked to sign a Contributor
License Agreement (CLA) before pull requests can be merged.

## Contact

**VisusVision** — Visus Artificial Vision and Automation Systems

For questions, partnership, or commercial inquiries, please open an issue
or reach out via the organisation page.

---

*"A jury of expert reviewers — for every line of code."*
