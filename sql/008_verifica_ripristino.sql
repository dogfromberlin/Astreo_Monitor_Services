/* =============================================================================
   Astreo Monitor 2.5 - 008_verifica_ripristino.sql
   Permette all'utente astreo_monitor_app di verificare (DBCC CHECKDB) ed eliminare
   SOLO i database temporanei della verifica del ripristino (astreo_restoretest_*),
   senza dargli permessi di amministratore.

   Tecnica: due procedure in master firmate con un certificato. Il certificato è
   associato a un login con i permessi necessari; quei permessi valgono SOLO
   dentro le due procedure, che accettano esclusivamente nomi astreo_restoretest_*.
   La chiave privata viene eliminata dopo la firma: nessuno può firmare altro codice.
   Da eseguire come sa. Rieseguibile (ricrea certificato e firme).
   ============================================================================= */
USE master;
GO

-- 1. Pulizia di un'eventuale installazione precedente
IF OBJECT_ID(N'dbo.astreo_restoretest_check', N'P') IS NOT NULL DROP PROCEDURE dbo.astreo_restoretest_check;
IF OBJECT_ID(N'dbo.astreo_restoretest_drop', N'P') IS NOT NULL DROP PROCEDURE dbo.astreo_restoretest_drop;
IF EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'astreo_restoretest_signer') DROP LOGIN astreo_restoretest_signer;
IF EXISTS (SELECT 1 FROM sys.certificates WHERE name = N'astreo_restoretest_cert') DROP CERTIFICATE astreo_restoretest_cert;
GO

-- 2. Procedure (accettano solo nomi astreo_restoretest_*)
CREATE PROCEDURE dbo.astreo_restoretest_check @db sysname
AS
BEGIN
    SET NOCOUNT ON;
    IF @db NOT LIKE N'<server>[_]restoretest[_]%' THROW 50001, N'Nome di database non ammesso', 1;
    IF DB_ID(@db) IS NULL THROW 50002, N'Database inesistente', 1;
    DECLARE @q nvarchar(max) = N'DBCC CHECKDB (' + QUOTENAME(@db) + N') WITH NO_INFOMSGS';
    EXEC (@q);
    SET @q = N'SELECT t.name AS tabella, SUM(p.rows) AS righe FROM ' + QUOTENAME(@db) + N'.sys.tables t '
           + N'JOIN ' + QUOTENAME(@db) + N'.sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1) '
           + N'GROUP BY t.name ORDER BY t.name';
    EXEC (@q);
END
GO
CREATE PROCEDURE dbo.astreo_restoretest_drop @db sysname
AS
BEGIN
    SET NOCOUNT ON;
    IF @db NOT LIKE N'<server>[_]restoretest[_]%' THROW 50001, N'Nome di database non ammesso', 1;
    IF DB_ID(@db) IS NULL RETURN;
    DECLARE @q nvarchar(max) = N'ALTER DATABASE ' + QUOTENAME(@db) + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE; '
                             + N'DROP DATABASE ' + QUOTENAME(@db) + N';';
    EXEC (@q);
END
GO

-- 3. Certificato con password casuale usata solo qui, firma, rimozione della chiave privata
DECLARE @pwd nvarchar(80) = CONVERT(nvarchar(36), NEWID()) + N'Aa1!' + CONVERT(nvarchar(36), NEWID());
DECLARE @q nvarchar(max);
SET @q = N'CREATE CERTIFICATE astreo_restoretest_cert ENCRYPTION BY PASSWORD = ' + QUOTENAME(@pwd, '''')
       + N' WITH SUBJECT = ''Astreo Monitor - verifica del ripristino'', EXPIRY_DATE = ''20991231'';';
EXEC (@q);
SET @q = N'ADD SIGNATURE TO dbo.astreo_restoretest_check BY CERTIFICATE astreo_restoretest_cert WITH PASSWORD = ' + QUOTENAME(@pwd, '''') + N';'
       + N'ADD SIGNATURE TO dbo.astreo_restoretest_drop BY CERTIFICATE astreo_restoretest_cert WITH PASSWORD = ' + QUOTENAME(@pwd, '''') + N';';
EXEC (@q);
ALTER CERTIFICATE astreo_restoretest_cert REMOVE PRIVATE KEY;
GO
CREATE LOGIN astreo_restoretest_signer FROM CERTIFICATE astreo_restoretest_cert;
ALTER SERVER ROLE sysadmin ADD MEMBER astreo_restoretest_signer;
GO

-- 4. Solo l'esecuzione delle due procedure all'utente applicativo
GRANT EXECUTE ON dbo.astreo_restoretest_check TO astreo_monitor_app;
GRANT EXECUTE ON dbo.astreo_restoretest_drop TO astreo_monitor_app;
GO

-- 5. Verifica
SELECT o.name AS procedura, c.name AS certificato
FROM sys.crypt_properties cp
JOIN sys.objects o ON o.object_id = cp.major_id
JOIN sys.certificates c ON c.thumbprint = cp.thumbprint
WHERE o.name LIKE N'<server>[_]restoretest[_]%';
GO
