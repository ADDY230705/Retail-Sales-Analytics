# Retail Sales Analytics — SQL & Python Data Engineering Project

## Overview
An end-to-end analytics pipeline that takes raw, transactional-style
e-commerce data (customers, products, orders) and transforms it into a
**dimensional star schema**, then answers real business questions with
SQL — including a correctly implemented **Slowly Changing Dimension
(Type 2)** for customer region history.

## Architecture

```
Raw source data (CSV)          ETL (Python)              Analytics (SQL)
─────────────────────         ──────────────            ─────────────────
customers.csv          ┐
customer_region_        ├──►  etl.py  ──►  retail.db  ──►  analytics_queries.sql
  changes.csv          │      (star schema,               (window functions,
products.csv           │       SCD2 logic,                 CTEs, cohort
order_items.csv        ┘       dedup)                       analysis)
```

## Star Schema

**Grain of `fact_sales`: one row per order line item.**

| Table | Type | Notes |
|---|---|---|
| `dim_customer` | SCD Type 2 | Tracks region history — a customer's region at time of sale is preserved, not overwritten |
| `dim_product` | SCD Type 1 | Overwrite-on-change (no history needed for this scope) |
| `dim_date` | Conformed date dimension | Generated, covers full data range |
| `fact_sales` | Fact table | quantity, unit_price, discount_pct, net_revenue |

## Why SCD Type 2 for customer region

If a customer relocates, overwriting their region (SCD1) would silently
reassign ALL their historical sales to the new region — corrupting past
reports. SCD2 keeps every version of the customer with `valid_from` /
`valid_to` dates, so each sale joins to the region that was actually
current **at the time of that sale**.

**Proof it matters (from `analytics_queries.sql`, Q5):**

| Method | East | North | South | West |
|---|---|---|---|---|
| SCD2-correct | 614,786 | 553,454 | 532,966 | 670,810 |
| Naive (current-region-only) | 638,270 | 572,317 | 531,909 | 629,520 |

The naive approach misattributes tens of thousands in revenue per
region — a concrete, quantified example of why SCD2 matters.

## Data quality handling
- Removed 15 exact duplicate order line items during transform
- Fixed a data-generation bug where orders could predate a customer's
  signup date (temporal integrity check) — a good example of validating
  business logic, not just null/duplicate checks

## Key SQL techniques demonstrated
- Window functions: `LAG()` for month-over-month growth, `RANK() OVER (PARTITION BY ...)` for top-N-per-group
- CTEs for readable multi-step transformations (cohort analysis)
- Point-in-time dimension joins (SCD2 pattern)

## How to run
```bash
pip install faker
python3 generate_data.py   # creates raw CSVs in data/raw/
python3 etl.py              # builds retail.db (SQLite) with star schema
sqlite3 retail.db < analytics_queries.sql   # or run queries individually
```

## Sample result: Top 3 products by revenue per category
| Category | Product | Revenue | Rank |
|---|---|---|---|
| Apparel | Denim Jacket v2 | 122,452 | 1 |
| Electronics | Wireless Mouse v2 | 95,895 | 1 |
| Home | Desk Lamp v1 | 105,110 | 1 |

## Tech stack
Python (data generation, ETL orchestration), SQL (DDL, window functions,
CTEs), SQLite (portable — swap for PostgreSQL by changing the connection
layer, schema is standard ANSI SQL)

## Possible extensions
- Orchestrate with Airflow instead of a manual script run
- Move to PostgreSQL/Snowflake for production-scale querying
- Add a BI layer (Power BI / Metabase) on top of `retail.db`
- Add automated data quality tests (e.g., Great Expectations)
