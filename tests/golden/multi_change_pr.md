<!-- blast-radius:v1 -->

## ❌ Blast Radius — Breaking change

**1 breaking, 1 warning** across 3 changes.

| Change | Verdict | Impact |
|---|---|---|
| Drop column `discount_amount` | ❌ Breaking change | 2 queries · ~11 reads/day |
| Drop column `warehouse_name` | ⚠️ Review before merge | 1 query · ~2 reads/day |
| Drop column `gift_wrap` | ✅ No downstream impact | no query usage |

### ❌ Drop column `discount_amount`

- Dropping `discount_amount` affects 2 production queries (~11 reads/day).
- Run by 2 people in the last 30 days.
- `analytics.order_details` feeds 3 dashboards downstream.

**Breaking queries**

| Query | Author |
|---|---|
| Daily revenue by category | sarah |
| Net margin after discounts | james |

<details><summary>SQL — Daily revenue by category</summary>

```sql
SELECT ...
FROM order_details
```

</details>

<details><summary>SQL — Net margin after discounts</summary>

```sql
SELECT ...
FROM order_details
```

</details>

**Downstream of `analytics.order_details`** (table-level; field bindings not verified):
- [Dashboard 0](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd0%29)
- [Dashboard 1](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd1%29)
- [Dashboard 2](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd2%29)

**Owners (from DataHub):** finance-team

### ⚠️ Drop column `warehouse_name`

- Dropping `warehouse_name` affects 1 production query (~2 reads/day).
- Run by 1 person in the last 30 days.
- `analytics.order_details` feeds 1 dashboard downstream.

**Breaking queries**

| Query | Author |
|---|---|
| Delivery SLA breach rate | andrea |

<details><summary>SQL — Delivery SLA breach rate</summary>

```sql
SELECT ...
FROM order_details
```

</details>

**Downstream of `analytics.order_details`** (table-level; field bindings not verified):
- [Dashboard 0](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd0%29)

<details>
<summary>✅ Drop column `gift_wrap`</summary>

- No production query or usage has referenced `gift_wrap` in the last 30 days.
- `analytics.order_details` feeds 3 dashboards downstream, but none of the tracked queries read `gift_wrap`. (BI field-level bindings aren't verified.)

**Downstream of `analytics.order_details`** (table-level; field bindings not verified):
- [Dashboard 0](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd0%29)
- [Dashboard 1](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd1%29)
- [Dashboard 2](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd2%29)

</details>

---
_Deterministic analysis from DataHub lineage + 30-day query history._
