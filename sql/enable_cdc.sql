-- Enable SQL Server Change Data Capture on WideWorldImporters + the four Sales tables.
-- Idempotent: safe to re-run. Requires SQL Server Agent (MSSQL_AGENT_ENABLED=true) so the
-- capture + cleanup jobs run; without Agent the change tables won't populate.
--
-- CDC captures changes from the moment a table is enabled forward — it does NOT backfill
-- existing rows. So the full/watermark extract is the initial snapshot; CDC supplies deltas.
USE WideWorldImporters;
GO

IF (SELECT is_cdc_enabled FROM sys.databases WHERE name = N'WideWorldImporters') = 0
BEGIN
    EXEC sys.sp_cdc_enable_db;
    PRINT 'CDC enabled on database.';
END
ELSE
    PRINT 'CDC already enabled on database.';
GO

DECLARE @tables TABLE (sch SYSNAME, tbl SYSNAME);
INSERT INTO @tables (sch, tbl) VALUES
    (N'Sales', N'Orders'),
    (N'Sales', N'OrderLines'),
    (N'Sales', N'Invoices'),
    (N'Sales', N'InvoiceLines');

DECLARE @sch SYSNAME, @tbl SYSNAME;
DECLARE c CURSOR FOR SELECT sch, tbl FROM @tables;
OPEN c;
FETCH NEXT FROM c INTO @sch, @tbl;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE s.name = @sch AND t.name = @tbl AND t.is_tracked_by_cdc = 1
    )
    BEGIN
        EXEC sys.sp_cdc_enable_table
            @source_schema = @sch,
            @source_name   = @tbl,
            @role_name     = NULL,            -- no gating role for a local PoC
            @supports_net_changes = 1;        -- needs a PK (these have one)
        PRINT 'CDC enabled on ' + @sch + '.' + @tbl;
    END
    ELSE
        PRINT 'CDC already enabled on ' + @sch + '.' + @tbl;
    FETCH NEXT FROM c INTO @sch, @tbl;
END
CLOSE c;
DEALLOCATE c;
GO

-- Show capture instances + whether the SQL Agent capture job exists.
EXEC sys.sp_cdc_help_change_data_capture;
GO
