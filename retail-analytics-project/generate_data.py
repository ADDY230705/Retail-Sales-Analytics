"""
generate_data.py
-----------------
Simulates the RAW data a data engineer would receive from an upstream
transactional (OLTP) system: customers, products, and orders.

Why we do this:
- Real source systems are messy: customers change addresses/regions,
  orders arrive as flat line-item records, prices/discounts vary.
- We deliberately build in a few realistic quirks:
    1. Some customers have a region CHANGE partway through the dataset
       -> this is what makes SCD Type 2 in our ETL meaningful later.
    2. Sales have seasonal spikes (e.g. Nov/Dec) -> makes month-over-month
       and trend queries actually interesting.
    3. A few duplicate/late order rows -> gives us something to talk about
       for "data quality checks" in an interview.

Output: three raw CSVs in data/raw/, exactly as a source system would hand off.
"""

import csv
import random
from datetime import date, timedelta
from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

REGIONS = ["North", "South", "East", "West"]
CATEGORIES = {
    "Electronics": ["Wireless Mouse", "Bluetooth Speaker", "USB-C Hub", "Laptop Stand", "Webcam"],
    "Home": ["Desk Lamp", "Throw Pillow", "Ceramic Mug", "Wall Clock", "Storage Bin"],
    "Apparel": ["Cotton T-Shirt", "Running Shoes", "Denim Jacket", "Wool Scarf", "Baseball Cap"],
    "Stationery": ["Notebook Set", "Fountain Pen", "Sticky Notes", "Desk Organizer", "Whiteboard"],
}

N_CUSTOMERS = 300
N_PRODUCTS = 40
N_ORDERS = 4000
START_DATE = date(2024, 4, 1)
END_DATE = date(2025, 9, 30)  # ~18 months of history


def daterange_days():
    return (END_DATE - START_DATE).days


# ---------- 1. CUSTOMERS ----------
# Each customer has a signup region. ~15% of customers RELOCATE region
# at some point -- this is the raw signal our ETL will later turn into
# a proper SCD Type 2 dimension.
customers = []
customer_region_changes = []  # (customer_id, new_region, change_date)

for cust_id in range(1, N_CUSTOMERS + 1):
    signup_days_offset = random.randint(0, daterange_days() // 2)
    signup_date = START_DATE + timedelta(days=signup_days_offset)
    region = random.choice(REGIONS)
    customers.append({
        "customer_id": cust_id,
        "customer_name": fake.name(),
        "email": fake.unique.email(),
        "region": region,          # current region as of "today" in the source system
        "signup_date": signup_date.isoformat(),
    })
    if random.random() < 0.15:
        new_region = random.choice([r for r in REGIONS if r != region])
        change_date = signup_date + timedelta(days=random.randint(60, 300))
        if change_date <= END_DATE:
            customer_region_changes.append({
                "customer_id": cust_id,
                "new_region": new_region,
                "change_date": change_date.isoformat(),
            })

# ---------- 2. PRODUCTS ----------
products = []
prod_id = 1
for category, names in CATEGORIES.items():
    for name in names:
        for variant in range(1, 3):  # 2 price variants per product name
            products.append({
                "product_id": prod_id,
                "product_name": f"{name} v{variant}",
                "category": category,
                "unit_price": round(random.uniform(5, 150), 2),
            })
            prod_id += 1

# ---------- 3. ORDERS (fact-level source data) ----------
# One row per order LINE ITEM, the way most source systems export it.
orders = []
order_id = 1
for _ in range(N_ORDERS):
    days_offset = random.randint(0, daterange_days())
    order_date = START_DATE + timedelta(days=days_offset)

    # seasonal boost: Nov/Dec get ~2x order volume by duplicating some orders
    seasonal_multiplier = 2 if order_date.month in (11, 12) else 1

    for _ in range(seasonal_multiplier):
        # An order can only happen AFTER the customer signed up --
        # filter eligible customers by signup_date <= order_date.
        eligible = [c for c in customers if c["signup_date"] <= order_date.isoformat()]
        if not eligible:
            continue
        cust = random.choice(eligible)
        n_items = random.randint(1, 4)
        chosen_products = random.sample(products, n_items)
        for prod in chosen_products:
            qty = random.randint(1, 5)
            discount_pct = random.choice([0, 0, 0, 5, 10, 15])
            orders.append({
                "order_id": order_id,
                "order_date": order_date.isoformat(),
                "customer_id": cust["customer_id"],
                "product_id": prod["product_id"],
                "quantity": qty,
                "unit_price": prod["unit_price"],
                "discount_pct": discount_pct,
            })
        order_id += 1

# inject a few duplicate rows on purpose (data quality talking point)
for _ in range(15):
    dup = random.choice(orders).copy()
    orders.append(dup)

random.shuffle(orders)

# ---------- WRITE CSVs ----------
with open("data/raw/customers.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=customers[0].keys())
    w.writeheader()
    w.writerows(customers)

with open("data/raw/customer_region_changes.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["customer_id", "new_region", "change_date"])
    w.writeheader()
    w.writerows(customer_region_changes)

with open("data/raw/products.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=products[0].keys())
    w.writeheader()
    w.writerows(products)

with open("data/raw/order_items.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=orders[0].keys())
    w.writeheader()
    w.writerows(orders)

print(f"Generated: {len(customers)} customers, {len(customer_region_changes)} region changes, "
      f"{len(products)} products, {len(orders)} order line items.")
