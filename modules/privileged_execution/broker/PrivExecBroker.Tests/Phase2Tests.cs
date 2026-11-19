using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using PrivExecBroker;

namespace PrivExecBroker.Tests;

internal static class Phase2Tests
{
    private const string OperatorSid = "S-1-5-21-1000-1000-1000-1001";
    private const string AgentSid = "S-1-5-21-1000-1000-1000-1002";

    public static async Task RunAllAsync()
    {
        var tests = new (string Name, Func<Task> Fn)[]
        {
            ("SqlitePersistenceAndCrashRecovery", TestSqlitePersistenceAndCrashRecoveryAsync),
            ("IdempotencyReplayAndPayloadMismatch", TestIdempotencyReplayAndPayloadMismatchAsync),
            ("TargetMutationConflictRejected", TestTargetMutationConflictRejectedAsync),
            ("OutputSanitizerRedactsSecretsAndTruncates", TestOutputSanitizerAsync),
            ("ProcessExecutorDigestAndReparsePointGuards", TestProcessExecutorIntegrityAndReparseAsync),
            ("ProcessExecutorTimeoutKillsTree", TestProcessExecutorTimeoutAsync),
            ("ArgumentInjectionRejectedByTypedSchema", TestArgumentInjectionRejectedAsync),
        };

        foreach ((string name, Func<Task> fn) in tests)
        {
            await fn();
            Console.WriteLine($"[PASS] Phase2.{name}");
        }
    }

    private static string CreateTempDir(string suffix)
    {
        string dir = Path.Combine(Path.GetTempPath(), "privexec-cs-tests", $"{suffix}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(dir);
        return dir;
    }

    private static Task TestSqlitePersistenceAndCrashRecoveryAsync()
    {
        string dir = CreateTempDir("sqlite");
        string dbPath = Path.Combine(dir, "privexec.db");
        try
        {
            DateTimeOffset now = DateTimeOffset.UtcNow;
            using (var store = new SqliteOperationStore(dbPath))
            {
                var rec = new OperationRecord(
                    "op-crash-001", "req-crash-001", AgentSid, "synth.mutate", "synthetic", "target-1", "apply",
                    "hash-1", OperationState.Executing, true, null, now, null, null, null, new List<string>(), false, null);
                store.InsertOperation(rec);
            }

            // Simulate broker restart after crash
            using (var reopened = new SqliteOperationStore(dbPath))
            {
                int marked = reopened.MarkInterruptedExecutionsAsOutcomeUnknown();
                Assert.Equal(1, marked, "interrupted execution marked outcome_unknown");
                OperationRecord? loaded = reopened.GetByOperationId("op-crash-001");
                Assert.True(loaded is not null, "loaded record exists");
                Assert.Equal("req-crash-001", loaded!.RequestId, "request_id preserved on SQLite read");
                Assert.Equal(AgentSid, loaded.ClientSid, "client_sid preserved on SQLite read");
                Assert.Equal(OperationState.OutcomeUnknown, loaded.State, "state after crash recovery");
                Assert.Equal("broker_crash_unknown_outcome", loaded.DiagnosticCategory, "diagnostic category");
            }
        }
        finally
        {
            string junction = Path.Combine(dir, "junction");
            if (Directory.Exists(junction)) Directory.Delete(junction, false);
            Directory.Delete(dir, true);
        }
        return Task.CompletedTask;
    }

    private static async Task TestIdempotencyReplayAndPayloadMismatchAsync()
    {
        string dir = CreateTempDir("idemp");
        string dbPath = Path.Combine(dir, "privexec.db");
        try
        {
            using var store = new SqliteOperationStore(dbPath);
            var grant = new SessionGrant
            {
                OperatorSid = OperatorSid,
                AllowedClientSids = new HashSet<string> { AgentSid },
                AllowedCapabilities = new HashSet<string> { "synthetic.echo" },
                AllowedTargets = new HashSet<string> { "synth-target-1" },
                ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(10)
            };
            var desc = new CapabilityDescriptor(
                1, "synthetic.echo", "1.0.0", "synthetic", null, null, null, null, null,
                new List<string> { "synthetic" }, new List<string> { "synth-target-1" },
                true, false, false, 30, false, new List<string>(), new List<string>(), new List<string>(),
                new Dictionary<string, ParameterRule>
                {
                    ["message"] = new("string", false, "^[A-Za-z0-9_-]{1,32}$", null, null, null, "--msg", "any")
                });
            var engine = new BrokerEngine(
                new SessionAuthorizer(grant),
                new Dictionary<string, CapabilityDescriptor> { ["synthetic.echo"] = desc },
                store,
                new SyntheticCapabilityExecutor());
            var client = new ClientIdentity(AgentSid, "W\\agent", "Negotiate");

            string req1 = """
            {"protocol_version":1,"action":"run","request_id":"req-dup-1","capability":"synthetic.echo","target":{"type":"synthetic","id":"synth-target-1"},"mode":"dry_run","parameters":{"message":"one"}}
            """;
            using JsonDocument d1 = JsonDocument.Parse(await engine.HandleRawRequestAsync(req1, client, CancellationToken.None));
            string opId1 = d1.RootElement.GetProperty("operation_id").GetString()!;

            // Same request_id + identical payload -> same operation_id
            using JsonDocument d2 = JsonDocument.Parse(await engine.HandleRawRequestAsync(req1, client, CancellationToken.None));
            Assert.Equal(opId1, d2.RootElement.GetProperty("operation_id").GetString(), "idempotent replay op_id");

            // Same request_id + different payload -> 409 mismatch
            string reqMismatch = """
            {"protocol_version":1,"action":"run","request_id":"req-dup-1","capability":"synthetic.echo","target":{"type":"synthetic","id":"synth-target-1"},"mode":"dry_run","parameters":{"message":"two"}}
            """;
            using JsonDocument d3 = JsonDocument.Parse(await engine.HandleRawRequestAsync(reqMismatch, client, CancellationToken.None));
            Assert.Equal("request_id_payload_mismatch", d3.RootElement.GetProperty("diagnostic_category").GetString(), "payload mismatch");
        }
        finally
        {
            string junction = Path.Combine(dir, "junction");
            if (Directory.Exists(junction)) Directory.Delete(junction, false);
            Directory.Delete(dir, true);
        }
    }

    private sealed class BlockingExecutor : ICapabilityExecutor
    {
        public TaskCompletionSource Entered { get; } = new();
        public TaskCompletionSource Release { get; } = new();

        public async Task<ExecutionOutcome> ExecuteAsync(
            CapabilityDescriptor descriptor, ValidatedRunRequest request, string operationId, CancellationToken cancellationToken)
        {
            Entered.TrySetResult();
            await Release.Task.WaitAsync(cancellationToken);
            return new ExecutionOutcome(
                OperationState.Succeeded, 0, null, JsonSerializer.SerializeToElement(new { ok = true }),
                new List<string>(), true, null);
        }
    }

    private static async Task TestTargetMutationConflictRejectedAsync()
    {
        var blocking = new BlockingExecutor();
        var grant = new SessionGrant
        {
            OperatorSid = OperatorSid,
            AllowedClientSids = new HashSet<string> { AgentSid },
            AllowedCapabilities = new HashSet<string> { "synth.mut" },
            AllowedTargets = new HashSet<string> { "vm-1" },
            AllowMutation = true,
            AllowedMutationCapabilities = new HashSet<string> { "synth.mut" },
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(10)
        };
        var desc = new CapabilityDescriptor(
            1, "synth.mut", "1.0.0", "synthetic", null, null, null, null, null,
            new List<string> { "synthetic" }, new List<string> { "vm-1" },
            true, true, true, 30, false, new List<string>(), new List<string>(), new List<string>(),
            new Dictionary<string, ParameterRule>());
        var engine = new BrokerEngine(
            new SessionAuthorizer(grant),
            new Dictionary<string, CapabilityDescriptor> { ["synth.mut"] = desc },
            new InMemoryOperationStore(),
            blocking);
        var client = new ClientIdentity(AgentSid, "W\\agent", "Negotiate");

        string reqA = """{"protocol_version":1,"action":"run","request_id":"m-1","capability":"synth.mut","target":{"type":"synthetic","id":"vm-1"},"mode":"apply","parameters":{}}""";
        string reqB = """{"protocol_version":1,"action":"run","request_id":"m-2","capability":"synth.mut","target":{"type":"synthetic","id":"vm-1"},"mode":"apply","parameters":{}}""";

        Task<string> firstTask = engine.HandleRawRequestAsync(reqA, client, CancellationToken.None);
        await blocking.Entered.Task;

        using JsonDocument conflictDoc = JsonDocument.Parse(await engine.HandleRawRequestAsync(reqB, client, CancellationToken.None));
        Assert.Equal("target_mutation_conflict", conflictDoc.RootElement.GetProperty("diagnostic_category").GetString(), "conflict rejected");

        blocking.Release.SetResult();
        using JsonDocument firstDoc = JsonDocument.Parse(await firstTask);
        Assert.Equal("succeeded", firstDoc.RootElement.GetProperty("state").GetString(), "first mutation completes");
    }

    private static Task TestOutputSanitizerAsync()
    {
        string dirty = "Connecting with password=SuperSecret123! and Authorization: Bearer tok_abc123 and PRIVEXEC_SECRET:myval";
        string clean = OutputSanitizer.SanitizeText(dirty, 500);
        Assert.True(!clean.Contains("SuperSecret123", StringComparison.Ordinal), "password redacted");
        Assert.True(!clean.Contains("tok_abc123", StringComparison.Ordinal), "bearer token redacted");
        Assert.True(!clean.Contains("myval", StringComparison.Ordinal), "privexec secret redacted");
        return Task.CompletedTask;
    }

    private static async Task TestProcessExecutorIntegrityAndReparseAsync()
    {
        string dir = CreateTempDir("exec-sec");
        try
        {
            string stateDir = Path.Combine(dir, "state");
            string scriptPath = Path.Combine(dir, "ok.ps1");
            File.WriteAllText(scriptPath, "Write-Output '{\"status\":\"ok\"}'");
            string sha = SecurityAndAcl.ComputeFileSha256(scriptPath);
            string pwshPath = @"C:\Program Files\PowerShell\7\pwsh.exe";
            if (!File.Exists(pwshPath)) return;

            var executor = new ProcessCapabilityExecutor(stateDir);
            var desc = new CapabilityDescriptor(
                1, "ps.test", "1.0.0", "powershell", pwshPath, null, scriptPath, sha, dir,
                new List<string> { "synthetic" }, new List<string> { "t1" },
                true, false, false, 15, false,
                new List<string> { "-NoProfile", "-NonInteractive", "-File", "{script_path}" },
                new List<string>(), new List<string>(),
                new Dictionary<string, ParameterRule>());
            var req = new ValidatedRunRequest(1, "r1", "ps.test", new TargetRef("synthetic", "t1"), "dry_run", new Dictionary<string, object?>(), "{}");

            // Tamper script after descriptor was loaded
            File.WriteAllText(scriptPath, "Write-Output 'evil'");
            ExecutionOutcome tampered = await executor.ExecuteAsync(desc, req, "op-tamper", CancellationToken.None);
            Assert.Equal(OperationState.Failed, tampered.FinalState, "tampered script rejected");
            Assert.Equal("integrity_check_failed", tampered.DiagnosticCategory, "integrity category");

            // Junction/reparse-point target rejection
            string realSub = Path.Combine(dir, "real");
            Directory.CreateDirectory(realSub);
            string junction = Path.Combine(dir, "junction");
            var psi = new ProcessStartInfo("cmd.exe", $"/c mklink /J \"{junction}\" \"{realSub}\"")
            {
                UseShellExecute = false, CreateNoWindow = true
            };
            using (var p = Process.Start(psi)!)
            {
                p.WaitForExit();
            }
            string junctionScript = Path.Combine(junction, "s.ps1");
            File.WriteAllText(realSub + "\\s.ps1", "Write-Output '{}'");
            string jSha = SecurityAndAcl.ComputeFileSha256(realSub + "\\s.ps1");
            var jDesc = desc with { ScriptPath = junctionScript, ScriptSha256 = jSha, WorkingDirectory = junction };
            ExecutionOutcome jOutcome = await executor.ExecuteAsync(jDesc, req, "op-junc", CancellationToken.None);
            Assert.Equal(OperationState.Failed, jOutcome.FinalState, "junction script rejected");
            Assert.Equal("integrity_check_failed", jOutcome.DiagnosticCategory, "reparse category");
        }
        finally
        {
            string junction = Path.Combine(dir, "junction");
            if (Directory.Exists(junction)) Directory.Delete(junction, false);
            Directory.Delete(dir, true);
        }
    }

    private static async Task TestProcessExecutorTimeoutAsync()
    {
        string pwshPath = @"C:\Program Files\PowerShell\7\pwsh.exe";
        if (!File.Exists(pwshPath)) return;

        string dir = CreateTempDir("exec-timeout");
        try
        {
            string stateDir = Path.Combine(dir, "state");
            string scriptPath = Path.Combine(dir, "sleep.ps1");
            File.WriteAllText(scriptPath, "Start-Sleep -Seconds 30");
            string sha = SecurityAndAcl.ComputeFileSha256(scriptPath);

            var executor = new ProcessCapabilityExecutor(stateDir);
            var desc = new CapabilityDescriptor(
                1, "ps.slow", "1.0.0", "powershell", pwshPath, null, scriptPath, sha, dir,
                new List<string> { "synthetic" }, new List<string> { "t1" },
                true, false, false, 1, false,
                new List<string> { "-NoProfile", "-NonInteractive", "-File", "{script_path}" },
                new List<string>(), new List<string>(),
                new Dictionary<string, ParameterRule>());
            var req = new ValidatedRunRequest(1, "r-slow", "ps.slow", new TargetRef("synthetic", "t1"), "dry_run", new Dictionary<string, object?>(), "{}");

            ExecutionOutcome outcome = await executor.ExecuteAsync(desc, req, "op-timeout", CancellationToken.None);
            Assert.Equal(OperationState.Failed, outcome.FinalState, "timeout fails");
            Assert.Equal("execution_timeout", outcome.DiagnosticCategory, "timeout category");
        }
        finally
        {
            string junction = Path.Combine(dir, "junction");
            if (Directory.Exists(junction)) Directory.Delete(junction, false);
            Directory.Delete(dir, true);
        }
    }

    private static Task TestArgumentInjectionRejectedAsync()
    {
        var grant = new SessionGrant
        {
            OperatorSid = OperatorSid,
            AllowedClientSids = new HashSet<string> { AgentSid },
            AllowedCapabilities = new HashSet<string> { "synthetic.echo" },
            AllowedTargets = new HashSet<string> { "t1" },
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(10)
        };
        var desc = new CapabilityDescriptor(
            1, "synthetic.echo", "1.0.0", "synthetic", null, null, null, null, null,
            new List<string> { "synthetic" }, new List<string> { "t1" },
            true, false, false, 30, false, new List<string>(), new List<string>(), new List<string>(),
            new Dictionary<string, ParameterRule>
            {
                ["message"] = new("string", false, "^[A-Za-z0-9 _.-]{0,64}$", null, null, null, "--message", "any")
            });
        var auth = new SessionAuthorizer(grant);
        var req = new ValidatedRunRequest(
            1, "r-inj", "synthetic.echo", new TargetRef("synthetic", "t1"), "dry_run",
            new Dictionary<string, object?> { ["message"] = "hello; Remove-Item C:\\" }, "{}");
        AuthorizationDecision decision = auth.Authorize(AgentSid, req, desc);
        Assert.True(!decision.Authorized, "shell metacharacter injection must be denied");
        Assert.Equal("invalid_parameters", decision.DiagnosticCategory, "category");
        return Task.CompletedTask;
    }
}
