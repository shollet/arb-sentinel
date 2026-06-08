---
description: Run the full pre-commit verification ritual and report results.
---

Run the project's verification ritual, in order, and report what happened.

1. Run: `uv run ruff check .`
2. Run: `uv run ruff format --check .`
3. Run: `uv run pytest`

If `ruff format --check` reports formatting issues, run `uv run ruff format .`,
then re-run `uv run ruff check .` before continuing.

You may fix ruff issues yourself — formatting and `ruff check` violations,
including small behavior-preserving code changes needed to satisfy a rule. But
if satisfying the linter would require changing behavior or business logic, stop
and ask instead of altering logic silently.

Do not commit. Report a concise summary: which of the three steps passed or
failed, what you fixed (if anything), and anything that needs my attention.
