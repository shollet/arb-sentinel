# ADR-0001: Introduce Claude Code as an implementation-under-spec tool

- **Status**: Accepted
- **Date**: 2026-06-06
- **Deciders**: Shayan Hollet
- **Context iteration**: Iteration 1

## Context

Iteration 0 deliberately deferred Claude Code (decision log, 2026-05-23). The reason
was **pedagogical**: learn the modern Python stack (`uv`, `ruff`, `pydantic`,
`hypothesis`, `httpx`) by hand first, to build the intuition that makes delegating to
an agent later a deliberate choice rather than a crutch. That iteration is now
complete and was built entirely by hand, so the pedagogical debt is paid.

Two facts frame the decision now:

1. **The `earn complexity` principle governs *product* complexity** — the code, the
   dependencies, the architecture. Claude Code is **developer tooling**: it adds
   nothing to the shipped artifact, the dependency set, or the runtime architecture.
   So adopting it does not violate `earn complexity` in the product sense; it is a
   workflow choice, and the original deferral was about learning, not architecture.

2. **The project's career thesis is platform engineering** — its value signal is
   architecture and design, not typing implementation. Iteration 1 is design-heavy
   (the scope, the phantom-filter spec, the selection logic).

## Decision

Adopt Claude Code starting in Iteration 1, as an **implementation-under-spec** tool,
with guardrails that keep design ownership with the human:

1. **Spec-first.** Shayan owns the architecture and the specs under `docs/design/`.
   Claude Code implements *against* an existing spec; it does not invent
   architecture. The human is the architect, the agent is the implementer.
2. **Pre-commit audit unchanged.** The full verification sequence still runs before
   every commit (`uv run ruff check . && uv run ruff format --check . && uv run
   pytest`), together with the standing question "does this respect our design?".
3. **Conventional Commits unchanged.** Logical, grouped commits with bodies that
   explain the *why*.
4. **Every diff reviewed against the spec before commit.** This discipline matters
   more with an agent, not less.

Scope of use in Iteration 1: implementation of the dynamic tournament discovery, the
phantom filter, the Discord webhook, the JSONL journal, and the cycle-robustness
changes — all under their specs. Architecture and scope decisions remain human.

## Consequences

**Positive**
- Faster implementation, freeing time for the design/architecture work that is the
  project's actual portfolio signal.
- Reinforces the platform-engineering narrative: *own the design, delegate the
  implementation under that design.*
- The pedagogical reason for deferral is satisfied; the tool is already paid for.

**Risks and mitigations**
- *Agent drifts from the spec* → mitigated by spec-first plus mandatory diff review
  against the spec before commit.
- *Over-delegating architecture* → explicitly retained by the human; the agent is
  scoped to implementation only.
- *Specs stop being the contract* → this is the trip-wire to revisit (see below).

**Neutral**
- No change to product complexity, dependencies, or CI. The shipped artifact is
  identical to one written by hand.

## Alternatives considered

- **Keep hand-coding through Iteration 1, adopt in Iteration 2.** More conservative;
  maximizes hands-on learning of IT1's genuinely new fundamentals (scheduling,
  webhook, persistence). Rejected because the pedagogical debt is already paid and
  IT1 is design-heavy, so the marginal learning from hand-typing the implementation is
  low relative to the time it costs.
- **Do not adopt at all.** Rejected: career-aligned, already available, and zero
  product cost.

## Revisit when

- Specs stop functioning as the contract (the agent's output and the design drift
  apart), or
- Delegation begins to erode the design ownership the project exists to demonstrate.

This ADR supersedes the 2026-05-23 decision-log entry "Defer Claude Code introduction
to learn the stack first."
