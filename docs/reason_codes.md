\# Reconciliation reason codes



Every order is compared: \*\*paid\*\* (sum of payments) vs \*\*expected\*\* (sum of item price + freight).

Gap = paid - expected. Gaps within R$0.01 count as matched (rounding).

Rules are checked in this order; the first one that matches wins.



| # | Code | Rule | Impact | Amount at risk |

|---|------|------|--------|----------------|

| 1 | NOT\_APPROVED | Payment recorded but order never approved, and the order has no items or is canceled/unavailable | Unconfirmed | 0 (shown separately) |

| 2 | PAID\_NO\_ITEMS | Order has no items but was paid | Refund exposure | Full payment |

| 3 | NO\_PAYMENT | Order has items but no payment record | Revenue leakage | Expected amount |

| 4 | CANCELED\_BUT\_PAID | Status canceled or unavailable, has items, was paid | Refund exposure | Full payment |

| 5 | MATCHED | Has items, gap within R$0.01 | OK | 0 |

| 6 | OVERPAID\_INSTALMENT\_FEE | Paid more, more than 1 instalment, extra is at most 20% of the order | Explained | 0 |

| 7 | OVERPAID\_OTHER | Paid more, and not explained by rule 6 | Customer overcharged | Gap |

| 8 | UNDERPAID | Paid less than expected | Revenue leakage | Shortfall |

| 9 | EMPTY\_ORDER | No items and nothing paid | OK | 0 |



\*\*Impact meanings\*\*

\- \*\*Refund exposure:\*\* money held for goods not delivered. Not lost revenue, but a liability: if refunds were not processed, customers lose money and trust.

\- \*\*Revenue leakage:\*\* money that should have been collected and was not.

\- \*\*Customer overcharged:\*\* the customer paid more than the order was worth with no known reason.

\- \*\*Explained:\*\* a legitimate difference, such as card instalment interest.

\- \*\*Unconfirmed:\*\* a payment record exists but the order was never approved, so the money was probably never taken. Counted, but not added to amount at risk.



\*\*How the thresholds were chosen (from the data, 2026-11-18)\*\*

\- Instalment overpayments: median 10.1%, 90th and 95th percentile 15.5%, 99th 28.9%, max 41.3% of the order. The cap of 20% keeps the normal pattern and flags the outliers.

\- Hand check of the 20 largest at-risk orders found voucher orders that were never approved; 143 such orders (R$35,175.17) are now NOT\_APPROVED instead of refund exposure.



\*\*Limitation:\*\* Olist provides no refunds table, so exposure is sized, not confirmed as unrefunded.

