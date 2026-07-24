"""Integration tests for DataHubClient.

These run against a live DataHub seeded with the showcase datapack + query seed
(``datapack/clean_datapack.py`` + ``datapack/seed_queries.py``). They double as
a verification harness for the demo environment: if these pass, the graph the
agent relies on is correctly seeded. Skipped automatically if DataHub is
unreachable so the suite stays green on machines without the stack up.
"""

from __future__ import annotations

import pytest

from blast_radius import DataHubClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client() -> DataHubClient:
    c = DataHubClient()
    orders = c.dataset_urn("order_entry_db.order_entry.orders")
    try:
        reachable = c.exists(orders)
    except Exception as exc:  # noqa: BLE001 - any transport error means "no stack"
        pytest.skip(f"DataHub not reachable: {exc}")
    if not reachable:
        pytest.skip("DataHub reachable but demo data not seeded (run the datapack loaders)")
    return c


def test_urn_roundtrip(client: DataHubClient) -> None:
    ds = client.dataset_urn("order_entry_db.analytics.order_details")
    col = client.field_urn(ds, "discount_amount")
    assert client.parse_schema_field(col) == (ds, "discount_amount")


def test_downstream_orders_reaches_dashboards(client: DataHubClient) -> None:
    orders = client.dataset_urn("order_entry_db.order_entry.orders")
    nodes = client.downstream(orders)

    assert nodes, "orders should have downstream lineage"
    types = {n.entity_type for n in nodes}
    assert "DASHBOARD" in types, f"expected dashboards downstream, got {types}"
    assert any(n.is_consumer for n in nodes)
    # multi-hop: dashboards are several hops past the raw table
    assert max(n.degree for n in nodes) >= 2


def test_drop_discount_amount_breaks_named_queries(client: DataHubClient) -> None:
    order_details = client.dataset_urn("order_entry_db.analytics.order_details")
    hits = client.queries_for_column(order_details, "discount_amount")

    names = {q.name for q in hits}
    assert {"Daily revenue by category", "Net margin after discounts"} <= names, names
    # every hit must actually carry the column link (no false positives)
    assert all(q.references_column(order_details, "discount_amount") for q in hits)


def test_clean_column_breaks_nothing(client: DataHubClient) -> None:
    order_details = client.dataset_urn("order_entry_db.analytics.order_details")
    # a real column that no seeded query reads -> a genuine clean-pass signal
    assert client.queries_for_column(order_details, "gift_wrap") == []


def test_usage_is_populated(client: DataHubClient) -> None:
    order_details = client.dataset_urn("order_entry_db.analytics.order_details")
    usage = client.usage(order_details)

    assert usage is not None
    assert usage.total_queries > 0
    assert usage.unique_users > 0
    assert usage.field_query_count("discount_amount") > 0


def test_owners_resolve_to_people(client: DataHubClient) -> None:
    # The PowerBI dashboard has registered owners in the datapack.
    dashboard = "urn:li:dashboard:(powerbi,b2fd91.reports.66666666-7777-8888-9999-000000000000)"
    owners = client.owners(dashboard)
    assert owners, "expected registered owners"
    assert any(o.name or o.email for o in owners), "owners should resolve to a human handle"
