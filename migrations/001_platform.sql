-- Applied once on a fresh local volume by the PostgreSQL entrypoint.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE TABLE platform_schema_version (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO platform_schema_version(version) VALUES (1);
