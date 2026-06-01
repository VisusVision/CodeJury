# Assignment, Rubric, and Grading QA Design

## Goal

Act as a QA engineer for the full faculty-to-student grading flow:

1. Create a programming assignment through the faculty chatbot.
2. Generate an AI rubric for that assignment.
3. Analyze representative related, unrelated, unsafe, and partial submissions.
4. Improve deterministic behavior where the system rewards unrelated code, invents rubric scope, or gives unclear feedback.

## Canonical Scenario

Use a CSV/log summarization CLI assignment because it gives clear positive and negative fixtures:

- Related: reads a file path, counts INFO/WARNING/ERROR rows, handles malformed lines, prints a summary.
- Partial: counts rows but misses error handling or file-path behavior.
- Unrelated: implements a library/book API or factorial calculator.
- Unsafe or risky: writes destructive commands, executes shell input, or includes suspicious file operations.

The assignment should remain a code/programming assignment, not a presentation or report-only task.

## Expected Behavior

The chatbot should produce a concrete title, description, and expected-output example. The description must preserve input/output expectations because those details drive rubric generation and relevance checks.

The rubric generator should create 10-20 criteria, each 5-10 points, totaling 100. Rows must be project-specific: CSV/log parsing, CLI input, summary accuracy, malformed-row handling, tests, style, documentation, and security. It should not invent unrelated API, OOP, database, or presentation requirements unless the assignment asks for them.

The grading pipeline should:

- Give high scores to the related complete solution.
- Give moderate scores to partial but on-topic code.
- Penalize unrelated code strongly, with explicit feedback that it does not match the assignment.
- Keep unsafe behavior critical even when the task involves file handling.
- Preserve instructor rubric order and labels in the final breakdown.

## Implementation Strategy

Start with tests that exercise existing helpers and agent contracts. Prefer deterministic tests for rubric scope, task relevance, and final scoring invariants. Use direct backend function calls before browser smoke tests so failures are fast and attributable.

If behavior fails, patch the narrowest backend helper or frontend copy/service path that causes it. Avoid broad UI redesigns. Keep demo mode and database behavior aligned for API changes.

## Verification

Run targeted backend tests for assignment assistant, rubric constraints, agent contracts, and behavior matrix. Run the frontend build after code changes. If local services are healthy, smoke-test the faculty flow in the browser.
