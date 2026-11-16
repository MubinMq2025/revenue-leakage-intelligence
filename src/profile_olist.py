"""Profile the 9 Olist CSVs: size, nulls, duplicates, keys, date ranges, relationships."""
from pathlib import Path
import pandas as pd

DATA = Path("data/olist")

# table name -> (file name, primary key columns)
TABLES = {
    "orders": ("olist_orders_dataset.csv", ["order_id"]),
    "order_items": ("olist_order_items_dataset.csv", ["order_id", "order_item_id"]),
    "payments": ("olist_order_payments_dataset.csv", ["order_id", "payment_sequential"]),
    "reviews": ("olist_order_reviews_dataset.csv", ["review_id"]),
    "customers": ("olist_customers_dataset.csv", ["customer_id"]),
    "sellers": ("olist_sellers_dataset.csv", ["seller_id"]),
    "products": ("olist_products_dataset.csv", ["product_id"]),
    "geolocation": ("olist_geolocation_dataset.csv", None),
    "category_translation": ("product_category_name_translation.csv", ["product_category_name"]),
}

# 1. Check each table on its own
dfs = {}
for name, (file, key) in TABLES.items():
    df = pd.read_csv(DATA / file)
    dfs[name] = df
    print(f"\n=== {name} ===")
    print(f"rows: {len(df):,}  columns: {df.shape[1]}")

    nulls = df.isna().sum()
    nulls = nulls[nulls > 0]
    print("nulls:", "none" if nulls.empty else nulls.to_dict())

    print(f"fully duplicated rows: {df.duplicated().sum():,}")
    if key:
        print(f"duplicate keys {key}: {df.duplicated(subset=key).sum():,}")

    for col in df.columns:
        if "date" in col or "timestamp" in col or col.endswith("_at"):
            dates = pd.to_datetime(df[col], errors="coerce")
            print(f"{col}: {dates.min()} to {dates.max()}")

# 2. Check how the tables link together
orders, items = dfs["orders"], dfs["order_items"]
pay, cust = dfs["payments"], dfs["customers"]

def orphans(child, child_col, parent, parent_col):
    """Count child rows whose key is missing from the parent table."""
    return (~child[child_col].isin(parent[parent_col])).sum()

print("\n=== relationship checks ===")
print("items with no matching order:", orphans(items, "order_id", orders, "order_id"))
print("payments with no matching order:", orphans(pay, "order_id", orders, "order_id"))
print("orders with no matching customer:", orphans(orders, "customer_id", cust, "customer_id"))
print("orders with no items:", orphans(orders, "order_id", items, "order_id"))
print("orders with no payment:", orphans(orders, "order_id", pay, "order_id"))

# 3. The customer key trap
print("\n=== customer key check ===")
print(f"unique customer_id: {cust['customer_id'].nunique():,}")
print(f"unique customer_unique_id: {cust['customer_unique_id'].nunique():,}")

# 4. Confirm the delivery finding
print("\n=== delivery check ===")
delivered = orders[orders["order_status"] == "delivered"]
print("delivered orders with no delivery date:", delivered["order_delivered_customer_date"].isna().sum())