# ---------------------------------------------------------------------------
# Glue Data Catalog: the Phase 4 model outputs (seller queue, forecast, order risk,
# drift checks), so Athena and Power BI can query them like any other table.
# Columns come from config/ml_tables.yaml, the same file the Python writer uses.
# ---------------------------------------------------------------------------

locals {
  ml_tables = yamldecode(file("${path.module}/../config/ml_tables.yaml")).tables
}

resource "aws_glue_catalog_table" "ml" {
  for_each = local.ml_tables

  name          = each.key
  database_name = aws_glue_catalog_database.olist.name
  description   = each.value.description
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data.bucket}/ml/${each.key}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = each.value.columns
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}