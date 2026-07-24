<!-- blast-radius:v1 -->

## ⚠️ Blast Radius — Review before merge

**1 warning** across 1 change.

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

---
_Deterministic analysis from DataHub lineage + 30-day query history._
