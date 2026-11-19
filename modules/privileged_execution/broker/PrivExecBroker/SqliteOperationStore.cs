using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace PrivExecBroker;

internal static class WinSqlite3
{
    private const string Dll = "winsqlite3.dll";
    public const int SQLITE_OK = 0;
    public const int SQLITE_CONSTRAINT = 19;
    public const int SQLITE_ROW = 100;
    public const int SQLITE_DONE = 101;
    public const int SQLITE_OPEN_READWRITE = 0x00000002;
    public const int SQLITE_OPEN_CREATE = 0x00000004;
    public const int SQLITE_OPEN_FULLMUTEX = 0x00010000;
    public static readonly IntPtr SQLITE_TRANSIENT = new(-1);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_open_v2(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string filename,
        out IntPtr ppDb,
        int flags,
        IntPtr zVfs);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_close_v2(IntPtr db);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_busy_timeout(IntPtr db, int ms);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_exec(
        IntPtr db,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string sql,
        IntPtr callback,
        IntPtr arg,
        out IntPtr errmsg);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern void sqlite3_free(IntPtr ptr);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_prepare_v2(
        IntPtr db,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string zSql,
        int nByte,
        out IntPtr ppStmt,
        out IntPtr pzTail);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_step(IntPtr stmt);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_finalize(IntPtr stmt);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_changes(IntPtr db);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern IntPtr sqlite3_errmsg(IntPtr db);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_bind_text(
        IntPtr stmt,
        int index,
        byte[] value,
        int nBytes,
        IntPtr destructor);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_bind_int(IntPtr stmt, int index, int value);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_bind_null(IntPtr stmt, int index);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_column_type(IntPtr stmt, int iCol);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern IntPtr sqlite3_column_text(IntPtr stmt, int iCol);

    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, ExactSpelling = true)]
    public static extern int sqlite3_column_int(IntPtr stmt, int iCol);

    public const int SQLITE_NULL = 5;

    public static string GetErrorMessage(IntPtr db)
    {
        IntPtr ptr = sqlite3_errmsg(db);
        return ptr == IntPtr.Zero ? "unknown sqlite error" : (Marshal.PtrToStringUTF8(ptr) ?? "unknown sqlite error");
    }

    public static void BindTextOrNull(IntPtr stmt, int index, string? value)
    {
        if (value is null)
        {
            Check(sqlite3_bind_null(stmt, index), "sqlite3_bind_null");
            return;
        }
        byte[] utf8 = Encoding.UTF8.GetBytes(value);
        Check(sqlite3_bind_text(stmt, index, utf8, utf8.Length, SQLITE_TRANSIENT), "sqlite3_bind_text");
    }

    public static string? ReadNullableString(IntPtr stmt, int col)
    {
        if (sqlite3_column_type(stmt, col) == SQLITE_NULL) return null;
        IntPtr ptr = sqlite3_column_text(stmt, col);
        return ptr == IntPtr.Zero ? null : Marshal.PtrToStringUTF8(ptr);
    }

    public static int? ReadNullableInt(IntPtr stmt, int col)
    {
        if (sqlite3_column_type(stmt, col) == SQLITE_NULL) return null;
        return sqlite3_column_int(stmt, col);
    }

    public static void Check(int rc, string op, IntPtr db = default)
    {
        if (rc != SQLITE_OK)
        {
            string detail = db != IntPtr.Zero ? $": {GetErrorMessage(db)}" : string.Empty;
            throw new InvalidOperationException($"SQLite {op} failed (rc={rc}){detail}");
        }
    }
}

public sealed class SqliteOperationStore : IOperationStore, IDisposable
{
    private readonly object _sync = new();
    private readonly Dictionary<string, string> _activeTargetMutations = new(StringComparer.OrdinalIgnoreCase);
    private IntPtr _db;
    private bool _disposed;

    public SqliteOperationStore(string dbPath)
    {
        SecurityAndAcl.AssertNoReparsePoints(dbPath, "SQLite database path");
        string? dir = Path.GetDirectoryName(Path.GetFullPath(dbPath));
        if (!string.IsNullOrWhiteSpace(dir))
        {
            Directory.CreateDirectory(dir);
            SecurityAndAcl.AssertNoReparsePoints(dir, "SQLite database directory");
        }

        int flags = WinSqlite3.SQLITE_OPEN_READWRITE | WinSqlite3.SQLITE_OPEN_CREATE | WinSqlite3.SQLITE_OPEN_FULLMUTEX;
        int rc = WinSqlite3.sqlite3_open_v2(dbPath, out _db, flags, IntPtr.Zero);
        if (rc != WinSqlite3.SQLITE_OK)
        {
            string msg = _db != IntPtr.Zero ? WinSqlite3.GetErrorMessage(_db) : $"rc={rc}";
            if (_db != IntPtr.Zero) WinSqlite3.sqlite3_close_v2(_db);
            _db = IntPtr.Zero;
            throw new InvalidOperationException($"Failed to open SQLite database '{dbPath}': {msg}");
        }

        WinSqlite3.Check(WinSqlite3.sqlite3_busy_timeout(_db, 5000), "sqlite3_busy_timeout", _db);
        ExecNonQuery("PRAGMA journal_mode=WAL;");
        ExecNonQuery("PRAGMA synchronous=FULL;");
        ExecNonQuery("""
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                client_sid TEXT NOT NULL,
                request_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                canonical_payload_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                authorized INTEGER NOT NULL,
                exit_code INTEGER,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                diagnostic_category TEXT,
                result_json TEXT,
                evidence_json TEXT NOT NULL,
                postcondition_verified INTEGER NOT NULL,
                error TEXT,
                UNIQUE(client_sid, request_id)
            );
            """);
    }

    public IdempotencyLookup CheckIdempotency(string clientSid, string requestId, string canonicalPayloadHash)
    {
        lock (_sync)
        {
            const string sql = """
                SELECT operation_id, client_sid, request_id, capability, target_type, target_id,
                       mode, canonical_payload_hash, state, authorized, exit_code, started_at,
                       finished_at, diagnostic_category, result_json, evidence_json,
                       postcondition_verified, error
                FROM operations
                WHERE client_sid = ?1 AND request_id = ?2
                LIMIT 1;
                """;
            IntPtr stmt = Prepare(sql);
            try
            {
                WinSqlite3.BindTextOrNull(stmt, 1, clientSid);
                WinSqlite3.BindTextOrNull(stmt, 2, requestId);
                int step = WinSqlite3.sqlite3_step(stmt);
                if (step == WinSqlite3.SQLITE_DONE)
                {
                    return new IdempotencyLookup(IdempotencyLookupKind.NewRequest, null);
                }
                if (step != WinSqlite3.SQLITE_ROW)
                {
                    throw new InvalidOperationException($"SQLite step failed: {WinSqlite3.GetErrorMessage(_db)}");
                }
                OperationRecord existing = ReadRecord(stmt);
                if (!string.Equals(existing.CanonicalPayloadHash, canonicalPayloadHash, StringComparison.Ordinal))
                {
                    return new IdempotencyLookup(IdempotencyLookupKind.PayloadMismatch, existing);
                }
                return new IdempotencyLookup(IdempotencyLookupKind.ReplayExisting, existing);
            }
            finally
            {
                WinSqlite3.sqlite3_finalize(stmt);
            }
        }
    }

    public void InsertOperation(OperationRecord record)
    {
        if (!TryInsertOperation(record, out _))
        {
            throw new InvalidOperationException($"Duplicate client_sid/request_id '{record.RequestId}'.");
        }
    }

    public bool TryInsertOperation(OperationRecord record, out IdempotencyLookup conflict)
    {
        lock (_sync)
        {
            const string sql = """
                INSERT INTO operations (
                    operation_id, client_sid, request_id, capability, target_type, target_id,
                    mode, canonical_payload_hash, state, authorized, exit_code, started_at,
                    finished_at, diagnostic_category, result_json, evidence_json,
                    postcondition_verified, error
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16, ?17, ?18);
                """;
            IntPtr stmt = Prepare(sql);
            int step;
            try
            {
                WinSqlite3.BindTextOrNull(stmt, 1, record.OperationId);
                WinSqlite3.BindTextOrNull(stmt, 2, record.ClientSid);
                WinSqlite3.BindTextOrNull(stmt, 3, record.RequestId);
                WinSqlite3.BindTextOrNull(stmt, 4, record.Capability);
                WinSqlite3.BindTextOrNull(stmt, 5, record.TargetType);
                WinSqlite3.BindTextOrNull(stmt, 6, record.TargetId);
                WinSqlite3.BindTextOrNull(stmt, 7, record.Mode);
                WinSqlite3.BindTextOrNull(stmt, 8, record.CanonicalPayloadHash);
                WinSqlite3.BindTextOrNull(stmt, 9, OperationStateNames.ToWire(record.State));
                WinSqlite3.Check(WinSqlite3.sqlite3_bind_int(stmt, 10, record.Authorized ? 1 : 0), "bind authorized", _db);
                if (record.ExitCode.HasValue)
                    WinSqlite3.Check(WinSqlite3.sqlite3_bind_int(stmt, 11, record.ExitCode.Value), "bind exit_code", _db);
                else
                    WinSqlite3.Check(WinSqlite3.sqlite3_bind_null(stmt, 11), "bind null exit_code", _db);
                WinSqlite3.BindTextOrNull(stmt, 12, record.StartedAtUtc.ToString("O"));
                WinSqlite3.BindTextOrNull(stmt, 13, record.FinishedAtUtc?.ToString("O"));
                WinSqlite3.BindTextOrNull(stmt, 14, record.DiagnosticCategory);
                WinSqlite3.BindTextOrNull(stmt, 15, record.ResultJson.HasValue ? record.ResultJson.Value.GetRawText() : null);
                WinSqlite3.BindTextOrNull(stmt, 16, JsonSerializer.Serialize(record.Evidence));
                WinSqlite3.Check(WinSqlite3.sqlite3_bind_int(stmt, 17, record.PostconditionVerified ? 1 : 0), "bind postcondition", _db);
                WinSqlite3.BindTextOrNull(stmt, 18, record.Error);

                step = WinSqlite3.sqlite3_step(stmt);
            }
            finally
            {
                WinSqlite3.sqlite3_finalize(stmt);
            }

            if (step == WinSqlite3.SQLITE_DONE)
            {
                conflict = new IdempotencyLookup(IdempotencyLookupKind.NewRequest, null);
                return true;
            }

            if (step == WinSqlite3.SQLITE_CONSTRAINT)
            {
                conflict = CheckIdempotency(record.ClientSid, record.RequestId, record.CanonicalPayloadHash);
                return false;
            }

            throw new InvalidOperationException($"SQLite insert failed: {WinSqlite3.GetErrorMessage(_db)}");
        }
    }

    public void UpdateOperationState(
        string operationId,
        OperationState state,
        int? exitCode,
        DateTimeOffset? finishedAtUtc,
        string? diagnosticCategory,
        JsonElement? resultJson,
        List<string> evidence,
        bool postconditionVerified,
        string? error)
    {
        lock (_sync)
        {
            const string sql = """
                UPDATE operations
                SET state = ?1,
                    exit_code = ?2,
                    finished_at = ?3,
                    diagnostic_category = ?4,
                    result_json = ?5,
                    evidence_json = ?6,
                    postcondition_verified = ?7,
                    error = ?8
                WHERE operation_id = ?9;
                """;
            IntPtr stmt = Prepare(sql);
            try
            {
                WinSqlite3.BindTextOrNull(stmt, 1, OperationStateNames.ToWire(state));
                if (exitCode.HasValue)
                    WinSqlite3.Check(WinSqlite3.sqlite3_bind_int(stmt, 2, exitCode.Value), "bind exit_code", _db);
                else
                    WinSqlite3.Check(WinSqlite3.sqlite3_bind_null(stmt, 2), "bind null exit_code", _db);
                WinSqlite3.BindTextOrNull(stmt, 3, finishedAtUtc?.ToString("O"));
                WinSqlite3.BindTextOrNull(stmt, 4, diagnosticCategory);
                WinSqlite3.BindTextOrNull(stmt, 5, resultJson.HasValue ? resultJson.Value.GetRawText() : null);
                WinSqlite3.BindTextOrNull(stmt, 6, JsonSerializer.Serialize(evidence));
                WinSqlite3.Check(WinSqlite3.sqlite3_bind_int(stmt, 7, postconditionVerified ? 1 : 0), "bind postcondition", _db);
                WinSqlite3.BindTextOrNull(stmt, 8, error);
                WinSqlite3.BindTextOrNull(stmt, 9, operationId);

                int step = WinSqlite3.sqlite3_step(stmt);
                if (step != WinSqlite3.SQLITE_DONE)
                {
                    throw new InvalidOperationException($"SQLite update failed: {WinSqlite3.GetErrorMessage(_db)}");
                }
                if (WinSqlite3.sqlite3_changes(_db) == 0)
                {
                    throw new KeyNotFoundException($"Unknown operation '{operationId}'.");
                }
            }
            finally
            {
                WinSqlite3.sqlite3_finalize(stmt);
            }
        }
    }

    public OperationRecord? GetByOperationId(string operationId)
    {
        lock (_sync)
        {
            const string sql = """
                SELECT operation_id, client_sid, request_id, capability, target_type, target_id,
                       mode, canonical_payload_hash, state, authorized, exit_code, started_at,
                       finished_at, diagnostic_category, result_json, evidence_json,
                       postcondition_verified, error
                FROM operations
                WHERE operation_id = ?1
                LIMIT 1;
                """;
            IntPtr stmt = Prepare(sql);
            try
            {
                WinSqlite3.BindTextOrNull(stmt, 1, operationId);
                int step = WinSqlite3.sqlite3_step(stmt);
                if (step == WinSqlite3.SQLITE_DONE) return null;
                if (step != WinSqlite3.SQLITE_ROW)
                {
                    throw new InvalidOperationException($"SQLite select failed: {WinSqlite3.GetErrorMessage(_db)}");
                }
                return ReadRecord(stmt);
            }
            finally
            {
                WinSqlite3.sqlite3_finalize(stmt);
            }
        }
    }

    public bool TryAcquireTargetMutationLock(string targetId, string operationId)
    {
        lock (_sync)
        {
            if (_activeTargetMutations.ContainsKey(targetId))
            {
                return false;
            }
            _activeTargetMutations[targetId] = operationId;
            return true;
        }
    }

    public void ReleaseTargetMutationLock(string targetId, string operationId)
    {
        lock (_sync)
        {
            if (_activeTargetMutations.TryGetValue(targetId, out string? owner) &&
                string.Equals(owner, operationId, StringComparison.Ordinal))
            {
                _activeTargetMutations.Remove(targetId);
            }
        }
    }

    public int MarkInterruptedExecutionsAsOutcomeUnknown()
    {
        lock (_sync)
        {
            const string sql = """
                UPDATE operations
                SET state = 'outcome_unknown',
                    finished_at = ?1,
                    diagnostic_category = 'broker_crash_unknown_outcome',
                    postcondition_verified = 0,
                    error = 'Broker terminated while operation was executing; manual reconciliation required before retry.'
                WHERE state = 'executing';
                """;
            IntPtr stmt = Prepare(sql);
            try
            {
                WinSqlite3.BindTextOrNull(stmt, 1, DateTimeOffset.UtcNow.ToString("O"));
                int step = WinSqlite3.sqlite3_step(stmt);
                if (step != WinSqlite3.SQLITE_DONE)
                {
                    throw new InvalidOperationException($"SQLite crash recovery update failed: {WinSqlite3.GetErrorMessage(_db)}");
                }
                return WinSqlite3.sqlite3_changes(_db);
            }
            finally
            {
                WinSqlite3.sqlite3_finalize(stmt);
            }
        }
    }

    private IntPtr Prepare(string sql)
    {
        WinSqlite3.Check(WinSqlite3.sqlite3_prepare_v2(_db, sql, -1, out IntPtr stmt, out _), "sqlite3_prepare_v2", _db);
        return stmt;
    }

    private void ExecNonQuery(string sql)
    {
        int rc = WinSqlite3.sqlite3_exec(_db, sql, IntPtr.Zero, IntPtr.Zero, out IntPtr errmsg);
        if (rc != WinSqlite3.SQLITE_OK)
        {
            string msg = errmsg != IntPtr.Zero ? (Marshal.PtrToStringUTF8(errmsg) ?? "sqlite error") : $"rc={rc}";
            if (errmsg != IntPtr.Zero) WinSqlite3.sqlite3_free(errmsg);
            throw new InvalidOperationException($"SQLite exec failed: {msg}");
        }
    }

    private static OperationRecord ReadRecord(IntPtr stmt)
    {
        string opId = WinSqlite3.ReadNullableString(stmt, 0)!;
        string clientSid = WinSqlite3.ReadNullableString(stmt, 1)!;
        string requestId = WinSqlite3.ReadNullableString(stmt, 2)!;
        string capability = WinSqlite3.ReadNullableString(stmt, 3)!;
        string targetType = WinSqlite3.ReadNullableString(stmt, 4)!;
        string targetId = WinSqlite3.ReadNullableString(stmt, 5)!;
        string mode = WinSqlite3.ReadNullableString(stmt, 6)!;
        string payloadHash = WinSqlite3.ReadNullableString(stmt, 7)!;
        OperationState state = OperationStateNames.FromWire(WinSqlite3.ReadNullableString(stmt, 8) ?? "outcome_unknown");
        bool authorized = WinSqlite3.sqlite3_column_int(stmt, 9) != 0;
        int? exitCode = WinSqlite3.ReadNullableInt(stmt, 10);
        DateTimeOffset startedAt = DateTimeOffset.Parse(WinSqlite3.ReadNullableString(stmt, 11)!);
        string? finStr = WinSqlite3.ReadNullableString(stmt, 12);
        DateTimeOffset? finishedAt = finStr is not null ? DateTimeOffset.Parse(finStr) : null;
        string? diagCat = WinSqlite3.ReadNullableString(stmt, 13);
        string? resStr = WinSqlite3.ReadNullableString(stmt, 14);
        JsonElement? resultJson = null;
        if (!string.IsNullOrEmpty(resStr))
        {
            using JsonDocument doc = JsonDocument.Parse(resStr);
            resultJson = doc.RootElement.Clone();
        }
        string evStr = WinSqlite3.ReadNullableString(stmt, 15) ?? "[]";
        List<string> evidence = JsonSerializer.Deserialize<List<string>>(evStr) ?? new List<string>();
        bool postVerified = WinSqlite3.sqlite3_column_int(stmt, 16) != 0;
        string? err = WinSqlite3.ReadNullableString(stmt, 17);

        return new OperationRecord(
            opId, requestId, clientSid, capability, targetType, targetId, mode, payloadHash,
            state, authorized, exitCode, startedAt, finishedAt, diagCat, resultJson, evidence, postVerified, err);
    }

    public void Dispose()
    {
        lock (_sync)
        {
            if (!_disposed && _db != IntPtr.Zero)
            {
                WinSqlite3.sqlite3_close_v2(_db);
                _db = IntPtr.Zero;
                _disposed = true;
            }
        }
    }
}
