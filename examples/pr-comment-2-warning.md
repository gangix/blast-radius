<!-- blast-radius:v1 -->

## ⚠️ Blast Radius — Review before merge

**1 warning** across 1 change.

### ⚠️ Drop column `warehouse_name`

- Dropping `warehouse_name` affects 1 production query (~2 reads/day).
- Run by 1 person in the last 30 days.
- `order_entry_db.analytics.order_details` feeds 3 dashboards and 12 charts downstream.

**Breaking queries**

| Query | Author |
|---|---|
| Delivery SLA breach rate | Andrea Garcia |

<details><summary>SQL — Delivery SLA breach rate</summary>

```sql
SELECT warehouse_name, delivery_status,
       COUNT(*) AS orders
FROM analytics.order_details
GROUP BY warehouse_name, delivery_status;
```

</details>

**Downstream of `order_entry_db.analytics.order_details`** (table-level; field bindings not verified):
- [Order Entry Dashboard](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cb2fd91.843bf583-900b-f1ba-0532-b5e67a0373dc%29)
- [datahub_order_entries](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28powerbi%2Cb2fd91.reports.66666666-7777-8888-9999-000000000000%29)
- [Orders By Month](https://datahub.example.com/chart/urn%3Ali%3Achart%3A%28tableau%2Cb2fd91.89f38fd7-058d-b66a-6db0-4f85f105468a%29)
- [Popular Products Categories](https://datahub.example.com/chart/urn%3Ali%3Achart%3A%28tableau%2Cb2fd91.b8c660a8-10ea-e32a-b823-fa655e1c2f43%29)
- [Promotions](https://datahub.example.com/chart/urn%3Ali%3Achart%3A%28tableau%2Cb2fd91.e051d978-989f-a329-5458-e01721b05570%29)
- [Order Mode](https://datahub.example.com/chart/urn%3Ali%3Achart%3A%28tableau%2Cb2fd91.e36d7772-ac4d-4fd0-a893-aec88f3aa13e%29)
- [Order Entry Dashboard](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28looker%2Cb2fd91.dashboards.53%29)
- [Popular Products](https://datahub.example.com/chart/urn%3Ali%3Achart%3A%28looker%2Cb2fd91.dashboard_elements.221%29)
- …and 7 more

**Owners (from DataHub):** DataHub SE Team, David Kim, Julia Novak

---
_Deterministic analysis from DataHub lineage + 30-day query history._
