\# Model Card: Seller Risk Queue and Weekly Revenue Forecast



Phase 4 of the Revenue Leakage Intelligence project. Data: Olist Brazilian e-commerce, 2017 to 2018, money in Brazilian reais (R$).

Code: `src/ml/`, settings: `config/ml.yaml`, every run tracked in MLflow (`data/mlflow/`).



\## 1. Seller risk review queue



\*\*Purpose:\*\* each month, give the finance team a list of 20 sellers to review, ordered so the list covers as much of the next 3 months' money at risk as possible.



\*\*Data:\*\* `mart\_seller\_orders` (100,010 order-seller rows, 3,095 sellers). Only seller-attributable risk is covered: R$108,848.80, which is 46% of the R$236,265.58 total. The other 54% comes from paid orders with no items and has no seller.



\*\*How it was built\*\*

\- Point-in-time seller report cards for 15 month-starts (Apr 2017 to Jun 2018). Each uses only orders from the 6 months ending 1 month before the snapshot, and hides any delivery or review that happened after the snapshot (about 0.5% of deliveries).

\- Rates are smoothed toward the average ((events + average × 20) ÷ (orders + 20)), so a seller with 1 order and 1 cancel is not ranked as 100%.

\- Six methods were compared: biggest revenue, worst past rate, Isolation Forest (no labels), LightGBM (Tweedie), expected loss (revenue × rate) and a cautious LightGBM. Supervised models only trained on months whose outcome was already known.



\*\*How it was tested:\*\* the winner was picked on Oct 2017 to Feb 2018, then measured on Mar to Jun 2018, months it never saw. Every idea was fixed in the config before the results were seen.



| Method | Picking months | Unseen months |

|---|---|---|

| \*\*Biggest revenue (chosen)\*\* | 17.1% | \*\*3.8%\*\* |

| LightGBM | 3.7% | 3.6% |

| LightGBM, cautious | 3.2% | 2.4% |

| Expected loss | 6.1% | 1.4% |

| Worst past rate | 2.6% | 1.3% |

| Isolation Forest | 1.6% | 1.3% |

| Random | | 0.7% |



The figures are the share of the next 3 months' seller-attributable money at risk caught by the top 20 sellers.



\*\*In plain words:\*\* of every R$10,000 that sellers will put at risk over the next 3 months, the chosen list catches about R$380 on unseen months, against R$70 for a random list.



\*\*Limitations: when not to trust it\*\*

\- \*\*It is fading.\*\* Its capture fell from 24.2% (Oct 2017) to 0.2% (Jun 2018). The drift check flags this as an ALERT.

\- \*\*A third of future seller risk (33%) comes from sellers with no history yet\*\*, and no history-based list can include them.

\- \*\*Sudden-onset sellers are missed.\*\* The worst seller in the data looked normal on 1 Jun 2018 (5 orders, 0.2% at-risk rate) and then put R$9,618.88 at risk within 3 months. It ranked #395 or lower out of 1,832 on every method.

\- \*\*Olist has no refunds table,\*\* so "at risk" means money held for undelivered orders, not confirmed losses.



\*\*Recommended use:\*\* a simple monthly check of the biggest sellers, alongside order-level risk scoring at checkout (step 4.8) and fast alerts on sudden spikes (Phase 5). Not as the only control.



\## 2. Weekly revenue forecast



\*\*Purpose:\*\* forecast revenue (what customers paid) 1 to 4 weeks ahead, with a range finance can plan with.



\*\*Data:\*\* 86 weeks of paid revenue (2 Jan 2017 to 20 Aug 2018, R$15,929,883.14). 2016 was left out because it is nearly empty.



\*\*How it was built:\*\* three methods were compared: same as last week, average of the last 4 weeks, and LightGBM. LightGBM predicts the ratio to the recent level, because tree models cannot predict numbers above anything they have seen and revenue was growing. It also gets Black Friday flags. The ranges come from each method's own past errors.



\*\*How it was tested:\*\* 46 forecast weeks (Oct 2017 to Aug 2018), each using only what was known that week. The winner was picked on origins before 5 Mar 2018 and measured on later, unseen origins.



| Method | WAPE, picking | WAPE, unseen | Bias | 80% range hit rate |

|---|---|---|---|---|

| Same as last week | 28.2% | 20.0% | −1.6% | 81.4% |

| \*\*Average of last 4 weeks (chosen)\*\* | 25.6% | \*\*18.1%\*\* | −3.4% | 77.9% |

| LightGBM | 25.8% | 18.2% | +7.2% | 80.0% |



\*\*In plain words:\*\* on a typical R$260,000 week, the forecast is off by about R$47,000 on average. The 80% range really does contain the actual number about 80% of the time (77.9%), so the range can be trusted.



\*\*Limitations: when not to trust it\*\*

\- \*\*Black Friday week (20 Nov 2017) was 2.6x a normal week\*\* (R$478,796 vs R$183,067). No method predicts the first one from data alone, so plan it from the business calendar.

\- \*\*Weeks swing between about R$150K and R$340K\*\* with no driver in the data (no marketing or promotion data). Expect about 18% error without such drivers.

\- \*\*The last week in the data (about R$150K) may be the dataset thinning out,\*\* not a real drop.

\- \*\*LightGBM tied the simple average but over-forecasts by 7%,\*\* so the simpler method was kept.



\## 3. Monitoring



`scripts/check\_drift.py` compares Apr to Jun 2017 with Apr to Jun 2018 and returns OK, WATCH or ALERT for Phase 5 alerts.



| Check | Result |

|---|---|

| Seller size (orders, revenue) | WATCH: median orders 3 to 6, revenue R$445 to R$1,003 |

| Prices (item price, delivery share) | OK |

| Cancel rate | WATCH: 0.49% to 0.25% |

| At-risk rate | ALERT: 0.89% to 0.30% (an improvement, but the model was trained on a riskier world, so retrain) |

| Late deliveries, bad reviews | OK |

| Seller queue performance | ALERT: capture fell from 19.5% to 2.2% |

| Forecast performance | OK: recent error 1.35x usual (alert line 1.5x) |



\*\*Lesson recorded:\*\* the first drift version applied PSI to smoothed seller rates and raised false alarms. Smoothed rates fall as sellers get bigger, even when their behaviour is unchanged. Behaviour is now measured with plain overall rates, and PSI is kept for size and price only.

