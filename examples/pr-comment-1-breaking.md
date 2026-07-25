<!-- blast-radius:v1 -->

## ❌ Blast Radius — Breaking change

**1 breaking** across 1 change.

### ❌ Drop column `discount_amount`

- Dropping `discount_amount` affects 2 production queries (~11 reads/day).
- Run by 2 people in the last 30 days.
- `order_entry_db.analytics.order_details` feeds 3 dashboards and 12 charts downstream.

**Breaking queries**

| Query | Author |
|---|---|
| Daily revenue by category | Sarah Chen |
| Net margin after discounts | James Wilson |

<details><summary>SQL — Daily revenue by category</summary>

```sql
SELECT order_date, category_name,
       SUM(line_total)                      AS revenue,
       SUM(discount_amount)                 AS discounts,
       COUNT(DISTINCT order_id)             AS orders
FROM analytics.order_details
WHERE order_status = 5
GROUP BY order_date, category_name
ORDER BY order_date DESC;
```

</details>

<details><summary>SQL — Net margin after discounts</summary>

```sql
SELECT order_date,
       SUM(line_total - discount_amount)    AS net_revenue,
       AVG(discount_percent)                AS avg_discount_pct
FROM analytics.order_details
GROUP BY order_date;
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
