-- Waves, currents and sea temperature now come from Copernicus Marine; NOAA GFS keeps wind.
-- The superseded products stay defined for replay of retained releases but are no longer served.
ALTER TABLE field_products DROP CONSTRAINT field_products_product_id_check;
ALTER TABLE field_products ADD CONSTRAINT field_products_product_id_check CHECK(product_id IN ('noaa_oisst','noaa_gfs_wave','noaa_gfs_weather','hycom_espc','cmems_wave','cmems_currents','cmems_sst'));
INSERT INTO field_products VALUES
 ('cmems_wave','{"refresh":true}'),('cmems_currents','{"refresh":true}'),('cmems_sst','{"refresh":true}');
UPDATE field_products SET metadata=metadata || '{"refresh":true}' WHERE product_id='noaa_gfs_weather';
UPDATE field_products SET metadata=metadata || '{"refresh":false}' WHERE product_id IN ('noaa_oisst','noaa_gfs_wave','hycom_espc');
DELETE FROM field_selection WHERE product_id IN ('noaa_oisst','noaa_gfs_wave','hycom_espc');
INSERT INTO platform_schema_version(version) VALUES (19);
