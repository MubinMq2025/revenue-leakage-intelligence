-- dim_product: one row per product, with an English category that is never blank.
-- Category order of preference: English translation, then Portuguese name, then 'unknown'.
CREATE OR REPLACE VIEW rli_dev_olist.dim_product AS
SELECT
    p.product_id,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown')  AS category,
    p.product_category_name                                                          AS category_pt,
    p.product_photos_qty                                                             AS photos_qty,
    p.product_weight_g                                                               AS weight_g,
    p.product_length_cm * p.product_height_cm * p.product_width_cm                   AS volume_cm3
FROM rli_dev_olist.products p
LEFT JOIN rli_dev_olist.category_translation t
       ON t.product_category_name = p.product_category_name;