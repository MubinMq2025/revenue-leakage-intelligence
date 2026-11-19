-- mart_checkout_orders: one row per paid order with items (grain: order_id).
-- Base table for the Phase 4.8 checkout risk model: what was known when the customer paid,
-- plus how the order turned out. Only the "known at checkout" columns may be used as model inputs;
-- order_status, reason_code, canceled_after_payment and at_risk_rs are outcomes, known only later.
-- Orders whose payment was never approved (NOT_APPROVED) are left out: no money was taken.
-- Materialized as a Parquet table by scripts/create_models.py, after mart_order_reconciliation.
WITH main_item AS (
    -- the most expensive item decides the order's main seller and category
    SELECT
        i.order_id,
        i.seller_id,
        p.category,
        ROW_NUMBER() OVER (PARTITION BY i.order_id ORDER BY i.price DESC, i.order_item_id) AS rn
    FROM rli_dev_olist.fact_order_items i
    LEFT JOIN rli_dev_olist.dim_product p ON p.product_id = i.product_id
)
SELECT
    r.order_id,
    o.order_purchase_timestamp                                                      AS purchased_at,
    r.purchase_date_key                                                             AS purchase_date,
    CAST(date_trunc('month', r.purchase_date_key) AS date)                          AS purchase_month,
    -- known at checkout
    CAST(r.items_price AS double)                                                   AS order_value_rs,
    CAST(r.items_freight AS double)                                                 AS freight_rs,
    CAST(r.items_freight AS double) / CAST(r.items_price AS double)                 AS freight_ratio,
    r.item_count,
    r.seller_count,
    COALESCE(r.payment_types, 'none')                                               AS payment_types,
    r.max_installments,
    IF(r.voucher_amount > 0, 1, 0)                                                  AS uses_voucher,
    date_diff('day', o.order_purchase_timestamp, o.order_estimated_delivery_date)   AS promised_days,
    hour(o.order_purchase_timestamp)                                                AS purchase_hour,
    day_of_week(o.order_purchase_timestamp)                                         AS purchase_weekday,
    c.customer_state,
    s.seller_state,
    IF(c.customer_state = s.seller_state, 1, 0)                                     AS same_state,
    m.seller_id                                                                     AS main_seller_id,
    m.category                                                                      AS main_category,
    -- outcome (the label), known only after checkout
    r.order_status,
    r.reason_code,
    IF(r.reason_code = 'CANCELED_BUT_PAID', 1, 0)                                   AS canceled_after_payment,
    CAST(r.amount_at_risk AS double)                                                AS at_risk_rs,
    CAST(r.paid_amount AS double)                                                   AS paid_rs
FROM rli_dev_olist.mart_order_reconciliation r
JOIN rli_dev_olist.orders o       ON o.order_id = r.order_id
JOIN rli_dev_olist.customers c    ON c.customer_id = o.customer_id
JOIN main_item m                  ON m.order_id = r.order_id AND m.rn = 1
LEFT JOIN rli_dev_olist.sellers s ON s.seller_id = m.seller_id
WHERE r.item_count > 0
  AND r.paid_amount > 0.01
  AND r.reason_code <> 'NOT_APPROVED'