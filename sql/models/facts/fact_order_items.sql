-- fact_order_items: one row per item in an order (grain: order_id + order_item_id)
CREATE OR REPLACE VIEW rli_dev_olist.fact_order_items AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    c.customer_unique_id                         AS customer_key,
    CAST(o.order_purchase_timestamp AS date)     AS purchase_date_key,
    i.shipping_limit_date,
    i.price,
    i.freight_value,
    i.price + i.freight_value                    AS item_total,
    i.dq_flags
FROM rli_dev_olist.order_items i
LEFT JOIN rli_dev_olist.orders o    ON o.order_id = i.order_id
LEFT JOIN rli_dev_olist.customers c ON c.customer_id = o.customer_id;