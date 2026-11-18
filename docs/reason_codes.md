\# Reconciliation reason codes



Every order is compared: \*\*paid\*\* (sum of payments) vs \*\*expected\*\* (sum of item price + freight).

Gap = paid - expected. Gaps within R$0.01 count as matched (rounding).

Rules are checked in this order; the first one that matches wins.



| # | Code | Rule | Impact | Amount at risk |

|---|------|------|--------|----------------|

| 1 | PAID\_NO\_ITEMS | Order has no items but was paid | Refund exposure | Full payment |

| 2 | NO\_PAYMENT | Order has items but no payment record | Revenue leakage | Expected amount |

| 3 | CANCELED\_BUT\_PAID | Status canceled or unavailable, has items, was paid | Refund exposure | Full payment |

| 4 | MATCHED | Has items, gap within R$0.01 | OK | 0 |

| 5 | OVERPAID\_INSTALMENT\_FEE | Paid more, more than 1 instalment (card interest) | Explained | 0 |

| 6 | OVERPAID\_OTHER | Paid more, single payment | Customer overcharged | Gap |

| 7 | UNDERPAID | Paid less than expected | Revenue leakage | Shortfall |

| 8 | EMPTY\_ORDER | No items and nothing paid | OK | 0 |



\*\*Impact meanings\*\*

\- \*\*Refund exposure:\*\* money held for goods not delivered. Not lost revenue, but a liability: if refunds were not processed, customers lose money and trust.

\- \*\*Revenue leakage:\*\* money that should have been collected and was not.

\- \*\*Customer overcharged:\*\* the customer paid more than the order was worth with no known reason.

\- \*\*Explained:\*\* a legitimate difference, such as card instalment interest.



\*\*Limitation:\*\* Olist provides no refunds table, so exposure is sized, not confirmed as unrefunded.

