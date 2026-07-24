"""Unit tests for the deterministic diff parser (no DataHub needed)."""

from __future__ import annotations

from blast_radius import Change, ChangeKind, DiffParser, FileChange, FileStatus


def parse_sql(sql: str, path: str = "migrations/V3__change.sql",
              old: str | None = None) -> list[Change]:
    status = FileStatus.MODIFIED if old is not None else FileStatus.ADDED
    return DiffParser().parse_file(
        FileChange(path=path, old_content=old, new_content=sql, status=status)
    )


def kinds(changes: list[Change]) -> set[ChangeKind]:
    return {c.kind for c in changes}


# --------------------------------------------------------------- DDL: columns
def test_drop_column():
    changes = parse_sql("ALTER TABLE order_entry.orders DROP COLUMN discount_amount;")
    assert len(changes) == 1
    c = changes[0]
    assert c.kind is ChangeKind.DROP_COLUMN
    assert c.table == "order_entry.orders"
    assert c.column == "discount_amount"
    assert c.potentially_breaking


def test_rename_column():
    changes = parse_sql("ALTER TABLE orders RENAME COLUMN order_total TO gross_total;")
    assert len(changes) == 1
    c = changes[0]
    assert c.kind is ChangeKind.RENAME_COLUMN
    assert (c.old, c.new) == ("order_total", "gross_total")
    assert c.potentially_breaking


def test_add_column_is_not_breaking():
    changes = parse_sql("ALTER TABLE orders ADD COLUMN loyalty_tier VARCHAR(20);")
    assert kinds(changes) == {ChangeKind.ADD_COLUMN}
    assert changes[0].column == "loyalty_tier"
    assert not changes[0].potentially_breaking


def test_alter_column_type():
    changes = parse_sql("ALTER TABLE orders ALTER COLUMN order_total SET DATA TYPE NUMBER(38,4);")
    assert changes[0].kind is ChangeKind.ALTER_COLUMN_TYPE
    assert changes[0].column == "order_total"
    assert changes[0].new.startswith("NUMBER")


def test_modify_column_type_mysql_style():
    changes = parse_sql("ALTER TABLE orders MODIFY COLUMN order_total DECIMAL(18,2);")
    assert changes[0].kind is ChangeKind.ALTER_COLUMN_TYPE
    assert changes[0].column == "order_total"


def test_multiple_actions_one_statement():
    changes = parse_sql(
        "ALTER TABLE orders DROP COLUMN promotion_id, ADD COLUMN channel VARCHAR(10);"
    )
    assert kinds(changes) == {ChangeKind.DROP_COLUMN, ChangeKind.ADD_COLUMN}


def test_add_column_if_not_exists():
    changes = parse_sql("ALTER TABLE orders ADD COLUMN IF NOT EXISTS loyalty_tier VARCHAR(20);")
    assert kinds(changes) == {ChangeKind.ADD_COLUMN}
    assert changes[0].column == "loyalty_tier"


# --- regression: table-level object changes must NOT read as column changes ---
def test_drop_constraint_is_not_a_column_drop():
    changes = parse_sql("ALTER TABLE orders DROP CONSTRAINT fk_orders_customer;")
    assert changes == [], f"constraint drop must not be a column change, got {changes}"


def test_drop_primary_key_is_not_a_column_drop():
    changes = parse_sql("ALTER TABLE orders DROP PRIMARY KEY;")
    assert changes == []


def test_add_constraint_is_not_a_column_add():
    changes = parse_sql(
        "ALTER TABLE order_items ADD CONSTRAINT fk_oi_order FOREIGN KEY (order_id) "
        "REFERENCES orders(order_id);"
    )
    assert changes == []


def test_real_column_drop_still_detected_alongside_constraint():
    changes = parse_sql(
        "ALTER TABLE orders DROP CONSTRAINT fk_x, DROP COLUMN discount_amount;"
    )
    assert kinds(changes) == {ChangeKind.DROP_COLUMN}
    assert changes[0].column == "discount_amount"


def test_quoted_identifiers():
    changes = parse_sql('ALTER TABLE "OrderDB"."Orders" DROP COLUMN "Discount_Amount";')
    c = changes[0]
    assert c.table == "OrderDB.Orders"
    assert c.column == "Discount_Amount"


# ---------------------------------------------------------------- DDL: tables
def test_drop_table():
    changes = parse_sql("DROP TABLE IF EXISTS analytics.order_history;")
    assert changes[0].kind is ChangeKind.DROP_TABLE
    assert changes[0].table == "analytics.order_history"


def test_rename_table():
    changes = parse_sql("ALTER TABLE orders RENAME TO orders_v2;")
    assert changes[0].kind is ChangeKind.RENAME_TABLE
    assert (changes[0].old, changes[0].new) == ("orders", "orders_v2")


def test_create_table_is_not_breaking():
    changes = parse_sql("CREATE TABLE analytics.new_mart (id INT, total FLOAT);")
    assert kinds(changes) == {ChangeKind.CREATE_TABLE}
    assert not changes[0].potentially_breaking


def test_modified_file_reports_only_new_statements():
    old = "CREATE TABLE orders (id INT);"
    new = "CREATE TABLE orders (id INT);\nALTER TABLE orders DROP COLUMN id;"
    changes = parse_sql(new, old=old)
    assert kinds(changes) == {ChangeKind.DROP_COLUMN}  # the pre-existing CREATE is ignored


def test_comments_ignored():
    changes = parse_sql(
        "-- drop the column below\nALTER TABLE orders DROP COLUMN discount_amount; -- done"
    )
    assert kinds(changes) == {ChangeKind.DROP_COLUMN}


# ------------------------------------------------------------------- dbt path
DBT_PATH = "models/marts/order_details.sql"
DBT_BEFORE = """
{{ config(materialized='table') }}
select
    order_id,
    order_total,
    discount_amount,
    category_name
from {{ ref('stg_order_details') }}
"""


def test_dbt_drop_column():
    after = DBT_BEFORE.replace("    discount_amount,\n", "")
    changes = DiffParser().parse_file(
        FileChange(DBT_PATH, old_content=DBT_BEFORE, new_content=after)
    )
    drops = [c for c in changes if c.kind is ChangeKind.DROP_COLUMN]
    assert [c.column for c in drops] == ["discount_amount"]
    assert drops[0].table == "order_details"
    assert drops[0].confidence == "medium"


def test_dbt_add_column():
    after = DBT_BEFORE.replace(
        "    category_name\n", "    category_name,\n    net_total\n"
    )
    changes = DiffParser().parse_file(
        FileChange(DBT_PATH, old_content=DBT_BEFORE, new_content=after)
    )
    assert kinds(changes) == {ChangeKind.ADD_COLUMN}
    assert changes[0].column == "net_total"


def test_dbt_select_star_is_logic_change():
    old = "{{ config(materialized='view') }}\nselect * from {{ ref('orders') }}"
    new = "{{ config(materialized='view') }}\nselect *, 1 as flag from {{ ref('orders') }}"
    changes = DiffParser().parse_file(FileChange(DBT_PATH, old_content=old, new_content=new))
    assert kinds(changes) == {ChangeKind.LOGIC_CHANGE}
    assert changes[0].potentially_breaking


def test_dbt_model_deleted_is_drop_table():
    changes = DiffParser().parse_file(
        FileChange(DBT_PATH, old_content=DBT_BEFORE, new_content=None,
                   status=FileStatus.REMOVED)
    )
    assert changes[0].kind is ChangeKind.DROP_TABLE
    assert changes[0].table == "order_details"


def test_new_dbt_model_breaks_nothing():
    changes = DiffParser().parse_file(
        FileChange(DBT_PATH, old_content=None, new_content=DBT_BEFORE,
                   status=FileStatus.ADDED)
    )
    assert changes == []


# ------------------------------------------------------------------- non-SQL
def test_non_sql_files_ignored():
    assert DiffParser().parse_file(FileChange("README.md", new_content="# hi")) == []
    assert DiffParser().parse_file(
        FileChange("app/main.py", new_content="print('x')")
    ) == []


def test_parse_batches_multiple_files():
    files = [
        FileChange("migrations/V4.sql", new_content="ALTER TABLE orders DROP COLUMN a;",
                   status=FileStatus.ADDED),
        FileChange("README.md", new_content="docs"),
    ]
    changes = DiffParser().parse(files)
    assert len(changes) == 1 and changes[0].column == "a"
