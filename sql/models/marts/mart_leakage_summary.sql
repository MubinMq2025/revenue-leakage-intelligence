-- mart_leakage_summary: reconciliation totals by month, seller, category, payment type and reason.
-- Materialized as a Parquet table by scripts/create_models.py, after mart_order_reconciliation.
-- Orders with several sellers/categories are split by each item's share of the order's item value,
-- so no order is counted twice. Orders with no items get seller 'NO_ITEMS' / category 'no_items'.
-- Note: "orders" counts an order in every row it is split into; use mart_order_reconciliation
-- for exact order counts.
WITH allocated AS (
    -- Orders with items: one row per item, carrying the item's share of the order
    SELECT
        r.order_id, r.purchase_date_key, r.order_status, r.reason_code, r.impact,
        COALESCE(r.payment_types, 'none')                                   AS payment_types,
        i.seller_id,
        p.category,
        CAST(i.item_total AS double) / CAST(r.expected_amount AS double)    AS share,
        r.paid_amount, r.expected_amount, r.gap_amount, r.amount_at_risk
    FROM rli_dev_olist.mart_order_reconciliation r
    JOIN rli_dev_olist.fact_order_items i ON i.order_id = r.order_id
    LEFT JOIN rli_dev_olist.dim_product p ON p.product_id = i.product_id

    UNION ALL

    -- Orders with no items: nothing to split, so the whole order goes to one bucket
    SELECT
        r.order_id, r.purchase_date_key, r.order_status, r.reason_code, r.impact,
        COALESCE(r.payment_types, 'none'),
        'NO_ITEMS',
        'no_items',
        CAST(1 AS double),
        r.paid_amount, r.expected_amount, r.gap_amount, r.amount_at_risk
    FROM rli_dev_olist.mart_order_reconciliation r
    WHERE r.item_count = 0
)
SELECT
    date_trunc('month', purchase_date_key)                         AS month,
    seller_id,
    category,
    payment_types,
    order_status,
    reason_code,
    impact,
    COUNT(DISTINCT order_id)                                       AS orders,
    ROUND(SUM(share * CAST(paid_amount AS double)), 2)             AS paid_rs,
    ROUND(SUM(share * CAST(expected_amount AS double)), 2)         AS expected_rs,
    ROUND(SUM(share * CAST(gap_amount AS double)), 2)              AS gap_rs,
    ROUND(SUM(share * CAST(amount_at_risk AS double)), 2)          AS at_risk_rs
FROM allocated
GROUP BY 1, 2, 3, 4, 5, 6, 7