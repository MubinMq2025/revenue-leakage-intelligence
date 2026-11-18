-- recon_order_items: what each order SHOULD have cost (one row per order that has items)
CREATE OR REPLACE VIEW rli_dev_olist.recon_order_items AS
SELECT
    order_id,
    COUNT(*)                   AS item_count,
    COUNT(DISTINCT seller_id)  AS seller_count,
    SUM(price)                 AS items_price,
    SUM(freight_value)         AS items_freight,
    SUM(item_total)            AS expected_amount
FROM rli_dev_olist.fact_order_items
GROUP BY order_id;