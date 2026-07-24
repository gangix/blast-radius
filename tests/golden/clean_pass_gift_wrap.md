<!-- blast-radius:v1 -->

## ✅ Blast Radius — No downstream impact

No downstream impact detected across 1 change. Safe to merge.

### ✅ Drop column `gift_wrap`

- No production query or usage has referenced `gift_wrap` in the last 30 days.
- `analytics.order_details` feeds 3 dashboards downstream, but none of the tracked queries read `gift_wrap`. (BI field-level bindings aren't verified.)

**Downstream of `analytics.order_details`** (table-level; field bindings not verified):
- [Dashboard 0](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd0%29)
- [Dashboard 1](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd1%29)
- [Dashboard 2](https://datahub.example.com/dashboard/urn%3Ali%3Adashboard%3A%28tableau%2Cd2%29)

---
_Deterministic analysis from DataHub lineage + 30-day query history._
