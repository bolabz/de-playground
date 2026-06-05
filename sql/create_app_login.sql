-- Create the least-privilege login the PIPELINE connects as (run as sa).
-- The app login can only SELECT the Sales schema (source tables) and the cdc schema (change
-- tables) — no writes, no other databases/schemas, not sysadmin. The pipeline never uses sa.
-- Password comes from the sqlcmd variable :APP_PASSWORD (set by create_app_login.sh from .env).
-- Idempotent: safe to re-run.
USE master;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'de_extract')
    CREATE LOGIN [de_extract] WITH PASSWORD = N'$(APP_PASSWORD)';
GO

USE WideWorldImporters;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'de_extract')
    CREATE USER [de_extract] FOR LOGIN [de_extract];
GO

-- Read-only on exactly the schemas the pipeline touches.
GRANT SELECT ON SCHEMA::Sales TO [de_extract];   -- watermark + CDC source tables
GO
-- The cdc schema only exists after `make enable-cdc`. Grant it only if present; re-run this
-- script after enabling CDC to pick up the grant (it's idempotent).
IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'cdc')
    GRANT SELECT ON SCHEMA::cdc TO [de_extract];   -- CDC change tables (read directly)
GO

PRINT 'de_extract ready: SELECT on Sales (+ cdc if enabled); no write, not sysadmin.';
GO
