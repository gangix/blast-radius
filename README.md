# Blast Radius — PR Impact Guardian for data teams

> A GitHub bot that reads every data PR, asks DataHub *"what breaks downstream and who actually queries this?"*, and comments with the full blast radius — affected models, dashboards, real production queries, and owners — **before anyone merges**.

Built for **Build with DataHub: The Agent Hackathon**.

---

## Why not just tests?

Blast Radius is a **pre-merge impact review, complementary to CI — not a replacement.** Tests own in-repo assertions. This targets the breaks CI *structurally cannot see*: consumers in other repos, non-code consumers (Tableau/Looker/PowerBI dashboards, ad-hoc analyst SQL), silent semantic breaks (rename, type/unit changes), and cross-system breaks like a backend `@Entity` rename that no test in the backend repo could ever know feeds a finance dashboard. It answers *who downstream this hurts, how much, and who must sign off* — at review time.

## How it works

```
GitHub PR ─▶ GitHub Action ─▶ Agent (Python)
                                 │
              ┌──────────────────┼───────────────────┐
              ▼                  ▼                    ▼
        Diff parser        DataHub (source        LLM (phrasing
        (deterministic)     of truth)             only, at the edge)
                            · downstream lineage
                            · column → queries
                            · usage statistics
                            · ownership
              └──────────────────┬───────────────────┘
                                 ▼
                 PR comment + "Blast Radius" check
                                 │
                                 ▼
      Write-back → DataHub: knowledge doc + tag (Agent Context Kit)
```

**Deterministic core, LLM at the edges.** Every downstream fact comes from DataHub via `blast_radius.datahub_client` — no hallucinated lineage. The LLM only phrases what the graph already proves.

**Reads _and_ writes DataHub through the Agent Context Kit.** Lineage is read through DataHub's [Agent Context Kit](https://docs.datahub.com/docs/dev-guides/agent-context/agent-context) (`datahub-agent-context` — the same tool layer behind DataHub's MCP server), and the verdict is contributed **back** to the graph: a knowledge-base document plus a `blast-radius-breaking` / `blast-radius-review` tag on the affected column, so the next person or agent inherits the impact analysis instead of it being lost in a PR thread. Write-back is opt-in (see below). This is the "**Agents That Do Real Work**" loop: read context → act → write results back.

## Use it as a GitHub Action

Add `.github/workflows/blast-radius.yml` to a data repo (see
[`examples/demo-workflow.yml`](examples/demo-workflow.yml)):

```yaml
name: Blast Radius
on: pull_request
permissions:
  pull-requests: write
  checks: write
  contents: read
jobs:
  blast-radius:
    runs-on: ubuntu-latest
    steps:
      - uses: OWNER/blast-radius@v1
        with:
          datahub-gms-url: ${{ secrets.DATAHUB_GMS_URL }}
          datahub-token:   ${{ secrets.DATAHUB_TOKEN }}      # write-scoped if write-back is on
          link-base:       ${{ secrets.DATAHUB_FRONTEND_URL }}
          write-back:      "true"   # optional: contribute the verdict back to DataHub
```

On every pull request the Action reads the changed `.sql`/`.ddl` files, asks
DataHub what breaks downstream, and posts (and keeps updated) a blast-radius
comment plus a **Blast Radius** check: ❌ breaking → failing, ⚠️ review →
neutral, ✅ safe → success. The check is advisory (non-blocking) unless you make
it a required check. `datahub-gms-url` must be reachable from the runner (a
hosted DataHub, or your instance exposed via a tunnel / self-hosted runner).

With **`write-back: true`** (and a write-scoped `datahub-token`), the Action also
writes the verdict **back** to DataHub via the Agent Context Kit — a knowledge
document and a governance tag on the affected column — so the impact analysis
lives in the catalog, not just the PR. Write-back is **off by default**.

## How DataHub makes this possible

The product is impossible without a context platform. It relies on:
- **Lineage** (`searchAcrossLineage`, downstream, multi-hop) — the blast radius of models, charts, and dashboards.
- **Query subjects** (column-level) — mapping a dropped/renamed column to the exact production queries that break.
- **Usage statistics** (`datasetUsageStatistics`) — usage-weighted severity: who runs what, how often.
- **Ownership** — who to notify.
- **Agent Context Kit** (`datahub-agent-context`) — reads lineage and **writes the verdict back** to the graph (knowledge doc + governance tag), so the analysis is inherited, not lost.

## Repository layout

```
src/blast_radius/
  config.py          # DataHub connection + instance URN settings (env-driven)
  models.py          # result types: LineageNode, QueryRef, Usage, Owner
  datahub_client.py  # deterministic SDK reads (lineage, queries, usage, owners)
  diff_parser.py     # PR diff → schema changes (SQL DDL + dbt output-column diff)
  resolver.py        # change table/model name → real DataHub dataset URN
  severity.py        # usage-weighted ✅/⚠️/❌ verdict (deterministic)
  comment.py         # render the Markdown PR comment (golden-file tested)
  agent.py           # orchestrator: files → Report(verdict, comment, write-back)
  agent_context.py   # DataHub Agent Context Kit boundary — lineage read + write-back
  writeback.py       # render the knowledge doc contributed back to DataHub
  action.py          # GitHub Action entrypoint (blast-radius-review)
action.yml           # composite GitHub Action definition
examples/            # sample outputs + drop-in demo workflow
datapack/            # reproducible demo environment (showcase data + loaders)
tests/               # unit tests (offline) + live integration harness
```

## Setup

Requires Python 3.11 and a running DataHub (`datahub docker quickstart --version v1.6.0`).

```bash
pip install -e ".[dev]"

# seed the demo environment (from the datapack/ dir, relative paths)
cd datapack
python clean_datapack.py 02-data.json
datahub ingest -c recipe-02-clean.yml
python seed_queries.py
cd ..

# verify the graph the agent depends on
pytest -m integration
```

## Status

End-to-end and working. The full pipeline — diff → resolve → DataHub blast radius → usage-weighted verdict → PR comment + check → opt-in write-back — is built and tested (offline unit tests + live integration against a seeded DataHub). See [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for how it was built and [`examples/`](examples/) for sample output.

## Limitations

- v1 scope: dbt models, raw SQL, and schema migrations. Backend `@Entity`/`@Query` awareness is a planned differentiator.
- Graph facts are only as complete as what is ingested into DataHub.
- Write-back documents are not yet deduplicated across PR re-runs (upstream `save_document` mints a new URN per call); planned via search-then-update.

## License

Apache 2.0 — see [LICENSE](LICENSE).
