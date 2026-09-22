-- schema.sql
-- ---------------------------------------------------------------
-- Star schema for retail sales analytics.
-- Grain of fact_sales: ONE ROW PER ORDER LINE ITEM.
-- (Always state your grain explicitly -- interviewers love asking this.)
-- ---------------------------------------------------------------

DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_date;

-- ---------------- DIM: CUSTOMER (SCD Type 2) ----------------
-- Why SCD2: a customer's region can change over time (they relocate).
-- If we just overwrote the region (SCD Type 1), historical sales would
-- silently get reattributed to the NEW region, corrupting past reports.
-- SCD2 keeps a full history: each row is a "version" of the customer,
-- valid for a date range. Facts join to the version that was CURRENT
-- at the time of the sale.
CREATE TABLE dim_customer (
    customer_sk     INTEGER PRIMARY KEY AUTOINCREMENT,  -- surrogate key
    customer_id     INTEGER NOT NULL,                   -- natural/business key
    customer_name   TEXT NOT NULL,
    email           TEXT NOT NULL,
    region          TEXT NOT NULL,
    valid_from      DATE NOT NULL,
    valid_to        DATE,                                -- NULL = still current
    is_current      INTEGER NOT NULL                     -- 1 = current version, 0 = historical
);

-- ---------------- DIM: PRODUCT ----------------
-- Kept as SCD Type 1 (overwrite) for simplicity -- product price/category
-- changes aren't something we need history for in this scope.
CREATE TABLE dim_product (
    product_sk      INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL UNIQUE,
    product_name    TEXT NOT NULL,
    category        TEXT NOT NULL,
    unit_price      REAL NOT NULL
);

-- ---------------- DIM: DATE ----------------
-- A conformed date dimension lets us slice by year/month/quarter/weekday
-- without repeating date-math logic in every query.
CREATE TABLE dim_date (
    date_sk         INTEGER PRIMARY KEY,   -- format YYYYMMDD, sorts naturally
    full_date       DATE NOT NULL,
    year            INTEGER NOT NULL,
    quarter         INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    month_name      TEXT NOT NULL,
    day_of_week     TEXT NOT NULL,
    is_weekend      INTEGER NOT NULL
);

-- ---------------- FACT: SALES ----------------
CREATE TABLE fact_sales (
    sales_sk        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,
    date_sk         INTEGER NOT NULL REFERENCES dim_date(date_sk),
    customer_sk     INTEGER NOT NULL REFERENCES dim_customer(customer_sk),
    product_sk      INTEGER NOT NULL REFERENCES dim_product(product_sk),
    quantity        INTEGER NOT NULL,
    unit_price      REAL NOT NULL,
    discount_pct    REAL NOT NULL,
    net_revenue     REAL NOT NULL   -- quantity * unit_price * (1 - discount_pct/100)
);

CREATE INDEX idx_fact_customer ON fact_sales(customer_sk);
CREATE INDEX idx_fact_product ON fact_sales(product_sk);
CREATE INDEX idx_fact_date ON fact_sales(date_sk);
