-- dim_date: one row per calendar day, 2016-01-01 to 2018-12-31
-- sequence() returns timestamp(0), which Athena views cannot store, so cast to DATE first.
CREATE OR REPLACE VIEW rli_dev_olist.dim_date AS
WITH days AS (
    SELECT CAST(d AS date) AS d
    FROM UNNEST(sequence(DATE '2016-01-01', DATE '2018-12-31', INTERVAL '1' DAY)) AS t (d)
)
SELECT
    d                                           AS date_key,
    year(d)                                     AS year,
    quarter(d)                                  AS quarter,
    month(d)                                    AS month,
    date_format(CAST(d AS timestamp), '%b')     AS month_name,
    date_trunc('month', d)                      AS month_start,
    date_trunc('week', d)                       AS week_start,
    day_of_week(d)                              AS day_of_week,   -- 1 = Monday, 7 = Sunday
    day_of_week(d) IN (6, 7)                    AS is_weekend
FROM days;