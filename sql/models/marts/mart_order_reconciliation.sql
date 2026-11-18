-- mart_order_reconciliation: one row per order with its gap, reason code, impact and amount at risk.
-- Rules are checked IN ORDER; the first match wins. Tolerance: gaps within R$0.01 count as matched.
-- Full definitions: docs/reason_codes.md
CREATE OR REPLACE VIEW rli_dev_olist.mart_order_reconciliation AS
WITH coded AS (
    SELECT
        t.*,
        CASE
            WHEN t.item_count = 0 AND t.paid_amount > 0.01                         THEN 'PAID_NO_ITEMS'
            WHEN t.item_count > 0 AND t.payment_count = 0                          THEN 'NO_PAYMENT'
            WHEN t.order_status IN ('canceled', 'unavailable')
                 AND t.item_count > 0 AND t.paid_amount > 0.01                     THEN 'CANCELED_BUT_PAID'
            WHEN t.item_count > 0 AND abs(t.gap_amount) <= 0.01                    THEN 'MATCHED'
            WHEN t.gap_amount > 0.01 AND t.max_installments > 1                    THEN 'OVERPAID_INSTALMENT_FEE'
            WHEN t.gap_amount > 0.01                                               THEN 'OVERPAID_OTHER'
            WHEN t.gap_amount < -0.01                                              THEN 'UNDERPAID'
            ELSE 'EMPTY_ORDER'
        END AS reason_code
    FROM rli_dev_olist.recon_order_totals t
)
SELECT
    c.*,
    CASE c.reason_code
        WHEN 'PAID_NO_ITEMS'           THEN 'refund_exposure'
        WHEN 'CANCELED_BUT_PAID'       THEN 'refund_exposure'
        WHEN 'NO_PAYMENT'              THEN 'revenue_leakage'
        WHEN 'UNDERPAID'               THEN 'revenue_leakage'
        WHEN 'OVERPAID_OTHER'          THEN 'customer_overcharged'
        WHEN 'OVERPAID_INSTALMENT_FEE' THEN 'explained'
        ELSE 'ok'
    END AS impact,
    -- Money at risk for this order (not always the gap: a cancelled order can match to the cent
    -- and still have its full payment at risk)
    CASE c.reason_code
        WHEN 'PAID_NO_ITEMS'     THEN c.paid_amount
        WHEN 'CANCELED_BUT_PAID' THEN c.paid_amount
        WHEN 'NO_PAYMENT'        THEN c.expected_amount
        WHEN 'UNDERPAID'         THEN -c.gap_amount
        WHEN 'OVERPAID_OTHER'    THEN c.gap_amount
        ELSE 0
    END AS amount_at_risk
FROM coded c;