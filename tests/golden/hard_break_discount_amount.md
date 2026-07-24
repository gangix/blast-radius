<!-- blast-radius:v1 -->

## ❌ Blast Radius — Breaking change

**1 breaking** across 1 change.

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

---
_Deterministic analysis from DataHub lineage + 30-day query history._
