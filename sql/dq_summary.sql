-- Data quality summary: one row per table for a given load date.
-- rules_triggered lists every rule that caught at least one row, e.g. OR006=8
SELECT
    dataset,
    status,
    total_rows,
    rejected_rows,
    flagged_rows,
    ROUND(reject_rate * 100, 2)                                   AS reject_pct,
    cardinality(warnings)                                         AS warning_count,
    array_join(
        transform(
            filter(rule_failures, r -> r.failed_rows > 0),
            r -> r.rule_id || '=' || CAST(r.failed_rows AS varchar)
        ),
        ', '
    )                                                             AS rules_triggered
FROM rli_dev_olist.dq_reports
WHERE load_date = '2026-11-16'
ORDER BY dataset;