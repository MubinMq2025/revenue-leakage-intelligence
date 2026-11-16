# ---------------------------------------------------------------------------
# Athena table over the validator's JSON reports (one per table per load).
#   dq-reports/<table_name>/load_date=YYYY-MM-DD/<file>_dq_report.json
#
# Partition projection: Athena works out the folders from a pattern, so new
# tables and new load dates become queryable automatically, with no crawler.
# ---------------------------------------------------------------------------

resource "aws_glue_catalog_table" "dq_reports" {
  name          = "dq_reports"
  database_name = aws_glue_catalog_database.olist.name
  description   = "One data quality report per validated file (written by the validator Lambda)"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"                   = "json"
    "projection.enabled"               = "true"
    "projection.table_name.type"       = "enum"
    "projection.table_name.values"     = join(",", sort(keys(local.contracts)))
    "projection.load_date.type"        = "date"
    "projection.load_date.format"      = "yyyy-MM-dd"
    "projection.load_date.range"       = "2026-11-01,NOW"
    "projection.load_date.interval"    = "1"
    "projection.load_date.interval.unit" = "DAYS"
    "storage.location.template"        = "s3://${aws_s3_bucket.data.bucket}/dq-reports/$${table_name}/load_date=$${load_date}/"
  }

  partition_keys {
    name = "table_name"
    type = "string"
  }
  partition_keys {
    name = "load_date"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data.bucket}/dq-reports/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "dataset"
      type = "string"
    }
    columns {
      name = "source_file"
      type = "string"
    }
    columns {
      name = "contract_version"
      type = "int"
    }
    columns {
      name = "run_timestamp_utc"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "total_rows"
      type = "int"
    }
    columns {
      name = "valid_rows"
      type = "int"
    }
    columns {
      name = "rejected_rows"
      type = "int"
    }
    columns {
      name = "flagged_rows"
      type = "int"
    }
    columns {
      name = "reject_rate"
      type = "double"
    }
    columns {
      name = "rule_failures"
      type = "array<struct<rule_id:string,rule_name:string,severity:string,failed_rows:int>>"
    }
    columns {
      name = "warnings"
      type = "array<struct<rule_id:string,message:string>>"
    }
  }
}