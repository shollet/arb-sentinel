# Examples

Executable scripts that explore design decisions and demonstrate how to use
the library. Each script can be run with `uv run python examples/<file>.py`.

These are **not tests**. Tests enforce invariants and run in CI; examples
illustrate intent and may evolve as the library evolves.

## Scripts

- **`001_modeling_poc.py`** — validates that the domain models can faithfully
  represent a realistic two-bookmaker tennis event. Run before committing
  to the model structure in Iteration 0.
