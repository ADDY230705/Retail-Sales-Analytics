"""
etl.py
------
Transforms raw source CSVs into the star schema defined in schema.sql,
and loads everything into a SQLite database (retail.db).

Pipeline stages (this is the "E-T-L" story to tell in an interview):
  1. EXTRACT : read raw CSVs (data/raw/)
  2. TRANSFORM:
       - data quality: drop duplicate order line items
       - build dim_customer with SCD Type 2 versioning
       - build dim_product (straight load)
       - build dim_date (generated, not from source)
       - build fact_sales with surrogate key lookups + derived net_revenue
  3. LOAD    : write everything into retail.db (SQLite) using schema.sql
"""

import csv
import sqlite3
from datetime import date, timedelta

DB_PATH = "retail.db"


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def build_dim_date(conn, min_date, max_date):
    """Generate a full date dimension covering the range of our data."""
    rows = []
    d = min_date
    while d <= max_date:
        date_sk = int(d.strftime("%Y%m%d"))
        rows.append((
            date_sk, d.isoformat(), d.year, (d.month - 1) // 3 + 1, d.month,
            d.strftime("%B"), d.strftime("%A"), 1 if d.weekday() >= 5 else 0,
        ))
        d += timedelta(days=1)
    conn.executemany(
        "INSERT INTO dim_date VALUES (?,?,?,?,?,?,?,?)", rows
    )


def build_dim_customer_scd2(conn, customers, region_changes):
    """
    SCD Type 2 logic:
    - Start each customer with ONE row: valid_from = signup_date, valid_to = NULL, is_current = 1
    - For each region change (sorted by date), CLOSE the current row
      (set valid_to = change_date - 1 day, is_current = 0) and INSERT a new
      current row starting at change_date with the new region.
    """
    changes_by_customer = {}
    for chg in region_changes:
        changes_by_customer.setdefault(chg["customer_id"], []).append(chg)

    cur = conn.cursor()
    for cust in customers:
        cid = cust["customer_id"]
        # current "live" state in the source system already reflects the
        # LATEST region -- so we reconstruct history backwards from it.
        cust_changes = sorted(
            changes_by_customer.get(cid, []), key=lambda c: c["change_date"]
        )

        if not cust_changes:
            # never moved: single version, current
            cur.execute(
                "INSERT INTO dim_customer (customer_id, customer_name, email, region, "
                "valid_from, valid_to, is_current) VALUES (?,?,?,?,?,?,1)",
                (cid, cust["customer_name"], cust["email"], cust["region"], cust["signup_date"], None),
            )
            continue

        # customer moved at least once: reconstruct versions in order
        valid_from = cust["signup_date"]
        # the ORIGINAL region (before any change) -- source data only gives us
        # the CURRENT region, so we infer prior region as "unknown-original"
        # unless it's the first change's implied prior state. For this
        # synthetic dataset we treat the customer's listed region as the
        # region BEFORE the first recorded change.
        current_region = cust["region"]

        for i, chg in enumerate(cust_changes):
            valid_to = (date.fromisoformat(chg["change_date"]) - timedelta(days=1)).isoformat()
            cur.execute(
                "INSERT INTO dim_customer (customer_id, customer_name, email, region, "
                "valid_from, valid_to, is_current) VALUES (?,?,?,?,?,?,0)",
                (cid, cust["customer_name"], cust["email"], current_region, valid_from, valid_to),
            )
            valid_from = chg["change_date"]
            current_region = chg["new_region"]

        # final, still-current version
        cur.execute(
            "INSERT INTO dim_customer (customer_id, customer_name, email, region, "
            "valid_from, valid_to, is_current) VALUES (?,?,?,?,?,?,1)",
            (cid, cust["customer_name"], cust["email"], current_region, valid_from, None),
        )


def build_dim_product(conn, products):
    conn.executemany(
        "INSERT INTO dim_product (product_id, product_name, category, unit_price) VALUES (?,?,?,?)",
        [(p["product_id"], p["product_name"], p["category"], float(p["unit_price"])) for p in products],
    )


def get_customer_sk_asof(conn, customer_id, order_date):
    """SCD2 point-in-time lookup: find the dim_customer row that was
    valid on the given order_date. This is the key SCD2 join pattern."""
    row = conn.execute(
        "SELECT customer_sk FROM dim_customer "
        "WHERE customer_id = ? AND valid_from <= ? AND (valid_to IS NULL OR valid_to >= ?)",
        (customer_id, order_date, order_date),
    ).fetchone()
    return row[0] if row else None


def build_fact_sales(conn, orders):
    # --- Data quality step: drop exact duplicate order line items ---
    seen = set()
    deduped = []
    dup_count = 0
    for o in orders:
        key = (o["order_id"], o["customer_id"], o["product_id"], o["quantity"], o["unit_price"])
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        deduped.append(o)
    print(f"Data quality: removed {dup_count} duplicate order line items "
          f"({len(orders)} -> {len(deduped)} rows).")

    product_sk_map = {
        row[0]: row[1] for row in conn.execute("SELECT product_id, product_sk FROM dim_product")
    }

    cur = conn.cursor()
    skipped = 0
    for o in deduped:
        date_sk = int(o["order_date"].replace("-", ""))
        customer_sk = get_customer_sk_asof(conn, int(o["customer_id"]), o["order_date"])
        product_sk = product_sk_map.get(int(o["product_id"]))
        if customer_sk is None or product_sk is None:
            skipped += 1
            continue
        qty = int(o["quantity"])
        price = float(o["unit_price"])
        disc = float(o["discount_pct"])
        net_revenue = round(qty * price * (1 - disc / 100), 2)
        cur.execute(
            "INSERT INTO fact_sales (order_id, date_sk, customer_sk, product_sk, "
            "quantity, unit_price, discount_pct, net_revenue) VALUES (?,?,?,?,?,?,?,?)",
            (o["order_id"], date_sk, customer_sk, product_sk, qty, price, disc, net_revenue),
        )
    if skipped:
        print(f"Warning: skipped {skipped} rows with no matching dimension key.")


def main():
    conn = sqlite3.connect(DB_PATH)
    with open("schema.sql") as f:
        conn.executescript(f.read())

    customers = load_csv("data/raw/customers.csv")
    region_changes = load_csv("data/raw/customer_region_changes.csv")
    products = load_csv("data/raw/products.csv")
    orders = load_csv("data/raw/order_items.csv")

    order_dates = [date.fromisoformat(o["order_date"]) for o in orders]
    build_dim_date(conn, min(order_dates), max(order_dates))

    build_dim_customer_scd2(conn, customers, region_changes)
    build_dim_product(conn, products)
    build_fact_sales(conn, orders)

    conn.commit()

    # quick sanity summary
    n_fact = conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
    n_cust_versions = conn.execute("SELECT COUNT(*) FROM dim_customer").fetchone()[0]
    n_cust_with_history = conn.execute(
        "SELECT COUNT(DISTINCT customer_id) FROM dim_customer WHERE is_current = 0"
    ).fetchone()[0]
    print(f"\nLoaded: {n_fact} fact_sales rows, {n_cust_versions} dim_customer rows "
          f"({n_cust_with_history} customers have >1 SCD2 version).")
    conn.close()


if __name__ == "__main__":
    main()
