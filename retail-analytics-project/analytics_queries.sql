-- analytics_queries.sql
-- ---------------------------------------------------------------
-- Business-question SQL against the star schema.
-- Each query below is something you should be able to explain
-- line-by-line in an interview: what it answers, and how the
-- window function / CTE works.
-- ---------------------------------------------------------------

-- ============================================================
-- Q1. Month-over-month revenue growth
-- Uses: window function LAG() to compare each month to the previous one.
-- ============================================================
WITH monthly_revenue AS (
    SELECT
        d.year,
        d.month,
        d.month_name,
        SUM(f.net_revenue) AS revenue
    FROM fact_sales f
    JOIN dim_date d ON f.date_sk = d.date_sk
    GROUP BY d.year, d.month
)
SELECT
    year,
    month_name,
    ROUND(revenue, 2) AS revenue,
    ROUND(revenue - LAG(revenue) OVER (ORDER BY year, month), 2) AS revenue_change,
    ROUND(
        100.0 * (revenue - LAG(revenue) OVER (ORDER BY year, month))
        / LAG(revenue) OVER (ORDER BY year, month), 1
    ) AS pct_change
FROM monthly_revenue
ORDER BY year, month;


-- ============================================================
-- Q2. Top 3 products per category by total revenue
-- Uses: window function RANK() PARTITION BY category.
-- This is one of the most commonly asked window function patterns
-- in interviews ("top N per group").
-- ============================================================
WITH product_revenue AS (
    SELECT
        p.category,
        p.product_name,
        SUM(f.net_revenue) AS revenue
    FROM fact_sales f
    JOIN dim_product p ON f.product_sk = p.product_sk
    GROUP BY p.category, p.product_name
),
ranked AS (
    SELECT
        category,
        product_name,
        ROUND(revenue, 2) AS revenue,
        RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rnk
    FROM product_revenue
)
SELECT category, product_name, revenue, rnk
FROM ranked
WHERE rnk <= 3
ORDER BY category, rnk;


-- ============================================================
-- Q3. Customer cohort retention by signup month
-- Uses: CTE to build cohorts, then a self-referencing comparison
-- to see what % of each signup cohort is still ordering N months later.
-- ============================================================
WITH first_purchase AS (
    -- first purchase month per customer = their cohort
    SELECT
        c.customer_id,
        MIN(strftime('%Y-%m', d.full_date)) AS cohort_month
    FROM fact_sales f
    JOIN dim_customer c ON f.customer_sk = c.customer_sk
    JOIN dim_date d ON f.date_sk = d.date_sk
    GROUP BY c.customer_id
),
activity AS (
    SELECT DISTINCT
        c.customer_id,
        strftime('%Y-%m', d.full_date) AS activity_month
    FROM fact_sales f
    JOIN dim_customer c ON f.customer_sk = c.customer_sk
    JOIN dim_date d ON f.date_sk = d.date_sk
),
cohort_activity AS (
    SELECT
        fp.cohort_month,
        (
            (CAST(strftime('%Y', a.activity_month || '-01') AS INT) - CAST(strftime('%Y', fp.cohort_month || '-01') AS INT)) * 12
            + (CAST(strftime('%m', a.activity_month || '-01') AS INT) - CAST(strftime('%m', fp.cohort_month || '-01') AS INT))
        ) AS months_since_signup,
        a.customer_id
    FROM first_purchase fp
    JOIN activity a ON fp.customer_id = a.customer_id
)
SELECT
    cohort_month,
    months_since_signup,
    COUNT(DISTINCT customer_id) AS active_customers
FROM cohort_activity
WHERE months_since_signup BETWEEN 0 AND 3
GROUP BY cohort_month, months_since_signup
ORDER BY cohort_month, months_since_signup;


-- ============================================================
-- Q4. Proof that SCD2 is working correctly
-- For customers who relocated, revenue should be attributed to the
-- region they were ACTUALLY in on the order date -- not their
-- current/final region. This query shows both versions side by side.
-- ============================================================
SELECT
    c.customer_id,
    c.region AS region_at_time_of_sale,
    c.valid_from,
    c.valid_to,
    c.is_current,
    COUNT(f.sales_sk) AS orders_in_this_period,
    ROUND(SUM(f.net_revenue), 2) AS revenue_in_this_period
FROM dim_customer c
JOIN fact_sales f ON f.customer_sk = c.customer_sk
WHERE c.customer_id IN (
    SELECT customer_id FROM dim_customer
    GROUP BY customer_id HAVING COUNT(*) > 1
)
GROUP BY c.customer_sk
ORDER BY c.customer_id, c.valid_from
LIMIT 20;


-- ============================================================
-- Q5. Revenue by region (CORRECT, using SCD2 point-in-time region)
-- vs what it WOULD be if we naively used current region for all history
-- (this is the exact bug SCD2 prevents -- great interview talking point).
-- ============================================================
-- Correct: revenue attributed to region at time of sale
SELECT 'SCD2-correct' AS method, c.region, ROUND(SUM(f.net_revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_customer c ON f.customer_sk = c.customer_sk
GROUP BY c.region

UNION ALL

-- Naive/incorrect: as if we only ever knew the customer's CURRENT region
SELECT 'naive-SCD1-style' AS method, cur.region, ROUND(SUM(f.net_revenue), 2) AS revenue
FROM fact_sales f
JOIN dim_customer c ON f.customer_sk = c.customer_sk
JOIN dim_customer cur ON cur.customer_id = c.customer_id AND cur.is_current = 1
GROUP BY cur.region
ORDER BY method, region;
