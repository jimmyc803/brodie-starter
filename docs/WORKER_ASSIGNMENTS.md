# Client workout selection

With `DEMO_CLIENT_ID` configured, the worker fetches the client's newest active
assignment at each call's entrypoint. Worker registration and model prewarming do
not fetch or cache the assignment. Updating an assignment therefore applies to
the next call without restarting the worker. An ongoing call keeps its original day.

If the database is unavailable, the assignment is missing, the day has no counted
exercises, or a supported exercise has invalid counts, that call stops before any
workout starts. It does not fall back to `starter/plan.txt` or the demo workout.
The worker logs a generic assignment failure; database response bodies are not logged.

Supported exercises require integer sets in `1..100` and integer reps in `1..1000`.
Boolean, fractional, string, missing, zero, negative, and excessive counts are
rejected. Unsupported/manual exercises are skipped. The day may contain at most
50 exercises, matching the PDF parser's bounds.

Explicit `--plan`, `PLAN`, `--exercise`, `--auto`, and `--perception off` remain
manual overrides. Without a client ID, the starter/demo behavior is unchanged.

Offline regression coverage:

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_plan_loader.py tests/test_worker_assignment.py tests/test_worker_recap.py -q
```
