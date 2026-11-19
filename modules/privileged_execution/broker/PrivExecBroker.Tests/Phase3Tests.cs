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
}
