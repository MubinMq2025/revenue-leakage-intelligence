-- recon_order_totals: one row per order, expected vs paid, side by side.
-- Starts from fact_orders so orders with no items or no payments are kept (as 0), not lost.
CREATE OR REPLACE VIEW rli_dev_olist.recon_order_totals AS
SELECT
    o.order_id,
    o.customer_key,
    o.purchase_date_key,
    o.order_status,
    o.approved_at,
    COALESCE(i.item_count, 0)         AS item_count,
    i.seller_count,
    COALESCE(i.items_price, 0)        AS items_price,
    COALESCE(i.items_freight, 0)      AS items_freight,
    COALESCE(i.expected_amount, 0)    AS expected_amount,
    COALESCE(p.payment_count, 0)      AS payment_count,
    COALESCE(p.paid_amount, 0)        AS paid_amount,
    COALESCE(p.voucher_amount, 0)     AS voucher_amount,
    p.max_installments,
    p.payment_types,
    COALESCE(p.paid_amount, 0) - COALESCE(i.expected_amount, 0)   AS gap_amount,   -- positive = paid more than expected
    o.dq_flags
FROM rli_dev_olist.fact_orders o
LEFT JOIN rli_dev_olist.recon_order_items i    ON i.order_id = o.order_id
LEFT JOIN rli_dev_olist.recon_order_payments p ON p.order_id = o.order_id;