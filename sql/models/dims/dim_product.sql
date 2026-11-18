-- dim_product: one row per product, with an English category that is never blank.
-- Category order of preference: official translation, our own seed for the 2 categories
-- missing from Kaggle's translation table, then the Portuguese name, then 'unknown'.
CREATE OR REPLACE VIEW rli_dev_olist.dim_product AS
WITH missing_translations (product_category_name, product_category_name_english) AS (
    VALUES
        ('pc_gamer', 'pc_gamer'),
        ('portateis_cozinha_e_preparadores_de_alimentos', 'portable_kitchen_and_food_preparers')
)
SELECT
    p.product_id,
    COALESCE(t.product_category_name_english, m.product_category_name_english,
             p.product_category_name, 'unknown')                                     AS category,
    p.product_category_name                                                          AS category_pt,
    p.product_photos_qty                                                             AS photos_qty,
    p.product_weight_g                                                               AS weight_g,
    p.product_length_cm * p.product_height_cm * p.product_width_cm                   AS volume_cm3
FROM rli_dev_olist.products p
LEFT JOIN rli_dev_olist.category_translation t
       ON t.product_category_name = p.product_category_name
LEFT JOIN missing_translations m
       ON m.product_category_name = p.product_category_name;