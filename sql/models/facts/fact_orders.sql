-- fact_orders: one row per order (grain: order_id), with delivery timing and the latest review.
CREATE OR REPLACE VIEW rli_dev_olist.fact_orders AS
WITH latest_review AS (
    SELECT
        order_id,
        review_score,
        ROW_NUMBER() OVER (PARTITION BY order_id
                           ORDER BY review_answer_timestamp DESC, review_creation_date DESC, review_id) AS rn
    FROM rli_dev_olist.reviews
)
SELECT
    o.order_id,
    c.customer_unique_id                                          AS customer_key,
    CAST(o.order_purchase_timestamp AS date)                      AS purchase_date_key,
    o.order_status,
    o.order_purchase_timestamp                                    AS purchased_at,
    o.order_approved_at                                           AS approved_at,
    o.order_delivered_carrier_date                                AS shipped_at,
    o.order_delivered_customer_date                               AS delivered_at,
    o.order_estimated_delivery_date                               AS estimated_delivery_at,
    date_diff('day', o.order_purchase_timestamp, o.order_delivered_customer_date)  AS delivery_days,
    -- positive = delivered after the promised date
    date_diff('day', CAST(o.order_estimated_delivery_date AS date),
                     CAST(o.order_delivered_customer_date AS date))                AS days_late,
    o.order_delivered_customer_date > o.order_estimated_delivery_date              AS is_late,
    r.review_score,
    o.dq_flags
FROM rli_dev_olist.orders o
LEFT JOIN rli_dev_olist.customers c ON c.customer_id = o.customer_id
LEFT JOIN latest_review r           ON r.order_id = o.order_id AND r.rn = 1;