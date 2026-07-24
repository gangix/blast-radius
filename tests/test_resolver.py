"""Tests for the table-name -> dataset-URN resolver.

Pure matching tests (synthetic catalogue, no DataHub) + integration tests that
close the review's key gap: a parsed diff Change must resolve to a URN that
actually exists in DataHub.
"""

from __future__ import annotations

import pytest

from blast_radius import (
    Change,
    ChangeKind,
    DataHubClient,
    DiffParser,
    FileChange,
    FileStatus,
    TableResolver,
)
from blast_radius.resolver import _Entry, _segments, match_table, parse_dataset_urn

PREFIX = "b2fd91"


def entry(urn_name: str, platform: str) -> _Entry:
    """Build a catalogue entry from a platform + prefixed dotted name."""
    full = f"urn:li:dataset:(urn:li:dataPlatform:{platform},{urn_name},PROD)"
    return _Entry(full, platform, _segments(urn_name, PREFIX))


# A synthetic catalogue mirroring the real showcase shape.
CATALOG = [
    entry("b2fd91.order_entry_db.analytics.order_details", "snowflake"),
    entry("b2fd91.ORDER_ENTRY_DB.analytics.order_details", "dbt"),
    entry("b2fd91.order-entry-looker.view.order_details", "looker"),
    entry("b2fd91.order_entry_db.order_entry.orders", "snowflake"),
    entry("b2fd91.order_entry_db.order_entry.orders", "dbt"),
    entry("b2fd91.order_entry_db.analytics.order_details_replica", "snowflake"),
    entry("b2fd91.order_entry_db.analytics.order_history", "snowflake"),
]


# ------------------------------------------------------------- pure matching
def test_parse_dataset_urn():
    plat, name = parse_dataset_urn(
        "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.db.schema.t,PROD)"
    )
    assert plat == "snowflake"
    assert name == "b2fd91.db.schema.t"


def test_exact_fully_qualified_match():
    r = match_table("order_entry_db.analytics.order_details", CATALOG, instance_prefix=PREFIX)
    assert r is not None
    assert r.platform == "snowflake"
    assert r.exact and r.score == 1.0


def test_two_part_suffix_match():
    r = match_table("analytics.order_details", CATALOG, instance_prefix=PREFIX)
    assert r is not None
    assert r.platform == "snowflake"
    assert r.matched_name == "order_entry_db.analytics.order_details"
    assert not r.exact and r.score == 0.9


def test_bare_stem_prefers_warehouse_over_bi_and_dbt():
    r = match_table("order_details", CATALOG, instance_prefix=PREFIX)
    assert r is not None
    assert r.platform == "snowflake"          # not looker, not dbt
    # the dbt + looker copies come along as candidates
    assert any(":dbt," in c for c in r.candidates)
    assert any(":looker," in c for c in r.candidates)


def test_case_insensitive():
    r = match_table("ORDER_ENTRY_DB.ANALYTICS.ORDER_DETAILS", CATALOG, instance_prefix=PREFIX)
    assert r is not None and r.platform == "snowflake"


def test_stem_does_not_match_replica():
    # "order_details" must not match "order_details_replica" (different last segment)
    r = match_table("order_details", CATALOG, instance_prefix=PREFIX)
    assert "replica" not in r.urn


def test_prefer_platform_override():
    r = match_table("order_details", CATALOG, instance_prefix=PREFIX, prefer_platform="dbt")
    assert r is not None and r.platform == "dbt"


def test_unknown_table_returns_none():
    assert match_table("does_not_exist", CATALOG, instance_prefix=PREFIX) is None


# ------------------------------------------------------------- integration
pytestmark_integration = pytest.mark.integration


@pytest.fixture(scope="module")
def resolver() -> TableResolver:
    client = DataHubClient()
    try:
        if not client.exists(client.dataset_urn("order_entry_db.order_entry.orders")):
            pytest.skip("DataHub reachable but demo data not seeded")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DataHub not reachable: {exc}")
    return TableResolver(client)


@pytest.mark.integration
@pytest.mark.parametrize(
    "written",
    [
        "order_entry_db.analytics.order_details",  # fully qualified
        "analytics.order_details",                 # schema.table
        "order_details",                           # bare dbt stem
        "orders",
        "order_entry.orders",
    ],
)
def test_resolves_to_existing_urn(resolver: TableResolver, written: str):
    resolved = resolver.resolve(written)
    assert resolved is not None, f"{written!r} did not resolve"
    assert resolver.client.exists(resolved.urn), f"{resolved.urn} does not exist"


@pytest.mark.integration
def test_change_from_migration_resolves_and_exists(resolver: TableResolver):
    changes = DiffParser().parse(
        [FileChange("migrations/V9.sql", status=FileStatus.ADDED,
                    new_content="ALTER TABLE analytics.order_details DROP COLUMN discount_amount;")]
    )
    assert len(changes) == 1
    resolved = resolver.resolve_change(changes[0])
    assert resolved is not None
    assert resolved.platform == "snowflake"
    assert resolver.client.exists(resolved.urn)


@pytest.mark.integration
def test_unknown_change_resolves_to_none(resolver: TableResolver):
    change = Change(ChangeKind.DROP_COLUMN, "totally_made_up_table", column="x")
    assert resolver.resolve_change(change) is None
