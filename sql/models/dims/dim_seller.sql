-- dim_seller: one row per seller
CREATE OR REPLACE VIEW rli_dev_olist.dim_seller AS
SELECT
    seller_id,
    seller_zip_code_prefix  AS zip_code_prefix,
    seller_city             AS city,
    seller_state            AS state
FROM rli_dev_olist.sellers;