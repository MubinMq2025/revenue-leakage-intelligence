# ---------------------------------------------------------------------------
# Glue Data Catalog: one curated table per Olist table, built from the contracts.
# Athena reads these descriptions to know where the Parquet files are and what
# columns they have. Column names and types come from config/contracts/*.yaml,
# so the Lambda, the Glue job and Athena all share one source of truth.
# ---------------------------------------------------------------------------

locals {
  contracts_dir = "${path.module}/../config/contracts"
  contracts = {
    for f in fileset(local.contracts_dir, "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${local.contracts_dir}/${f}"))
  }

  # Contract type -> Athena/Glue type (must match SPARK_TYPES in glue/curate_olist.py)
  glue_types = {
    string    = "string"
    integer   = "int"
    decimal   = "decimal(12,2)"
    double    = "double"
    timestamp = "timestamp"
  }

  # Columns every curated table gets, added by the Glue job
  lineage_columns = [
    { name = "dq_flags", type = "string" },
    { name = "load_date", type = "string" },
    { name = "curated_at", type = "timestamp" },
  ]

  curated_columns = {
    for table, contract in local.contracts : table => concat(
      [for col, spec in contract.columns : { name = try(spec.rename_to, col), type = local.glue_types[spec.type] }],
      local.lineage_columns,
    )
  }
}

resource "aws_glue_catalog_table" "curated" {
  for_each = local.contracts

  name          = each.key
  database_name = aws_glue_catalog_database.olist.name
  description   = "Curated ${each.key}: typed, de-duplicated latest snapshot (Parquet)"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "parquet"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data.bucket}/curated/${each.key}/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = local.curated_columns[each.key]
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }
}
