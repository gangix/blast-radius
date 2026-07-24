"""Seed synthetic-but-realistic query history + usage statistics into DataHub.

Why this exists
---------------
The showcase-ecommerce datapack ships lineage but NO query/usage history
(query entities = 0, Stats disabled). Blast Radius needs it for:
  * usage-weighted severity  — a break matters more if the column is queried
    often and by important people (Wow #4);
  * the demo money-shot      — "dropping this column breaks 14 queries the BI
    team runs weekly, feeding the Order Entry Dashboard."

What it emits (all deterministic + idempotent — safe to re-run)
  * `query` entities with `queryProperties` (real SQL) and `querySubjects`
    linking each query to its dataset AND to the specific columns it reads
    (schemaField-level). The column links are what let the agent map a
    dropped/renamed column to the exact queries that break.
  * `datasetUsageStatistics` timeseries on the hot datasets: per-user counts
    (who runs how much) and per-field counts (how hot each column is), bucketed
    daily across a 30-day window so the Stats tab renders a real trend.

Run:  python datapack/seed_queries.py   (DataHub GMS must be at :8080)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DatahubClientConfig, DataHubGraph
from datahub.metadata.schema_classes import (
    AuditStampClass,
    CalendarIntervalClass,
    DatasetFieldUsageCountsClass,
    DatasetUsageStatisticsClass,
    DatasetUserUsageCountsClass,
    QueryLanguageClass,
    QueryPropertiesClass,
    QuerySourceClass,
    QueryStatementClass,
    QuerySubjectClass,
    QuerySubjectsClass,
    TimeWindowSizeClass,
)

GMS = "http://localhost:8080"
PLATFORM = "snowflake"
PREFIX = "b2fd91"  # datapack instance prefix baked into every URN

def dataset_urn(name: str) -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{PLATFORM},{PREFIX}.{name},PROD)"

def field_urn(ds_urn: str, col: str) -> str:
    return f"urn:li:schemaField:({ds_urn},{col})"

# Real corpuser URNs from the datapack (verified via CorpUserInfo).
U_SARAH = "urn:li:corpuser:b2fd91.sam@example.com"        # Sr Data Analyst, Analytics
U_JAMES = "urn:li:corpuser:b2fd91.jonny2@example.com"     # BI Developer
U_MARCO = "urn:li:corpuser:b2fd91.michael@example.com"    # Sr Software Engineer
U_ANDREA = "urn:li:corpuser:b2fd91.alex@example.com"      # Analytics Engineer
U_PRIYA = "urn:li:corpuser:b2fd91.patrick1@example.com"   # Data Steward
U_DAVID = "urn:li:corpuser:b2fd91.brock1@example.com"     # Data Scientist
U_KAREN = "urn:li:corpuser:b2fd91.kirk@example.com"       # Product Manager

EMAIL = {
    U_SARAH: "sarah.chen@example.com", U_JAMES: "james.wilson@example.com",
    U_MARCO: "marco.santos@example.com", U_ANDREA: "andrea.garcia@example.com",
    U_PRIYA: "priya.sharma@example.com", U_DAVID: "david.kim@example.com",
    U_KAREN: "karen.okonkwo@example.com",
}

ORDER_DETAILS = "order_entry_db.analytics.order_details"
ORDER_HISTORY = "order_entry_db.analytics.order_history"
ORDERS = "order_entry_db.order_entry.orders"
ORDER_ITEMS = "order_entry_db.order_entry.order_items"
CUSTOMERS = "order_entry_db.order_entry.customers"


@dataclass
class QuerySpec:
    id: str
    name: str
    description: str
    sql: str
    dataset: str                 # short dataset name
    columns: list[str]           # columns the query reads (column-level subjects)
    user: str                    # primary author/runner
    runs_per_week: int           # drives usage weighting + Stats buckets


# A believable book of production queries. Every column referenced below exists
# in the real schema (verified). Frequencies encode business criticality.
QUERIES: list[QuerySpec] = [
    QuerySpec(
        "daily-revenue-by-category", "Daily revenue by category",
        "Finance daily revenue rollup feeding the Order Entry Dashboard.",
        "SELECT order_date, category_name,\n"
        "       SUM(line_total)                      AS revenue,\n"
        "       SUM(discount_amount)                 AS discounts,\n"
        "       COUNT(DISTINCT order_id)             AS orders\n"
        "FROM analytics.order_details\n"
        "WHERE order_status = 5\n"
        "GROUP BY order_date, category_name\n"
        "ORDER BY order_date DESC;",
        ORDER_DETAILS, ["order_date", "category_name", "line_total", "discount_amount", "order_id", "order_status"],
        U_SARAH, 42,
    ),
    QuerySpec(
        "net-margin-daily", "Net margin after discounts",
        "CFO daily margin view — net of discounts. Highly sensitive.",
        "SELECT order_date,\n"
        "       SUM(line_total - discount_amount)    AS net_revenue,\n"
        "       AVG(discount_percent)                AS avg_discount_pct\n"
        "FROM analytics.order_details\n"
        "GROUP BY order_date;",
        ORDER_DETAILS, ["order_date", "line_total", "discount_amount", "discount_percent"],
        U_JAMES, 35,
    ),
    QuerySpec(
        "aov-by-region", "Average order value by region",
        "Weekly AOV by shipping region for the commercial team.",
        "SELECT shipping_region,\n"
        "       SUM(order_total) / COUNT(DISTINCT order_id) AS aov\n"
        "FROM analytics.order_details\n"
        "GROUP BY shipping_region;",
        ORDER_DETAILS, ["shipping_region", "order_total", "order_id"],
        U_SARAH, 20,
    ),
    QuerySpec(
        "top-customers-90d", "Top customers (trailing 90d)",
        "Account management: highest-value customers by spend.",
        "SELECT customer_id, cust_email,\n"
        "       SUM(order_total) AS lifetime_value\n"
        "FROM analytics.order_details\n"
        "GROUP BY customer_id, cust_email\n"
        "ORDER BY lifetime_value DESC\n"
        "LIMIT 100;",
        ORDER_DETAILS, ["customer_id", "cust_email", "order_total"],
        U_KAREN, 12,
    ),
    QuerySpec(
        "delivery-sla", "Delivery SLA breach rate",
        "Ops dashboard: share of orders past estimated delivery.",
        "SELECT warehouse_name, delivery_status,\n"
        "       COUNT(*) AS orders\n"
        "FROM analytics.order_details\n"
        "GROUP BY warehouse_name, delivery_status;",
        ORDER_DETAILS, ["warehouse_name", "delivery_status"],
        U_ANDREA, 15,
    ),
    QuerySpec(
        "returns-by-product", "Returns by product",
        "Merchandising: return rate per product.",
        "SELECT product_name, return_status,\n"
        "       COUNT(*) AS n\n"
        "FROM analytics.order_details\n"
        "GROUP BY product_name, return_status;",
        ORDER_DETAILS, ["product_name", "return_status"],
        U_DAVID, 8,
    ),
    QuerySpec(
        "order-status-funnel", "Order status funnel",
        "Live order pipeline by status from the raw orders table.",
        "SELECT order_status, COUNT(*) AS orders, SUM(order_total) AS value\n"
        "FROM order_entry.orders\n"
        "GROUP BY order_status;",
        ORDERS, ["order_status", "order_total"],
        U_MARCO, 30,
    ),
    QuerySpec(
        "orders-by-day", "Orders by day",
        "Volume trend used by the analytics team.",
        "SELECT order_date, COUNT(*) AS orders\n"
        "FROM order_entry.orders\n"
        "GROUP BY order_date;",
        ORDERS, ["order_date"],
        U_SARAH, 18,
    ),
    QuerySpec(
        "fulfilment-cost", "Fulfilment cost per warehouse",
        "Ops: cost of delivery by warehouse.",
        "SELECT warehouse_id, SUM(cost_of_delivery) AS delivery_cost\n"
        "FROM order_entry.orders\n"
        "GROUP BY warehouse_id;",
        ORDERS, ["warehouse_id", "cost_of_delivery"],
        U_ANDREA, 6,
    ),
    QuerySpec(
        "order-value-history", "Order value history (SCD)",
        "Point-in-time order totals for trend reporting.",
        "SELECT as_of_date, SUM(order_total) AS total_value\n"
        "FROM analytics.order_history\n"
        "GROUP BY as_of_date;",
        ORDER_HISTORY, ["as_of_date", "order_total"],
        U_JAMES, 9,
    ),
    QuerySpec(
        "basket-size", "Average basket size",
        "Items per order from line items.",
        "SELECT order_id, SUM(quantity) AS items, SUM(unit_price*quantity) AS gross\n"
        "FROM order_entry.order_items\n"
        "GROUP BY order_id;",
        ORDER_ITEMS, ["order_id", "quantity", "unit_price"],
        U_DAVID, 5,
    ),
    QuerySpec(
        "customer-credit-exposure", "Customer credit exposure",
        "Finance: outstanding exposure vs credit limit.",
        "SELECT customer_id, credit_limit, customer_class\n"
        "FROM order_entry.customers\n"
        "WHERE credit_limit > 0;",
        CUSTOMERS, ["customer_id", "credit_limit", "customer_class"],
        U_PRIYA, 4,
    ),
]


def audit(ts_ms: int, actor: str) -> AuditStampClass:
    return AuditStampClass(time=ts_ms, actor=actor)


def main() -> None:
    graph = DataHubGraph(DatahubClientConfig(server=GMS))
    now = datetime.now(UTC)
    now_ms = int(now.timestamp() * 1000)

    # ---- 1. Query entities (properties + dataset/column subjects) -----------
    n_queries = 0
    for q in QUERIES:
        ds = dataset_urn(q.dataset)
        query_urn = f"urn:li:query:blast-radius-{q.id}"
        subjects = [QuerySubjectClass(entity=ds)]
        subjects += [QuerySubjectClass(entity=field_urn(ds, c)) for c in q.columns]

        props = QueryPropertiesClass(
            statement=QueryStatementClass(value=q.sql, language=QueryLanguageClass.SQL),
            source=QuerySourceClass.MANUAL,
            created=audit(now_ms, q.user),
            lastModified=audit(now_ms, q.user),
            name=q.name,
            description=f"{q.description}  (~{q.runs_per_week} runs/week)",
        )
        for aspect in (props, QuerySubjectsClass(subjects=subjects)):
            graph.emit(MetadataChangeProposalWrapper(entityUrn=query_urn, aspect=aspect))
        n_queries += 1

    # ---- 2. Usage statistics per dataset (daily buckets, 30-day window) -----
    # Aggregate query specs per dataset into per-user and per-field weekly counts.
    by_dataset: dict[str, list[QuerySpec]] = {}
    for q in QUERIES:
        by_dataset.setdefault(q.dataset, []).append(q)

    DAYS = 30
    granularity = TimeWindowSizeClass(unit=CalendarIntervalClass.DAY, multiple=1)
    n_usage = 0
    for ds_name, specs in by_dataset.items():
        ds = dataset_urn(ds_name)

        # weekly -> daily rate, with a mild weekday pattern for realism.
        user_week: dict[str, int] = {}
        field_week: dict[str, int] = {}
        for q in specs:
            user_week[q.user] = user_week.get(q.user, 0) + q.runs_per_week
            for c in q.columns:
                field_week[c] = field_week.get(c, 0) + q.runs_per_week

        for d in range(DAYS):
            day = (now - timedelta(days=DAYS - 1 - d)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ts = int(day.timestamp() * 1000)
            weekday = day.weekday()  # 0=Mon .. 6=Sun
            factor = 0.3 if weekday >= 5 else 1.0  # quieter weekends

            user_counts = [
                DatasetUserUsageCountsClass(
                    user=u, count=max(1, round(w / 7 * factor)), userEmail=EMAIL.get(u)
                )
                for u, w in sorted(user_week.items(), key=lambda kv: -kv[1])
            ]
            field_counts = [
                DatasetFieldUsageCountsClass(fieldPath=c, count=max(1, round(w / 7 * factor)))
                for c, w in sorted(field_week.items(), key=lambda kv: -kv[1])
            ]
            total = sum(uc.count for uc in user_counts)

            usage = DatasetUsageStatisticsClass(
                timestampMillis=ts,
                eventGranularity=granularity,
                uniqueUserCount=len(user_counts),
                totalSqlQueries=total,
                topSqlQueries=[q.name for q in sorted(specs, key=lambda s: -s.runs_per_week)][:5],
                userCounts=user_counts,
                fieldCounts=field_counts,
            )
            graph.emit(MetadataChangeProposalWrapper(entityUrn=ds, aspect=usage))
            n_usage += 1

    print(f"Emitted {n_queries} query entities and {n_usage} daily usage buckets "
          f"across {len(by_dataset)} datasets.")


if __name__ == "__main__":
    main()
