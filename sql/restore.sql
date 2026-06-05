-- Restore a .bak into the Linux SQL Server container, relocating every file with WITH MOVE.
--
-- Why this is dynamic: the WideWorldImporters backups were taken on Windows, so they carry
-- Windows paths (D:\Data\..., E:\Log\...) that don't exist on Linux. SQL Server refuses to
-- restore until each logical file is redirected to a valid path. Rather than hard-code the
-- logical names (they differ between the OLTP and DW backups, and across versions), we read
-- them from RESTORE FILELISTONLY and build the MOVE clauses on the fly. This also correctly
-- handles the in-memory OLTP filegroup, whose file (Type 'S'/'F') must point at a DIRECTORY,
-- not a file with an extension.
--
-- Invoked with sqlcmd scripting variables:  -v DBNAME=... BAKFILE=...
SET NOCOUNT ON;

DECLARE @bak     NVARCHAR(260) = N'$(BAKFILE)';
DECLARE @db      SYSNAME       = N'$(DBNAME)';
DECLARE @dataDir NVARCHAR(260) = N'/var/opt/mssql/data/';

IF OBJECT_ID('tempdb..#fl') IS NOT NULL DROP TABLE #fl;
CREATE TABLE #fl (
    LogicalName          NVARCHAR(128),
    PhysicalName         NVARCHAR(260),
    [Type]               CHAR(1),
    FileGroupName        NVARCHAR(128) NULL,
    Size                 NUMERIC(20,0),
    MaxSize              NUMERIC(20,0),
    FileID               BIGINT,
    CreateLSN            NUMERIC(25,0),
    DropLSN              NUMERIC(25,0) NULL,
    UniqueId             UNIQUEIDENTIFIER,
    ReadOnlyLSN          NUMERIC(25,0) NULL,
    ReadWriteLSN         NUMERIC(25,0) NULL,
    BackupSizeInBytes    BIGINT,
    SourceBlockSize      INT,
    FileGroupId          INT,
    LogGroupGUID         UNIQUEIDENTIFIER NULL,
    DifferentialBaseLSN  NUMERIC(25,0) NULL,
    DifferentialBaseGUID UNIQUEIDENTIFIER NULL,
    IsReadOnly           BIT,
    IsPresent            BIT,
    TDEThumbprint        VARBINARY(32) NULL,
    SnapshotUrl          NVARCHAR(360) NULL
);
INSERT INTO #fl EXEC ('RESTORE FILELISTONLY FROM DISK = N''' + @bak + '''');

PRINT '--- Logical files in ' + @db + ' backup ---';
SELECT LogicalName, [Type], FileGroupName FROM #fl ORDER BY FileID;

-- Build one MOVE clause per file. Extension is cosmetic to SQL Server; the in-memory
-- filegroup (Type S/F) must be a directory (no extension).
DECLARE @move NVARCHAR(MAX) = N'';
SELECT @move = @move + N',
    MOVE ' + QUOTENAME(LogicalName, '''')
        + N' TO ''' + @dataDir + @db + N'_' + LogicalName
        + CASE [Type]
              WHEN 'L' THEN N'.ldf'   -- log
              WHEN 'S' THEN N''       -- FILESTREAM / memory-optimized container = directory
              WHEN 'F' THEN N''
              ELSE N'.mdf'            -- rows data
          END
        + N''''
FROM #fl;

DECLARE @sql NVARCHAR(MAX) =
    N'RESTORE DATABASE ' + QUOTENAME(@db) + N'
FROM DISK = N''' + @bak + N'''
WITH FILE = 1, REPLACE, NOUNLOAD, STATS = 5' + @move + N';';

PRINT '--- Executing ---';
PRINT @sql;
EXEC (@sql);
