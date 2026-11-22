-- Unity Catalog objects for the demo. Safe to re-run.
-- Run in the SQL editor on the Serverless Starter Warehouse, or with the Databricks CLI.

CREATE CATALOG IF NOT EXISTS legal_demo
  COMMENT 'Legal data demo: Indiana Supreme Court opinions (CAP)';

CREATE SCHEMA IF NOT EXISTS legal_demo.raw COMMENT 'Raw downloaded files';
CREATE VOLUME IF NOT EXISTS legal_demo.raw.cap COMMENT 'Caselaw Access Project JSON files';
CREATE VOLUME IF NOT EXISTS legal_demo.raw.code
  COMMENT 'Shared Python package (src/legal_demo) for pipeline notebooks, one folder per bundle target';
CREATE SCHEMA IF NOT EXISTS legal_demo.bronze;
CREATE SCHEMA IF NOT EXISTS legal_demo.silver;
CREATE SCHEMA IF NOT EXISTS legal_demo.gold;

-- CI/CD service principal `legal-data-demo-ci` (deploys and runs prod jobs).
GRANT USE CATALOG, USE SCHEMA, SELECT, MODIFY, CREATE TABLE, READ VOLUME, WRITE VOLUME
  ON CATALOG legal_demo TO `da061def-bd47-4813-82c4-f55e52721e0c`;
