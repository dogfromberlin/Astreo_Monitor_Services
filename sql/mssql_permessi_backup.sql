/* =============================================================================
   Astreo Monitor - SQL Server: permessi per il backup notturno e la sua verifica.
   Serve solo se il database non è stato preparato dall'installatore (che li concede da solo).
   Da eseguire come amministratore (es. sa). Modifica i due valori qui sotto, poi esegui tutto.
   ============================================================================= */
DECLARE @app_user  sysname = N'astreo_monitor_app';        -- login dell'applicazione ([database] user)
DECLARE @databases nvarchar(max) = N'astreo_monitor';      -- database da salvare, separati da virgola

DECLARE @u nvarchar(300) = QUOTENAME(@app_user);
DECLARE @n nvarchar(300) = QUOTENAME(@app_user, '''');
DECLARE @q nvarchar(max), @db sysname;

-- CREATE DATABASE in master: serve a RESTORE VERIFYONLY e alla verifica mensile del ripristino
SET @q = N'USE master; IF DATABASE_PRINCIPAL_ID(N' + @n + N') IS NULL CREATE USER ' + @u + N' FOR LOGIN ' + @u
       + N'; GRANT CREATE DATABASE TO ' + @u + N';';
EXEC (@q);

-- db_backupoperator in ogni database da salvare
DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT LTRIM(RTRIM(value)) FROM STRING_SPLIT(@databases, N',');
OPEN c;
FETCH NEXT FROM c INTO @db;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @q = N'USE ' + QUOTENAME(@db) + N'; IF DATABASE_PRINCIPAL_ID(N' + @n + N') IS NULL CREATE USER ' + @u
           + N' FOR LOGIN ' + @u + N'; ALTER ROLE db_backupoperator ADD MEMBER ' + @u + N';';
    EXEC (@q);
    PRINT N'Permessi di backup concessi su ' + @db;
    FETCH NEXT FROM c INTO @db;
END
CLOSE c;
GO
