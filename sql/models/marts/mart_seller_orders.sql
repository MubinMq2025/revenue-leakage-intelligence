-- mart_seller_orders: one row per order and seller (grain: order_id + seller_id).
-- Base table for the Phase 4 seller models: what one seller sold in one order and how it turned out.
-- Money is split by the seller's share of the order's item value (same rule as mart_leakage_summary),
-- so seller rows add up to order totals. Orders with no items have no seller, so they are left out.
-- Materialized as a Parquet table by scripts/create_models.py, after mart_order_reconciliation.
WITH seller_items AS (
    SELECT
        order_id,
        seller_id,
        COUNT(*)            AS items,
        SUM(price)          AS price_rs,
        SUM(freight_value)  AS freight_rs,
        SUM(item_total)     AS item_total_rs
    FROM rli_dev_olist.fact_order_items
    GROUP BY order_id, seller_id
),
joined AS (
    SELECT
        s.*,
        r.purchase_date_key,
        r.order_status,
        r.reason_code,
        r.impact,
        r.paid_amount,
        r.amount_at_risk,
        CAST(s.item_total_rs AS double) / CAST(r.expected_amount AS double)  AS share,
        o.delivered_at,
        o.is_late,
        o.review_score
    FROM seller_items s
    JOIN rli_dev_olist.mart_order_reconciliation r ON r.order_id = s.order_id
    JOIN rli_dev_olist.fact_orders o               ON o.order_id = s.order_id
)
SELECT
    order_id,
    seller_id,
    purchase_date_key                                         AS purchase_date,
    CAST(date_trunc('month', purchase_date_key) AS date)      AS purchase_month,
    order_status,
    reason_code,
    impact,
    items,
    CAST(price_rs AS double)                                  AS price_rs,
    CAST(freight_rs AS double)                                AS freight_rs,
    share,
    share * CAST(paid_amount AS double)                       AS paid_rs,
    share * CAST(amount_at_risk AS double)                    AS at_risk_rs,
    IF(order_status IN ('canceled', 'unavailable'), 1, 0)     AS is_canceled,
    IF(delivered_at IS NOT NULL, 1, 0)                        AS is_delivered,
    IF(COALESCE(is_late, false), 1, 0)                        AS is_late,
    review_score,
    CAST(delivered_at AS date)                                AS delivered_date
FROM joined