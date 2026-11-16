"""
The 9 Olist tables: their source file names and how S3 keys map to tables.

Raw layout in S3:  raw/<table>/load_date=YYYY-MM-DD/<file>.csv
"""

from __future__ import annotations

import re

# table name -> original Kaggle file name
TABLE_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

RAW_KEY_PATTERN = re.compile(r"^raw/(?P<table>[a-z_]+)/(?P<partition>load_date=\d{4}-\d{2}-\d{2})/(?P<file>[^/]+\.csv)$")


def parse_raw_key(key: str) -> dict:
    """Split a raw S3 key into table, partition and file name."""
    match = RAW_KEY_PATTERN.match(key.replace("\\", "/"))
    if not match:
        raise ValueError(f"Key does not match raw/<table>/load_date=YYYY-MM-DD/<file>.csv: '{key}'")
    parts = match.groupdict()
    if parts["table"] not in TABLE_FILES:
        raise ValueError(f"Unknown table '{parts['table']}' in key '{key}'")
    return parts
