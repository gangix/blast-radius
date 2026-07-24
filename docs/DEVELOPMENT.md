# Development Process

Blast Radius was built with a **plan-first, test-driven** workflow. The team
authored the design and a task-decomposed implementation plan up front, then
implemented it task-by-task using [Claude Code](https://claude.com/claude-code)
(Anthropic's agentic coding assistant) as the implementer — with a code-review
gate after every task and a whole-branch review before merge.

## Engineering principles

- **Deterministic core, LLM only at the edges.** Every graph fact — lineage,
  30-day query history, ownership — comes from the DataHub SDK. The model never
  invents lineage; it only phrases facts the code has already fetched.
- **Pure, testable units.** Each module is a pure, unit-testable core plus a
  thin DataHub-facing wrapper; SDK types never leak past the client boundary.
- **Test-driven.** Failing test → minimal implementation → green, per unit.
  The PR-comment output is locked with golden-file tests.

## Worked example: the PR-comment renderer

We scoped the feature, wrote a design spec, then split it into **seven
independently testable tasks**. For each task the team specified the exact
interfaces and acceptance tests; Claude Code implemented it TDD-style; a review
gate checked spec-compliance and code quality before the next task began.

### Task breakdown

1. Pure helpers — verdict roll-up, entity-URL builder, change titling
2. `render_comment` skeleton — marker, header, per-change sections, footer
3. Collapse rule — low-severity sections fold away unless the whole PR passes
4. Breaking-queries table + owners line
5. At-a-glance table with change-scoped impact
6. Named downstream-consumer links (clickable, back to DataHub)
7. Golden-file lock — three demo scenarios + a multi-change PR

### Iteration & review

The review gates caught real issues before they shipped:

- **Task 4 review** found that the owners line could surface a raw email
  address for any owner without a display name. Fixed so owner handles never
  leak an address — with a regression test pinning it.
- **The final whole-branch review** found that the "affected assets" list
  showed a *table's* dashboards on a single-*column* change — which
  contradicted a clean-pass verdict ("no downstream impact… affected assets:
  3 dashboards"). Relabeled and scoped by change kind so a column change never
  implies it feeds consumers it may not.
- The same review caught unescaped `|` in Markdown table cells (DataHub asset
  names are free text and can contain pipes). Added cell escaping and a test.

Result: **81 passing tests**, byte-stable golden output, and four binding
output-quality rules enforced end-to-end (column-scoped severity, a
`Query | Author`-only queries table, plain-text owners, and correct
percent-encoded DataHub links).

## Running the tests

```bash
pip install -e ".[dev]"
pytest          # unit + golden tests; integration tests auto-skip if DataHub is down
ruff check .    # lint
```
