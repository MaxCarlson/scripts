using System;
using System.Collections.Generic;
using System.IO;
using System.Security;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using PrivExecBroker;

namespace PrivExecBroker.Tests;

internal static class Phase3Tests
{
    private const string OperatorSid = "S-1-5-21-1000-1000-1000-1001";
    private const string AgentSid = "S-1-5-21-1000-1000-1000-1002";
    private const string H4VmId = "d8483f98-8884-4758-abd1-cd6107c83c03";

    public static async Task RunAllAsync()
    {
        var tests = new (string Name, Func<Task> Fn)[]
        {
            ("OperatorMemoryCredentialProviderStdinHandoff", TestCredentialProviderAsync),
            ("MissingGuestCredentialDeniedCleanly", TestMissingGuestCredentialAsync),
            ("H4DescriptorsEnforceAllowedModesAndTargets", TestH4DescriptorValidationAsync),
            ("AcceptanceDeniedUnderSetupOnlyGrant", TestAcceptanceDeniedUnderSetupOnlyGrantAsync),
            ("AtomicTryInsertHandlesConcurrentDuplicate", TestAtomicTryInsertHandlesConcurrentDuplicateAsync),
            ("PipeServerHandlesBadClientAndEarlyEofCleanly", TestPipeServerHandlesBadClientAndEarlyEofAsync),
            ("ProcessExecutorPinsChildTempInsideStateDir", TestProcessExecutorPinsChildTempAsync),
            ("AccountDescriptionAndOwnershipMatching", TestAccountDescriptionAndOwnershipMatchingAsync),
            ("PipeServerDoesNotLeakImpersonation", TestPipeServerDoesNotLeakImpersonationAsync),
            ("SqliteEngineOwnershipAndCrossAgentIdempotency", TestSqliteEngineOwnershipAndCrossAgentIdempotencyAsync),
        };

        foreach ((string name, Func<Task> fn) in tests)
        {
            await fn();
            Console.WriteLine($"[PASS] Phase3.{name}");
        }
    }

    private static Task TestCredentialProviderAsync()
    {
        using var sec = new SecureString();
        foreach (char c in "GuestPass!23") sec.AppendChar(c);
        using var provider = new OperatorMemoryCredentialProvider(@"DESKTOP-1ITSJV0\mcarls", sec);
        Assert.True(provider.HasGuestCredential, "provider must hold credential");

        using var ms = new MemoryStream();
        using (var sw = new StreamWriter(ms, leaveOpen: true))
        {
            provider.WriteCredentialJsonToStdin(sw);
        }
        ms.Position = 0;
        using var sr = new StreamReader(ms);
        string line = sr.ReadLine()!;
        using JsonDocument doc = JsonDocument.Parse(line);
        Assert.Equal(@"DESKTOP-1ITSJV0\mcarls", doc.RootElement.GetProperty("username").GetString(), "username");
        Assert.Equal("GuestPass!23", doc.RootElement.GetProperty("password").GetString(), "password");

        provider.Dispose();
        Assert.True(!provider.HasGuestCredential, "disposed provider must report false");
        return Task.CompletedTask;
    }

    private static async Task TestMissingGuestCredentialAsync()
    {
        string dir = Path.Combine(Path.GetTempPath(), "privexec-p3-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            string pwshPath = @"C:\Program Files\PowerShell\7\pwsh.exe";
            string scriptPath = Path.Combine(dir, "dummy.ps1");
            File.WriteAllText(scriptPath, "Write-Output '{}'");
            string sha = SecurityAndAcl.ComputeFileSha256(scriptPath);

            var desc = new CapabilityDescriptor(
                1, "h4.preflight", "1.0.0", "powershell", pwshPath, null, scriptPath, sha, dir,
                new List<string> { "hyperv_vm" }, new List<string> { H4VmId },
                true, false, false, 60, true,
                new List<string> { "-NoProfile", "-File", "{script_path}" },
                new List<string>(), new List<string>(),
                new Dictionary<string, ParameterRule>());

            var exec = new ProcessCapabilityExecutor(dir, new NullCredentialProvider());
            var req = new ValidatedRunRequest(1, "r-cred", "h4.preflight", new TargetRef("hyperv_vm", H4VmId), "dry_run", new Dictionary<string, object?>(), "{}");
            ExecutionOutcome outcome = await exec.ExecuteAsync(desc, req, "op-missing-cred", CancellationToken.None);
            Assert.Equal(OperationState.Failed, outcome.FinalState, "missing credential fails");
            Assert.Equal("missing_guest_credential", outcome.DiagnosticCategory, "missing credential category");
        }
        finally
        {
            Directory.Delete(dir, true);
        }
    }

    private static Task TestH4DescriptorValidationAsync()
    {
        string repoDescDir = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "descriptors"));
        if (!Directory.Exists(repoDescDir))
        {
            return Task.CompletedTask;
        }

        IReadOnlyDictionary<string, CapabilityDescriptor> descriptors = DescriptorLoader.LoadFromDirectory(repoDescDir);
        Assert.True(descriptors.ContainsKey("h4.preflight"), "h4.preflight descriptor loaded");
        Assert.True(descriptors.ContainsKey("h4.qualify"), "h4.qualify descriptor loaded");
        Assert.True(descriptors.ContainsKey("h4.recover"), "h4.recover descriptor loaded");

        var grant = new SessionGrant
        {
            OperatorSid = OperatorSid,
            AllowedClientSids = new HashSet<string> { AgentSid },
            AllowedCapabilities = new HashSet<string> { "h4.preflight", "h4.qualify", "h4.recover" },
            AllowedTargets = new HashSet<string> { H4VmId },
            AllowMutation = true,
            AllowedMutationCapabilities = new HashSet<string> { "h4.qualify" }, // h4.recover NOT granted mutation!
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(10)
        };
        var auth = new SessionAuthorizer(grant);

        // h4.qualify rejects 'All' stage
        var badStage = new ValidatedRunRequest(
            1, "r1", "h4.qualify", new TargetRef("hyperv_vm", H4VmId), "apply",
            new Dictionary<string, object?> { ["stage"] = "All" }, "{}");
        Assert.True(!auth.Authorize(AgentSid, badStage, descriptors["h4.qualify"]).Authorized, "All stage must be rejected");

        // h4.qualify allows Setup apply when granted
        var okSetup = new ValidatedRunRequest(
            1, "r2", "h4.qualify", new TargetRef("hyperv_vm", H4VmId), "apply",
            new Dictionary<string, object?> { ["stage"] = "Setup" }, "{}");
        Assert.True(auth.Authorize(AgentSid, okSetup, descriptors["h4.qualify"]).Authorized, "Setup apply must be authorized");

        // h4.recover apply rejected without separate h4.recover mutation grant
        var deniedRecover = new ValidatedRunRequest(
            1, "r3", "h4.recover", new TargetRef("hyperv_vm", H4VmId), "apply",
            new Dictionary<string, object?>(), "{}");
        AuthorizationDecision recDecision = auth.Authorize(AgentSid, deniedRecover, descriptors["h4.recover"]);
        Assert.True(!recDecision.Authorized, "h4.recover apply requires separate mutation grant");
        Assert.Equal("mutation_not_authorized", recDecision.DiagnosticCategory, "recover denial category");

        return Task.CompletedTask;
    }

    private static Task TestAcceptanceDeniedUnderSetupOnlyGrantAsync()
    {
        string repoDescDir = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "descriptors"));
        if (!Directory.Exists(repoDescDir)) return Task.CompletedTask;
        IReadOnlyDictionary<string, CapabilityDescriptor> descriptors = DescriptorLoader.LoadFromDirectory(repoDescDir);

        var setupOnlyGrant = new SessionGrant
        {
            OperatorSid = OperatorSid,
            AllowedClientSids = new HashSet<string> { AgentSid },
            AllowedCapabilities = new HashSet<string> { "h4.qualify" },
            AllowedTargets = new HashSet<string> { H4VmId },
            AllowMutation = true,
            AllowedMutationCapabilities = new HashSet<string> { "h4.qualify" },
            AllowedH4Stages = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "Setup" },
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(10)
        };
        var auth = new SessionAuthorizer(setupOnlyGrant);

        var acceptanceReq = new ValidatedRunRequest(
            1, "r-acc", "h4.qualify", new TargetRef("hyperv_vm", H4VmId), "apply",
            new Dictionary<string, object?> { ["stage"] = "Acceptance", ["authorize_guest_mutation"] = true }, "{}");
        AuthorizationDecision decision = auth.Authorize(AgentSid, acceptanceReq, descriptors["h4.qualify"]);
        Assert.True(!decision.Authorized, "Acceptance must be denied under Setup-only grant");
        Assert.Equal("stage_not_authorized", decision.DiagnosticCategory, "stage denial category");
        return Task.CompletedTask;
    }

    private static Task TestAtomicTryInsertHandlesConcurrentDuplicateAsync()
    {
        string dir = Path.Combine(Path.GetTempPath(), "privexec-p3-atomic-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            using var store = new SqliteOperationStore(Path.Combine(dir, "privexec.db"));
            DateTimeOffset now = DateTimeOffset.UtcNow;
            var rec1 = new OperationRecord(
                "op-a1", "req-same", AgentSid, "synthetic.echo", "synthetic", "t1", "dry_run",
                "hash-A", OperationState.Succeeded, true, 0, now, now, null, null, new List<string>(), true, null);
            var recDup = rec1 with { OperationId = "op-a2" };
            var recMismatch = rec1 with { OperationId = "op-a3", CanonicalPayloadHash = "hash-B" };

            Assert.True(store.TryInsertOperation(rec1, out _), "first insert succeeds");
            Assert.True(!store.TryInsertOperation(recDup, out IdempotencyLookup c1), "duplicate insert returns false");
            Assert.Equal(IdempotencyLookupKind.ReplayExisting, c1.Kind, "duplicate kind");
            Assert.True(!store.TryInsertOperation(recMismatch, out IdempotencyLookup c2), "mismatch insert returns false");
            Assert.Equal(IdempotencyLookupKind.PayloadMismatch, c2.Kind, "mismatch kind");
        }
        finally
        {
            Directory.Delete(dir, true);
        }
        return Task.CompletedTask;
    }

    private static async Task TestPipeServerHandlesBadClientAndEarlyEofAsync()
    {
        string pipeName = "privexec-cs-eof-" + Guid.NewGuid().ToString("N")[..8];
        string mySid = SecurityAndAcl.GetCurrentProcessUserSid();
        var grant = new SessionGrant
        {
            OperatorSid = mySid,
            AllowedClientSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { mySid },
            AllowedCapabilities = new HashSet<string> { "synthetic.echo" },
            AllowedTargets = new HashSet<string> { "synth-target-1" },
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(5)
        };
        var desc = new CapabilityDescriptor(
            1, "synthetic.echo", "1.0.0", "synthetic", null, null, null, null, null,
            new List<string> { "synthetic" }, new List<string> { "synth-target-1" },
            true, false, false, 15, false, new List<string>(), new List<string>(), new List<string>(),
            new Dictionary<string, ParameterRule>());
        var engine = new BrokerEngine(
            new SessionAuthorizer(grant),
            new Dictionary<string, CapabilityDescriptor> { ["synthetic.echo"] = desc },
            new InMemoryOperationStore(),
            new SyntheticCapabilityExecutor());
        var server = new PipeBrokerServer(pipeName, SecurityAndAcl.BuildPipeSecurity(mySid, new[] { mySid }), engine);

        using var cts = new CancellationTokenSource();
        var listeningTcs = new TaskCompletionSource();
        Task serverTask = server.RunAsync(cts.Token, () => listeningTcs.TrySetResult());
        await listeningTcs.Task;

        try
        {
            // 1. Client disconnects immediately without sending frame
            using (var c1 = new System.IO.Pipes.NamedPipeClientStream(".", pipeName, System.IO.Pipes.PipeDirection.InOut,
                System.IO.Pipes.PipeOptions.None, System.Security.Principal.TokenImpersonationLevel.Impersonation))
            {
                await c1.ConnectAsync(3000);
            }

            // 2. Subsequent valid client still works cleanly
            using var c2 = new System.IO.Pipes.NamedPipeClientStream(".", pipeName, System.IO.Pipes.PipeDirection.InOut,
                System.IO.Pipes.PipeOptions.None, System.Security.Principal.TokenImpersonationLevel.Impersonation);
            await c2.ConnectAsync(3000);
            byte[] reqBytes = System.Text.Encoding.UTF8.GetBytes("""{"protocol_version":1,"action":"status"}""");
            byte[] lenBytes = BitConverter.GetBytes((uint)reqBytes.Length);
            await c2.WriteAsync(lenBytes);
            await c2.WriteAsync(reqBytes);
            await c2.FlushAsync();

            byte[] respLenBuf = new byte[4];
            int r = await c2.ReadAsync(respLenBuf);
            Assert.Equal(4, r, "valid status header after early EOF");
            uint rLen = BitConverter.ToUInt32(respLenBuf, 0);
            byte[] respBuf = new byte[rLen];
            int bodyRead = await c2.ReadAsync(respBuf);
            Assert.Equal((int)rLen, bodyRead, "valid status body");
            using JsonDocument doc = JsonDocument.Parse(respBuf);
            Assert.True(doc.RootElement.GetProperty("ok").GetBoolean(), "broker remains healthy");
        }
        finally
        {
            cts.Cancel();
            await serverTask;
        }
    }

    private static async Task TestProcessExecutorPinsChildTempAsync()
    {
        string pwshPath = @"C:\Program Files\PowerShell\7\pwsh.exe";
        if (!File.Exists(pwshPath)) return;

        string dir = Path.Combine(Path.GetTempPath(), "privexec-p3-temp-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            string stateDir = Path.Combine(dir, "state");
            string scriptPath = Path.Combine(dir, "print_temp.ps1");
            File.WriteAllText(scriptPath, "[ordered]@{ temp = $env:TEMP; tmp = $env:TMP } | ConvertTo-Json -Compress");
            string sha = SecurityAndAcl.ComputeFileSha256(scriptPath);

            var desc = new CapabilityDescriptor(
                1, "ps.temp", "1.0.0", "powershell", pwshPath, null, scriptPath, sha, dir,
                new List<string> { "synthetic" }, new List<string> { "t1" },
                true, false, false, 15, false,
                new List<string> { "-NoProfile", "-NonInteractive", "-File", "{script_path}" },
                new List<string>(), new List<string>(), new Dictionary<string, ParameterRule>());

            var exec = new ProcessCapabilityExecutor(stateDir);
            var req = new ValidatedRunRequest(1, "r-tmp", "ps.temp", new TargetRef("synthetic", "t1"), "dry_run", new Dictionary<string, object?>(), "{}");
            ExecutionOutcome outcome = await exec.ExecuteAsync(desc, req, "op-tmp-1", CancellationToken.None);
            Assert.Equal(OperationState.Succeeded, outcome.FinalState, "temp check succeeds");
            string expectedTmp = Path.Combine(stateDir, "tmp");
            Assert.Equal(expectedTmp, outcome.ResultJson.GetProperty("temp").GetString(), "child TEMP pinned inside state\\tmp");
        }
        finally
        {
            Directory.Delete(dir, true);
        }
    }

    private static Task TestAccountDescriptionAndOwnershipMatchingAsync()
    {
        string runId = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")[..8];
        Assert.Equal(24, runId.Length, "runId length is 24");

        string agentTag = $"PE2:agent:{runId}";
        string unauthTag = $"PE2:unauth:{runId}";
        Assert.True(agentTag.Length <= 48, $"agent tag length {agentTag.Length} <= 48");
        Assert.True(unauthTag.Length <= 48, $"unauth tag length {unauthTag.Length} <= 48");

        string agentUser = "PrivExecAg_" + Guid.NewGuid().ToString("N")[..6];
        string unauthUser = "PrivExecUn_" + Guid.NewGuid().ToString("N")[..6];
        Assert.True(agentUser.Length <= 20, $"agent username length {agentUser.Length} <= 20");
        Assert.True(unauthUser.Length <= 20, $"unauth username length {unauthUser.Length} <= 20");

        // Old failing tag format would have failed 48-char check
        string oldFailingTag = $"PrivExec Gate 2 temporary test account ({runId})";
        Assert.True(oldFailingTag.Length > 48, $"old tag length {oldFailingTag.Length} > 48");

        static bool MatchesOwnership(string desc, string targetRunId)
        {
            if (string.IsNullOrEmpty(desc) || desc.Length > 48) return false;
            return desc == $"PE2:agent:{targetRunId}" ||
                   desc == $"PE2:unauth:{targetRunId}" ||
                   (desc.StartsWith("PE2:") && desc.EndsWith($":{targetRunId}"));
        }

        Assert.True(MatchesOwnership(agentTag, runId), "current agent matches");
        Assert.True(MatchesOwnership(unauthTag, runId), "current unauth matches");
        Assert.True(!MatchesOwnership($"PE2:agent:other-{runId[6..]}", runId), "other run agent rejected");
        Assert.True(!MatchesOwnership("Built-in account for guest access", runId), "guest description rejected");
        Assert.True(!MatchesOwnership(oldFailingTag, runId), "old tag rejected");
        Assert.True(!MatchesOwnership("", runId), "empty description rejected");

        return Task.CompletedTask;
    }

    private sealed class ImpersonationCheckingExecutor : ICapabilityExecutor
    {
        public string? ThreadIdentityBeforeAwait { get; private set; }
        public string? ThreadIdentityAfterAwait { get; private set; }
        public int ThreadIdBeforeAwait { get; private set; }

        public async Task<ExecutionOutcome> ExecuteAsync(
            CapabilityDescriptor descriptor,
            ValidatedRunRequest request,
            string operationId,
            CancellationToken cancellationToken)
        {
            ThreadIdBeforeAwait = Environment.CurrentManagedThreadId;
            using (var id1 = System.Security.Principal.WindowsIdentity.GetCurrent(true))
            {
                ThreadIdentityBeforeAwait = id1 is null ? null : $"{id1.Name}({id1.ImpersonationLevel})[T{Environment.CurrentManagedThreadId}]";
            }
            await Task.Yield();
            using (var id2 = System.Security.Principal.WindowsIdentity.GetCurrent(true))
            {
                ThreadIdentityAfterAwait = id2 is null ? null : $"{id2.Name}({id2.ImpersonationLevel})[T{Environment.CurrentManagedThreadId}]";
            }
            return new ExecutionOutcome(
                OperationState.Succeeded,
                0,
                null,
                JsonSerializer.SerializeToElement(new { ok = true }),
                new List<string>(),
                true,
                null);
        }
    }

    private static async Task TestPipeServerDoesNotLeakImpersonationAsync()
    {
        string mySid = SecurityAndAcl.GetCurrentProcessUserSid();
        string pipeName = "privexec-imp-" + Guid.NewGuid().ToString("N")[..8];
        var grant = new SessionGrant
        {
            OperatorSid = mySid,
            AllowedClientSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { mySid },
            AllowedCapabilities = new HashSet<string> { "synthetic.check" },
            AllowedTargets = new HashSet<string> { "t1" },
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(5)
        };
        var desc = new CapabilityDescriptor(
            1, "synthetic.check", "1.0.0", "synthetic", null, null, null, null, null,
            new List<string> { "synthetic" }, new List<string> { "t1" },
            true, false, false, 15, false, new List<string>(), new List<string>(), new List<string>(),
            new Dictionary<string, ParameterRule>());
        var exec = new ImpersonationCheckingExecutor();
        var engine = new BrokerEngine(
            new SessionAuthorizer(grant),
            new Dictionary<string, CapabilityDescriptor> { ["synthetic.check"] = desc },
            new InMemoryOperationStore(),
            exec);
        var server = new PipeBrokerServer(pipeName, SecurityAndAcl.BuildPipeSecurity(mySid, new[] { mySid }), engine);

        using var cts = new CancellationTokenSource();
        var listeningTcs = new TaskCompletionSource();
        Task serverTask = server.RunAsync(cts.Token, () => listeningTcs.TrySetResult());
        await listeningTcs.Task;

        try
        {
            using var client = new System.IO.Pipes.NamedPipeClientStream(
                ".", pipeName, System.IO.Pipes.PipeDirection.InOut,
                System.IO.Pipes.PipeOptions.None, System.Security.Principal.TokenImpersonationLevel.Impersonation);
            await client.ConnectAsync(3000);
            byte[] reqBytes = System.Text.Encoding.UTF8.GetBytes(
                """{"protocol_version":1,"action":"run","request_id":"req-imp-1","capability":"synthetic.check","target":{"type":"synthetic","id":"t1"},"mode":"dry_run","parameters":{}}""");
            byte[] lenBytes = BitConverter.GetBytes((uint)reqBytes.Length);
            await client.WriteAsync(lenBytes);
            await client.WriteAsync(reqBytes);
            await client.FlushAsync();

            byte[] respLenBuf = new byte[4];
            int r = await client.ReadAsync(respLenBuf);
            Assert.Equal(4, r, "response header length");
            uint rLen = BitConverter.ToUInt32(respLenBuf, 0);
            byte[] respBuf = new byte[rLen];
            int bodyRead = await client.ReadAsync(respBuf);
            Assert.Equal((int)rLen, bodyRead, "response body length");

            Assert.Equal(null, exec.ThreadIdentityBeforeAwait, "thread must not impersonate before await");
            Assert.Equal(null, exec.ThreadIdentityAfterAwait, $"thread must not impersonate after await (before was T{exec.ThreadIdBeforeAwait})");
        }
        finally
        {
            cts.Cancel();
            await serverTask;
        }
    }

    private static async Task TestSqliteEngineOwnershipAndCrossAgentIdempotencyAsync()
    {
        const string AgentSid2 = "S-1-5-21-1000-1000-1000-1003";
        const string UnauthSid = "S-1-5-21-1000-1000-1000-9999";

        string pwshPath = @"C:\Program Files\PowerShell\7\pwsh.exe";
        if (!File.Exists(pwshPath)) return;

        string dir = Path.Combine(Path.GetTempPath(), "privexec-p3-own-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            string stateDir = Path.Combine(dir, "state");
            Directory.CreateDirectory(stateDir);
            string scriptPath = Path.Combine(dir, "echo_op.ps1");
            File.WriteAllText(scriptPath, "param([string]$OperationId) [ordered]@{ op = $OperationId } | ConvertTo-Json -Compress");
            string sha = SecurityAndAcl.ComputeFileSha256(scriptPath);

            var desc = new CapabilityDescriptor(
                1, "synthetic.mutate", "1.0.0", "powershell", pwshPath, null, scriptPath, sha, dir,
                new List<string> { "synthetic" }, new List<string> { "synth-target-1" },
                true, true, true, 15, false,
                new List<string> { "-NoProfile", "-NonInteractive", "-File", "{script_path}", "-OperationId", "{operation_id}" },
                new List<string>(), new List<string>(), new Dictionary<string, ParameterRule>());

            var grant = new SessionGrant
            {
                OperatorSid = OperatorSid,
                AllowedClientSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { AgentSid, AgentSid2 },
                AllowedCapabilities = new HashSet<string> { "synthetic.mutate" },
                AllowedTargets = new HashSet<string> { "synth-target-1" },
                AllowMutation = true,
                AllowedMutationCapabilities = new HashSet<string> { "synthetic.mutate" },
                ExpiresAtUtc = DateTimeOffset.UtcNow.AddMinutes(5)
            };

            using var store = new SqliteOperationStore(Path.Combine(stateDir, "privexec.db"));
            var executor = new ProcessCapabilityExecutor(stateDir);
            var engine = new BrokerEngine(
                new SessionAuthorizer(grant),
                new Dictionary<string, CapabilityDescriptor> { ["synthetic.mutate"] = desc },
                store,
                executor);

            var agent1 = new ClientIdentity(AgentSid, @"TEST\Agent1", "Negotiate");
            var agent2 = new ClientIdentity(AgentSid2, @"TEST\Agent2", "Negotiate");
            var unauth = new ClientIdentity(UnauthSid, @"TEST\Unauth", "Negotiate");

            // 1. Agent 1 executes an apply operation with request_id "shared-req-1"
            string runReq = """{"protocol_version":1,"action":"run","request_id":"shared-req-1","capability":"synthetic.mutate","target":{"type":"synthetic","id":"synth-target-1"},"mode":"apply","parameters":{}}""";
            string runResp1 = await engine.HandleRawRequestAsync(runReq, agent1, CancellationToken.None);
            using JsonDocument runDoc1 = JsonDocument.Parse(runResp1);
            Assert.True(runDoc1.RootElement.GetProperty("ok").GetBoolean(), "agent1 run ok");
            Assert.Equal("succeeded", runDoc1.RootElement.GetProperty("state").GetString(), "agent1 run succeeded");
            Assert.Equal("shared-req-1", runDoc1.RootElement.GetProperty("request_id").GetString(), "agent1 request_id preserved");
            string opId1 = runDoc1.RootElement.GetProperty("operation_id").GetString()!;
            Assert.Equal(1, runDoc1.RootElement.GetProperty("evidence").GetArrayLength(), "privileged evidence written");

            // 2. Agent 1 retrieves its own operation result from SQLite
            string lookupReq1 = $$"""{"protocol_version":1,"action":"result","operation_id":"{{opId1}}"}""";
            string lookupResp1 = await engine.HandleRawRequestAsync(lookupReq1, agent1, CancellationToken.None);
            using JsonDocument lookupDoc1 = JsonDocument.Parse(lookupResp1);
            Assert.True(lookupDoc1.RootElement.GetProperty("ok").GetBoolean(), "agent1 result lookup ok");
            Assert.Equal(opId1, lookupDoc1.RootElement.GetProperty("operation_id").GetString(), "agent1 lookup opId matches");
            Assert.Equal("shared-req-1", lookupDoc1.RootElement.GetProperty("request_id").GetString(), "agent1 lookup requestId matches");
            Assert.Equal("succeeded", lookupDoc1.RootElement.GetProperty("state").GetString(), "agent1 lookup state matches");

            // 3. Agent 2 is denied retrieving Agent 1's operation result
            string lookupRespCross = await engine.HandleRawRequestAsync(lookupReq1, agent2, CancellationToken.None);
            using JsonDocument lookupDocCross = JsonDocument.Parse(lookupRespCross);
            Assert.True(!lookupDocCross.RootElement.GetProperty("ok").GetBoolean(), "agent2 cross-lookup denied");
            Assert.Equal(403, lookupDocCross.RootElement.GetProperty("exit_code").GetInt32(), "agent2 cross-lookup 403");
            Assert.Equal("unauthorized_identity", lookupDocCross.RootElement.GetProperty("diagnostic_category").GetString(), "agent2 cross-lookup category");

            // 4. Agent 1 replaying "shared-req-1" gets its own operation replayed
            string replayResp1 = await engine.HandleRawRequestAsync(runReq, agent1, CancellationToken.None);
            using JsonDocument replayDoc1 = JsonDocument.Parse(replayResp1);
            Assert.Equal(opId1, replayDoc1.RootElement.GetProperty("operation_id").GetString(), "agent1 idempotency replay returns opId1");
            Assert.Equal("shared-req-1", replayDoc1.RootElement.GetProperty("request_id").GetString(), "agent1 idempotency replay preserves request_id");

            // 5. Agent 2 sending the SAME request_id "shared-req-1" gets a brand-new operation owned by Agent 2 (no cross-identity leak)
            string runResp2 = await engine.HandleRawRequestAsync(runReq, agent2, CancellationToken.None);
            using JsonDocument runDoc2 = JsonDocument.Parse(runResp2);
            Assert.True(runDoc2.RootElement.GetProperty("ok").GetBoolean(), "agent2 run with same request_id ok");
            string opId2 = runDoc2.RootElement.GetProperty("operation_id").GetString()!;
            Assert.True(!string.Equals(opId1, opId2, StringComparison.Ordinal), "agent2 gets distinct operation_id");

            string lookupReq2 = $$"""{"protocol_version":1,"action":"result","operation_id":"{{opId2}}"}""";
            string lookupResp2 = await engine.HandleRawRequestAsync(lookupReq2, agent2, CancellationToken.None);
            using JsonDocument lookupDoc2 = JsonDocument.Parse(lookupResp2);
            Assert.True(lookupDoc2.RootElement.GetProperty("ok").GetBoolean(), "agent2 retrieves own operation");

            // 6. Unauthorized client is denied capability execution
            string unauthRunReq = """{"protocol_version":1,"action":"run","request_id":"unauth-req-1","capability":"synthetic.mutate","target":{"type":"synthetic","id":"synth-target-1"},"mode":"dry_run","parameters":{}}""";
            string unauthResp = await engine.HandleRawRequestAsync(unauthRunReq, unauth, CancellationToken.None);
            using JsonDocument unauthDoc = JsonDocument.Parse(unauthResp);
            Assert.True(!unauthDoc.RootElement.GetProperty("ok").GetBoolean(), "unauth client denied");
            Assert.Equal("unauthorized_identity", unauthDoc.RootElement.GetProperty("diagnostic_category").GetString(), "unauth client category");
        }
        finally
        {
            Directory.Delete(dir, true);
        }
    }
}
