-- dim_customer: one row per REAL customer (customer_unique_id).
-- customer_id changes with every order, so location comes from the customer's latest order.
CREATE OR REPLACE VIEW rli_dev_olist.dim_customer AS
WITH ranked AS (
    SELECT
        c.customer_unique_id,
        c.customer_zip_code_prefix,
        c.customer_city,
        c.customer_state,
        o.order_purchase_timestamp,
        ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id
                           ORDER BY o.order_purchase_timestamp DESC, c.customer_id) AS rn,
        COUNT(*)  OVER (PARTITION BY c.customer_unique_id)                          AS order_count,
        MIN(o.order_purchase_timestamp) OVER (PARTITION BY c.customer_unique_id)    AS first_order_at
    FROM rli_dev_olist.customers c
    LEFT JOIN rli_dev_olist.orders o ON o.customer_id = c.customer_id
)
SELECT
    customer_unique_id         AS customer_key,
    customer_zip_code_prefix   AS zip_code_prefix,
    customer_city              AS city,
    customer_state             AS state,
    order_count,
    first_order_at,
    order_purchase_timestamp   AS last_order_at
FROM ranked
WHERE rn = 1;