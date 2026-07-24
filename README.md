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
                 PR comment + suggested patches
                                 │
                                 ▼
                 Write-back: impact record → DataHub
```

**Deterministic core, LLM at the edges.** Every downstream fact comes from DataHub via `blast_radius.datahub_client` — no hallucinated lineage. The LLM only phrases what the graph already proves.

## How DataHub makes this possible

The product is impossible without a context platform. It relies on:
- **Lineage** (`searchAcrossLineage`, downstream, multi-hop) — the blast radius of models, charts, and dashboards.
- **Query subjects** (column-level) — mapping a dropped/renamed column to the exact production queries that break.
- **Usage statistics** (`datasetUsageStatistics`) — usage-weighted severity: who runs what, how often.
- **Ownership** — who to notify.

## Repository layout

```
src/blast_radius/
  config.py          # DataHub connection + instance URN settings (env-driven)
  models.py          # result types: LineageNode, QueryRef, Usage, Owner
  datahub_client.py  # the only module that talks to DataHub (deterministic)
datapack/            # reproducible demo environment (showcase data + loaders)
  clean_datapack.py  # strips server-unknown aspects so lineage ingests cleanly
  seed_queries.py    # seeds query history + usage statistics
tests/               # integration tests = live seed-verification harness
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

Foundation complete and verified: lineage traverses 5 hops to named dashboards; query history + usage statistics seeded; column→break mapping proven. Agent core (diff parser → severity → PR comment → write-back) in progress. See `BLAST_RADIUS_PROJECT.md` and `RISKS.md`.

## Limitations

- v1 scope: dbt models, raw SQL, and schema migrations. Backend `@Entity`/`@Query` awareness is a planned differentiator.
- Graph facts are only as complete as what is ingested into DataHub.

## License

Apache 2.0 — see [LICENSE](LICENSE).
