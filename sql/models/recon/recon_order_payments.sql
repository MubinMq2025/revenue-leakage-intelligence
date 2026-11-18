-- recon_order_payments: what each order WAS paid (one row per order that has payments)
CREATE OR REPLACE VIEW rli_dev_olist.recon_order_payments AS
SELECT
    order_id,
    COUNT(*)                                                               AS payment_count,
    SUM(payment_value)                                                     AS paid_amount,
    SUM(CASE WHEN payment_type = 'voucher' THEN payment_value ELSE 0 END)  AS voucher_amount,
    MAX(payment_installments)                                              AS max_installments,
    array_join(array_sort(array_distinct(array_agg(payment_type))), '+')   AS payment_types
FROM rli_dev_olist.fact_payments
GROUP BY order_id;