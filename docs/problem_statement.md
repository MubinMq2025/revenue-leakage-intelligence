\# Problem Statement



\## Problem

Olist is a marketplace that sells products from thousands of small sellers through Brazil's largest online stores. Every order passes through several records: the order, its items, its payments and its delivery. When these records do not agree, money is lost or left unexplained. Customers can pay for orders that have no items, orders can be delivered without a matching payment, and late deliveries lead to poor reviews and lost repeat customers. These gaps are usually found weeks later through manual reconciliation in spreadsheets, if they are found at all.



Initial profiling of 99,441 orders (2016 to 2018) already shows the pattern:

\- 775 orders have no items, so their value cannot be verified

\- 1 order has no payment record

\- 8 orders are marked delivered but have no delivery date

\- Shipping deadlines are recorded up to 2020, two years after the data ends



\## Who uses this

\- \*\*Finance:\*\* size and track revenue at risk, and replace manual reconciliation

\- \*\*Operations:\*\* find late delivery and fulfilment problems

\- \*\*Seller management:\*\* identify sellers with unusual payment, freight or cancellation patterns



\## Business questions

1\. How much revenue is at risk from mismatches between orders, items and payments?

2\. What causes it, and which sellers, categories and payment types drive it?

3\. Which sellers behave abnormally compared with their peers?

4\. What revenue should we expect over the next 90 days, and is actual revenue on track?



\## Success metrics

\- Total revenue at risk (R$) and leakage rate (% of order value)

\- % of orders with a reconciliation gap, broken down by reason code

\- Number of anomalous sellers flagged, and the share confirmed by reconciliation gaps or poor reviews

\- Forecast error (WAPE) lower than a simple baseline

\- The pipeline runs daily from start to end with no manual steps (Power BI refresh aside)



\## Scope

\*\*In scope\*\*

\- All 9 Olist tables, for orders from September 2016 to October 2018

\- Automated ingestion, validation, reconciliation, anomaly detection, forecasting and alerting on AWS

\- A Power BI dashboard and a one-page executive memo



\*\*Out of scope\*\*

\- Real-time streaming (a daily batch is enough for finance reconciliation)

\- Fraud investigation of individual customers

\- Currency conversion (all values stay in Brazilian reais, R$)

\- Geolocation analysis below state level



\## Assumptions

\- Olist is a public, anonymised dataset and is treated as one company's data.

\- Order item value = price + freight\_value.

\- Small differences between the amount paid and the item value can have legitimate causes, such as instalment fees or vouchers. These are allowed within a tolerance and classed separately from true leakage.

