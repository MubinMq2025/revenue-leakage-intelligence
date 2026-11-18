-- fact_payments: one row per payment on an order (grain: order_id + payment_sequential)
CREATE OR REPLACE VIEW rli_dev_olist.fact_payments AS
SELECT
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value,
    c.customer_unique_id                         AS customer_key,
    CAST(o.order_purchase_timestamp AS date)     AS purchase_date_key,
    p.dq_flags
FROM rli_dev_olist.payments p
LEFT JOIN rli_dev_olist.orders o    ON o.order_id = p.order_id
LEFT JOIN rli_dev_olist.customers c ON c.customer_id = o.customer_id;