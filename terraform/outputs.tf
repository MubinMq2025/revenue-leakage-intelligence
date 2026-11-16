output "bucket_name" {
  value = aws_s3_bucket.data.bucket
}

output "glue_database" {
  value = aws_glue_catalog_database.olist.name
}