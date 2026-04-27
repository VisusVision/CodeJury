# CodeJury
Multi-agent system for assessment and self-paced learning in programming. Instructors describe assignments in any language; agents resolve ambiguities interactively, then build rubrics, style/security checks, and unit tests. Submissions run in a sandbox and a final agent delivers a unified evaluation report.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Commercial License](https://img.shields.io/badge/Commercial-Available-brightgreen.svg)](#license)
[![Status](https://img.shields.io/badge/Status-Alpha-orange.svg)](#roadmap)

---

## Overview

**CodeJury** is an AI-powered platform that automates the full lifecycle of programming assignments — authoring, evaluation, and feedback — for both **formal assessment** (courses, exams, certifications) and **self-paced learning**.

Instructors no longer need to write detailed assignment specifications, rubrics, or unit tests by hand. They simply express the assignment idea in **any natural language** as a "vibe description". From there, a coordinated jury of AI agents takes over: one agent interactively clarifies the assignment with the instructor, others build the rubric, style guide, security checklist, and unit tests, and finally the student's submission is executed in a sandbox and consolidated into a unified evaluation report by a chief agent.

The platform is delivered as a cloud-based online service.

## Why CodeJury?

| Without CodeJury | With CodeJury |
|---|---|
| Instructors write specs, rubrics, and tests manually | Instructor writes a short vibe description; agents build the rest |
| Single rubric, single perspective | A jury of agents — each specialized in style, security, correctness, and testing |
| Inconsistent grading across submissions | Sandbox-executed, criterion-based, repeatable evaluation |
| Feedback is generic and slow | Per-criterion verdicts synthesized into a structured report |
| Suited only for grading | Equally usable for self-paced learning and practice |

## Key Features

- **Vibe-Description Authoring** — Instructors describe assignments in any natural language; no template required.
- **Interactive Refinement Agent** — Detects ambiguities in the description and resolves them with the instructor through a guided dialog.
- **Auto-Generated Artifacts** — Once the assignment is finalized, the system produces:
  - A structured **assignment specification**
  - A weighted **grading rubric**
  - A **coding-style guide** tailored to the task
  - A **code-security checklist**
  - A complete **unit test suite**
- **Jury-Based Evaluation** — Independent agents review the student's submission against each artifact.
- **Sandboxed Execution** — Tests are executed in an isolated environment to safely run untrusted student code.
- **Chief Synthesis Agent** — Aggregates all jury verdicts into a single human-readable report with optional grading.
- **Dual Mode**:
  - 🎓 **Assessment** — for instructors, courses, exams, and bootcamps.
  - 📚 **Self-paced learning** — students request feedback on their own attempts at any pace.
- **Cloud-Native** — Runs fully online; no local installation required for end users.
- **Language-Agnostic Pedagogy** — Instructions, rubrics, and feedback can be authored and delivered in any natural language.

## How It Works

```
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE 1 — ASSIGNMENT AUTHORING                                      │
│                                                                      │
│   Instructor                                                         │
│      │  vibe description                                             │
│      ▼                                                               │
│   ┌─────────────────────┐    questions    ┌─────────────────────┐    │
│   │ Refinement Agent    │ ◀─────────────▶ │     Instructor      │    │
│   └─────────────────────┘    answers      └─────────────────────┘    │
│      │                                                               │
│      ▼                                                               │
│   ┌─────────────────────┐                                            │
│   │ Finalized Spec      │                                            │
│   └─────────────────────┘                                            │
└──────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE 2 — ARTIFACT GENERATION (parallel)                            │
│                                                                      │
│   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │
│   │ Rubric      │ │ Style Guide │ │ Security    │ │ Unit Test   │    │
│   │ Agent       │ │ Agent       │ │ Agent       │ │ Agent       │    │
│   └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE 3 — STUDENT EVALUATION                                        │
│                                                                      │
│   Student submission                                                 │
│      │                                                               │
│      ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────┐    │
│   │  Jury (parallel reviewers)                                  │    │
│   │   • Style verdict     • Security verdict                    │    │
│   │   • Rubric verdict    • Test verdict (sandboxed run)        │    │
│   └─────────────────────────────────────────────────────────────┘    │
│      │                                                               │
│      ▼                                                               │
│   ┌─────────────────────┐                                            │
│   │ Chief Agent         │  → consolidated report + optional grade    │
│   └─────────────────────┘                                            │
│                            │                                         │
│                            ▼                                         │
│              Student & Instructor receive report                     │
└──────────────────────────────────────────────────────────────────────┘
```

## The Jury

| Agent | Role |
|---|---|
| **Refinement Agent** | Removes ambiguity from the instructor's vibe description through interactive Q&A. |
| **Rubric Agent** | Produces a weighted grading rubric aligned with the finalized specification. |
| **Style Agent** | Defines and enforces a language-appropriate coding-style guide. |
| **Security Agent** | Checks for unsafe patterns, injection risks, and unsafe API usage. |
| **Test Agent** | Generates and runs unit tests against the student submission in a sandbox. |
| **Chief Agent** | Synthesizes all verdicts into a single report and computes an optional grade. |

## Tech Stack

| Layer            | Technology                                          |
|------------------|-----------------------------------------------------|
| Runtime          | Python 3.11+                                        |
| Agent framework  | LLM-based multi-agent orchestration                 |
| Sandboxing       | Containerized isolated execution (per submission)   |
| API              | REST / WebSocket for real-time refinement dialog    |
| Storage          | Object storage for submissions and reports          |
| Deployment       | Cloud-native (Kubernetes-ready)                     |
| Frontend         | Web-based instructor and student portals            |

## Use Cases

- 🎓 **University courses** — automate weekly programming assignment grading
- 🏫 **Coding bootcamps** — give students immediate, structured feedback at scale
- 🏢 **Technical hiring** — standardized take-home assessments with explainable scoring
- 🎯 **Certification programs** — repeatable, auditable evaluation
- 📚 **Self-study** — learners build their own assignments and get jury-grade feedback
- 🌍 **Multilingual education** — assignments and feedback in the learner's native language

## Installation

> ⚠️ Public alpha — installation instructions will be finalized as components are released.

```bash
# Clone the repository
git clone https://github.com/VisusVision/CodeJury.git
cd CodeJury

# Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# (edit .env with your LLM API keys, sandbox settings, etc.)
```

## Quick Start (Planned API)

```python
from codejury import CodeJury

cj = CodeJury()

# Phase 1 — Author an assignment from a vibe description
assignment = cj.author(
    vibe="A first-year Python exercise about sorting a list of student grades, "
         "should teach loops and basic functions, must avoid using sorted().",
    language="python",
    interactive=True,   # opens the refinement dialog
)

# Phase 2 — (auto) rubric, style, security, and tests are generated

# Phase 3 — Evaluate a student submission
report = cj.evaluate(
    assignment_id=assignment.id,
    submission_path="./student_submission.py",
    grade=True,
)

print(report.summary)
print(report.grade)
```

## Roadmap

- [ ] Public alpha release
- [ ] Web UI for instructors and students
- [ ] Plagiarism / similarity detection agent
- [ ] LMS integration (Moodle, Canvas)
- [ ] Support for multi-file projects and build systems
- [ ] Voice-based vibe description input
- [ ] Personalized learning paths from accumulated student reports
- [ ] Instructor analytics dashboard

## License

CodeJury is **dual-licensed**:

- **AGPL-3.0** — free for personal, academic, and non-commercial use, as well as for commercial use where derivative works are released under AGPL-3.0. See [LICENSE](LICENSE).
- **Commercial License** — required for proprietary/commercial use without releasing derivative work under AGPL-3.0. See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

For commercial licensing inquiries, please contact: **<your-email>**

## Contributing

Contributions are welcome. Because CodeJury is offered under a dual-licensing model, contributors will be asked to sign a Contributor License Agreement (CLA) before pull requests can be merged.

## Contact

**VisusVision** — Visus Artificial Vision and Automation Systems

For questions, partnership, or commercial inquiries, please open an issue or reach out via the organization page.

---

*"A jury of expert reviewers — for every line of code."*
