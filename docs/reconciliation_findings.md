\# Reconciliation Findings: Olist Orders (Sep 2016 to Oct 2018)



\## Headline

R$236,265.58 is at risk across 1,159 orders, which is 1.48% of R$16,008,872.12 in payments.

Almost all of it (R$235,475.00, 1,096 orders) is refund exposure: customers paid for orders that were never fulfilled.

True revenue leakage (we were paid less than the items were worth) is small: R$342.54 across 40 orders.



The reconciliation ties out to the source data exactly. Order-level gaps add up to R$165,318.88, and every one of the 99,441 orders gets exactly one reason code. 98,365 orders (98.9%) have payments equal to item value within 1 cent.



\## By impact

| Impact | Orders | Amount at risk (R$) | Meaning |

|---|---|---|---|

| refund\_exposure | 1,096 | 235,475.00 | Paid, but goods not delivered. Money is owed back unless already refunded |

| customer\_overcharged | 23 | 448.04 | Paid more than item value, with no instalment explanation |

| revenue\_leakage | 40 | 342.54 | Paid less than item value, or not paid at all |

| explained | 239 | 0.00 | Overpayment explained by instalment interest (20% cap or less) |

| unconfirmed | 143 | 0.00 | Payment never approved, so no money was confirmed (R$35,175.17 recorded) |

| \*\*Total at risk\*\* | \*\*1,159\*\* | \*\*236,265.58\*\* | |



\## By reason code

| Reason code | Orders | Amount at risk (R$) |

|---|---|---|

| PAID\_NO\_ITEMS | 629 | 127,416.78 |

| CANCELED\_BUT\_PAID | 467 | 108,058.22 |

| OVERPAID\_OTHER | 23 | 448.04 |

| UNDERPAID | 39 | 199.08 |

| NO\_PAYMENT | 1 | 143.46 |

| OVERPAID\_INSTALMENT\_FEE | 239 | 0.00 |

| NOT\_APPROVED | 143 | 0.00 |

| EMPTY\_ORDER | 3 | 0.00 |

| MATCHED | 97,897 | 0.00 |



Key insight: the 467 CANCELED\_BUT\_PAID orders have a combined payment gap of only R$32.01. Their payments match item value almost to the cent, so amount-only matching would mark them as fine. They are only caught because order status is checked before amounts. In a hand audit, these orders were approved and never shipped, and most had 1-star reviews.



\## Where the risk sits

\*\*53.9% of the money at risk has no items\*\* (PAID\_NO\_ITEMS), so it cannot be traced to a product or seller. Fixing this needs the order process itself, not a seller review.



Top categories by amount at risk:

| Category | At risk (R$) | Rate |

|---|---|---|

| cool\_stuff | 15,266.50 | 2.12% |

| sports\_leisure | 9,411.89 | 0.81% |

| computers\_accessories | 8,330.85 | 0.79% |

| watches\_gifts | 7,310.15 | 0.56% |

| auto | 6,778.68 | 0.99% |



\- cool\_stuff is highest in both money and rate (about 2.5 times the typical 0.8%).

\- musical\_instruments also has a high rate (1.96%).

\- health\_beauty has the largest revenue (R$1,441,197.90) but one of the lowest rates (0.26%).



Top sellers by amount at risk:

| Seller (id prefix) | At risk (R$) | Rate |

|---|---|---|

| c4f7fee5 | 9,618.88 | 76.74% |

| 7e93a43e | 3,915.63 | 2.14% |

| 961dff0a | 2,692.82 | 26.71% |

| c004e5ea | 2,419.20 | 49.63% |

| ea6b12bf | 1,629.13 | 57.54% |



Seller c4f7fee5 had R$9,618.88 at risk out of R$12,533.60 paid. Several other sellers sit between 26% and 58%. A typical seller is close to 1%.



\## Trend

| Period | Paid (R$) | At risk (R$) | Rate |

|---|---|---|---|

| 2017 | 7,249,746.74 | 147,476.22 | 2.03% |

| Jan to Aug 2018 | 8,694,733.86 | 81,530.10 | 0.94% |



\- The rate roughly halved while payment volume grew.

\- Mar to Jun 2018 was the cleanest period (about 0.5%).

\- July 2018 spiked to 2.48% (R$26,487.10) and needs investigating.

\- 2016 and Sep/Oct 2018 are excluded because they have too few orders to be reliable.



\## Audit adjustments

The first version reported R$271K across 1,294 orders. A hand audit of the 20 largest at-risk orders and the top 3 of each smaller code found two problems:

1\. 143 orders whose payment was never approved (R$35,175.17, mostly vouchers) were counted as refund exposure. A NOT\_APPROVED rule now classes them as unconfirmed.

2\. Some "instalment fees" were as high as 41% of the order. The cap was set at 20% using the data (median 10.1%, p95 15.5%, p99 28.9%), so larger overpayments are now flagged.



Final figure after the audit: R$236,265.58 across 1,159 orders.



\## Recommendations

1\. \*\*Confirm refunds for the 1,096 refund exposure orders\*\* (R$235K). Match them against payment provider refund records. Any order with no refund is money owed to customers.

2\. \*\*Find out why paid orders become unavailable or canceled.\*\* These are the 629 PAID\_NO\_ITEMS orders and the 467 CANCELED\_BUT\_PAID orders. Check stock sync and seller cancellation rules at checkout.

3\. \*\*Review the high-rate sellers\*\*, starting with c4f7fee5 (76.7%). Phase 4 anomaly detection will test whether they stand out on other measures too.

4\. \*\*Investigate July 2018.\*\* Check what changed that month (sellers, categories, promotions).

5\. \*\*Review the 23 overcharged orders\*\* (R$448.04) and refund the customers if the charges are confirmed.



\## Limitations

\- Olist has no refunds table, so exposure is sized, not confirmed as unrefunded.

\- Instalment interest is inferred from overpayment (20% cap), not read from fee records.

\- Multi-seller orders are split by each item's share of order value, which is an allocation, not a recorded split.

\- The 2016 and Sep/Oct 2018 months are too thin to analyse.



\## Method

\- Each order's expected amount (item price plus freight) is compared with its paid amount, aggregating per order before joining so nothing is double counted.

\- 9 reason codes are applied in order (first match wins, R$0.01 tolerance). Definitions are in docs/reason\_codes.md.

\- 32 automated checks, including a cent-level tie-out to the curated source tables, run with scripts/check\_models.py.

