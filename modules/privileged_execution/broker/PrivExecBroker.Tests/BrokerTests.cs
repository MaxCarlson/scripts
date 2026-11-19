using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using PrivExecBroker;

namespace PrivExecBroker.Tests;

internal static class Assert
{
    public static void True(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Assertion failed: {message}");
    }

    public static void Equal<T>(T expected, T actual, string message)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new InvalidOperationException($"Assertion failed ({message}): expected '{expected}', got '{actual}'.");
        }
    }
}

public static class Program
{
    private const string OperatorSid = "S-1-5-21-1000-1000-1000-1001";
    private const string AgentSid = "S-1-5-21-1000-1000-1000-1002";
    private const string WrongSid = "S-1-5-21-1000-1000-1000-9999";

    public static async Task<int> Main()
    {
        var tests = new (string Name, Func<Task> Fn)[]
        {
            ("AuthorizedSyntheticRunAndResultLookup", TestAuthorizedSyntheticRunAndResultLookupAsync),
            ("WrongIdentityRejected", TestWrongIdentityRejectedAsync),
            ("UnapprovedTargetRejected", TestUnapprovedTargetRejectedAsync),
            ("ExpiredGrantRejected", TestExpiredGrantRejectedAsync),
            ("RevokedGrantRejected", TestRevokedGrantRejectedAsync),
            ("UnknownCapabilityRejected", TestUnknownCapabilityRejectedAsync),
            ("MalformedAndProtocolMismatchRejected", TestMalformedAndProtocolMismatchRejectedAsync),
            ("ClientForgeryRejected", TestClientForgeryRejectedAsync),
            ("ShutdownRequiresOperatorIdentity", TestShutdownRequiresOperatorIdentityAsync),
            ("PipeSecurityDeniesNetworkAndGrantsClientReadWrite", TestPipeSecurityAsync),
        };

        int passed = 0;
        foreach ((string name, Func<Task> fn) in tests)
        {
            await fn();
            Console.WriteLine($"[PASS] {name}");
            passed++;
        }

        Console.WriteLine($"All {passed}/{tests.Length} PrivExecBroker Phase 1 C# tests passed.");
        return 0;
    }

    private static (BrokerEngine Engine, SessionAuthorizer Auth, DateTimeOffset Now, Action<DateTimeOffset> SetNow, bool ShutdownCalled)
        CreateHarness(bool expired = false)
    {
        DateTimeOffset now = new(2026, 11, 19, 12, 0, 0, TimeSpan.Zero);
        var grant = new SessionGrant
        {
            OperatorSid = OperatorSid,
            AllowedClientSids = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { AgentSid },
            AllowedCapabilities = new HashSet<string>(StringComparer.Ordinal) { "synthetic.echo" },
            AllowedTargets = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "synth-target-1" },
            AllowMutation = false,
            ExpiresAtUtc = expired ? now.AddSeconds(-1) : now.AddMinutes(10)
        };

        var descriptor = new CapabilityDescriptor(
            1,
            "synthetic.echo",
            "1.0.0",
            "synthetic",
            null, null, null, null, null,
            new List<string> { "synthetic" },
            new List<string> { "synth-target-1", "synth-target-2" },
            true, false, false, 30, false,
            new List<string>(),
            new Dictionary<string, ParameterRule>
            {
                ["message"] = new("string", false, "^[A-Za-z0-9 _.-]{0,128}$", null, null, null, "--message", "any")
            });

        var descriptors = new Dictionary<string, CapabilityDescriptor> { ["synthetic.echo"] = descriptor };
        var auth = new SessionAuthorizer(grant, () => now);
        bool shutdown = false;
        var engine = new BrokerEngine(
            auth,
            descriptors,
            new InMemoryOperationStore(),
            new SyntheticCapabilityExecutor(),
            () => now,
            () => shutdown = true);

        return (engine, auth, now, t => now = t, shutdown);
    }

    private static async Task TestAuthorizedSyntheticRunAndResultLookupAsync()
    {
        var (engine, _, _, _, _) = CreateHarness();
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        string req = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-001",
          "capability": "synthetic.echo",
          "target": { "type": "synthetic", "id": "synth-target-1" },
          "mode": "dry_run",
          "parameters": { "message": "hello world" }
        }
        """;

        string rawResp = await engine.HandleRawRequestAsync(req, client, CancellationToken.None);
        using JsonDocument doc = JsonDocument.Parse(rawResp);
        JsonElement r = doc.RootElement;
        Assert.True(r.GetProperty("ok").GetBoolean(), "ok must be true");
        Assert.Equal("succeeded", r.GetProperty("state").GetString(), "state");
        Assert.True(r.GetProperty("authorized").GetBoolean(), "authorized");
        Assert.Equal("hello world", r.GetProperty("result").GetProperty("echo").GetString(), "echo");
        string opId = r.GetProperty("operation_id").GetString()!;

        string resReq = $$"""{ "protocol_version": 1, "action": "result", "operation_id": "{{opId}}" }""";
        string rawLookup = await engine.HandleRawRequestAsync(resReq, client, CancellationToken.None);
        using JsonDocument lookupDoc = JsonDocument.Parse(rawLookup);
        Assert.Equal(opId, lookupDoc.RootElement.GetProperty("operation_id").GetString(), "lookup opId");
        Assert.Equal("succeeded", lookupDoc.RootElement.GetProperty("state").GetString(), "lookup state");
    }

    private static async Task TestWrongIdentityRejectedAsync()
    {
        var (engine, _, _, _, _) = CreateHarness();
        var rogue = new ClientIdentity(WrongSid, "WORKSTATION\\rogue", "Negotiate");
        string req = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-wrong-id",
          "capability": "synthetic.echo",
          "target": { "type": "synthetic", "id": "synth-target-1" },
          "mode": "dry_run",
          "parameters": {}
        }
        """;

        using JsonDocument doc = JsonDocument.Parse(await engine.HandleRawRequestAsync(req, rogue, CancellationToken.None));
        Assert.Equal("denied", doc.RootElement.GetProperty("state").GetString(), "wrong SID state");
        Assert.Equal("unauthorized_identity", doc.RootElement.GetProperty("diagnostic_category").GetString(), "category");
    }

    private static async Task TestUnapprovedTargetRejectedAsync()
    {
        var (engine, _, _, _, _) = CreateHarness();
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        string req = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-bad-target",
          "capability": "synthetic.echo",
          "target": { "type": "synthetic", "id": "synth-target-2" },
          "mode": "dry_run",
          "parameters": {}
        }
        """;

        using JsonDocument doc = JsonDocument.Parse(await engine.HandleRawRequestAsync(req, client, CancellationToken.None));
        Assert.Equal("denied", doc.RootElement.GetProperty("state").GetString(), "bad target state");
        Assert.Equal("unauthorized_target", doc.RootElement.GetProperty("diagnostic_category").GetString(), "category");
    }

    private static async Task TestExpiredGrantRejectedAsync()
    {
        var (engine, _, _, _, _) = CreateHarness(expired: true);
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        string req = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-expired",
          "capability": "synthetic.echo",
          "target": { "type": "synthetic", "id": "synth-target-1" },
          "mode": "dry_run",
          "parameters": {}
        }
        """;

        using JsonDocument doc = JsonDocument.Parse(await engine.HandleRawRequestAsync(req, client, CancellationToken.None));
        Assert.Equal("denied", doc.RootElement.GetProperty("state").GetString(), "expired state");
        Assert.Equal("session_expired", doc.RootElement.GetProperty("diagnostic_category").GetString(), "category");
    }

    private static async Task TestRevokedGrantRejectedAsync()
    {
        var (engine, auth, _, _, _) = CreateHarness();
        auth.Revoke();
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        string req = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-revoked",
          "capability": "synthetic.echo",
          "target": { "type": "synthetic", "id": "synth-target-1" },
          "mode": "dry_run",
          "parameters": {}
        }
        """;

        using JsonDocument doc = JsonDocument.Parse(await engine.HandleRawRequestAsync(req, client, CancellationToken.None));
        Assert.Equal("denied", doc.RootElement.GetProperty("state").GetString(), "revoked state");
        Assert.Equal("session_revoked", doc.RootElement.GetProperty("diagnostic_category").GetString(), "category");
    }

    private static async Task TestUnknownCapabilityRejectedAsync()
    {
        var (engine, _, _, _, _) = CreateHarness();
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        string req = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-unknown-cap",
          "capability": "powershell.arbitrary",
          "target": { "type": "synthetic", "id": "synth-target-1" },
          "mode": "dry_run",
          "parameters": {}
        }
        """;

        using JsonDocument doc = JsonDocument.Parse(await engine.HandleRawRequestAsync(req, client, CancellationToken.None));
        Assert.Equal("denied", doc.RootElement.GetProperty("state").GetString(), "unknown cap state");
        Assert.Equal("unknown_capability", doc.RootElement.GetProperty("diagnostic_category").GetString(), "category");
    }

    private static async Task TestMalformedAndProtocolMismatchRejectedAsync()
    {
        var (engine, _, _, _, _) = CreateHarness();
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");

        using JsonDocument badJson = JsonDocument.Parse(await engine.HandleRawRequestAsync("{not-json", client, CancellationToken.None));
        Assert.Equal("malformed_request", badJson.RootElement.GetProperty("diagnostic_category").GetString(), "bad json");

        using JsonDocument badVer = JsonDocument.Parse(await engine.HandleRawRequestAsync("""{"protocol_version":99,"action":"status"}""", client, CancellationToken.None));
        Assert.Equal("protocol_mismatch", badVer.RootElement.GetProperty("diagnostic_category").GetString(), "bad protocol");
    }

    private static async Task TestClientForgeryRejectedAsync()
    {
        var (engine, _, _, _, _) = CreateHarness();
        var client = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        string forged = """
        {
          "protocol_version": 1,
          "action": "run",
          "request_id": "req-forged",
          "capability": "synthetic.echo",
          "target": { "type": "synthetic", "id": "synth-target-1" },
          "mode": "dry_run",
          "authorized": true,
          "parameters": {}
        }
        """;

        using JsonDocument doc = JsonDocument.Parse(await engine.HandleRawRequestAsync(forged, client, CancellationToken.None));
        Assert.Equal("denied", doc.RootElement.GetProperty("state").GetString(), "forged state");
        Assert.Equal("forbidden_property", doc.RootElement.GetProperty("diagnostic_category").GetString(), "category");
    }

    private static async Task TestShutdownRequiresOperatorIdentityAsync()
    {
        var (engine, auth, _, _, _) = CreateHarness();
        var agent = new ClientIdentity(AgentSid, "WORKSTATION\\agent", "Negotiate");
        var op = new ClientIdentity(OperatorSid, "WORKSTATION\\operator", "Negotiate");
        string stopReq = """{ "protocol_version": 1, "action": "shutdown" }""";

        using JsonDocument denied = JsonDocument.Parse(await engine.HandleRawRequestAsync(stopReq, agent, CancellationToken.None));
        Assert.Equal("operator_only_action", denied.RootElement.GetProperty("diagnostic_category").GetString(), "agent denied shutdown");
        Assert.True(!auth.Grant.Revoked, "grant must remain active");

        using JsonDocument allowed = JsonDocument.Parse(await engine.HandleRawRequestAsync(stopReq, op, CancellationToken.None));
        Assert.True(allowed.RootElement.GetProperty("ok").GetBoolean(), "operator shutdown ok");
        Assert.True(auth.Grant.Revoked, "grant revoked on operator shutdown");
    }

    private static Task TestPipeSecurityAsync()
    {
        string mySid = SecurityAndAcl.GetCurrentProcessUserSid();
        PipeSecurity ps = SecurityAndAcl.BuildPipeSecurity(mySid, new[] { AgentSid });
        var rules = ps.GetAccessRules(true, false, typeof(SecurityIdentifier)).Cast<PipeAccessRule>().ToList();
        bool hasNetworkDeny = rules.Any(r =>
            r.AccessControlType == AccessControlType.Deny &&
            r.IdentityReference.Value == "S-1-5-2");
        bool hasAnonymousDeny = rules.Any(r =>
            r.AccessControlType == AccessControlType.Deny &&
            r.IdentityReference.Value == "S-1-5-7");
        bool hasAgentReadWrite = rules.Any(r =>
            r.AccessControlType == AccessControlType.Allow &&
            r.IdentityReference.Value == AgentSid &&
            (r.PipeAccessRights & PipeAccessRights.ReadWrite) == PipeAccessRights.ReadWrite &&
            (r.PipeAccessRights & PipeAccessRights.CreateNewInstance) == 0 &&
            (r.PipeAccessRights & PipeAccessRights.ChangePermissions) == 0 &&
            (r.PipeAccessRights & PipeAccessRights.TakeOwnership) == 0);

        Assert.True(hasNetworkDeny, "PipeSecurity must deny NetworkSid");
        Assert.True(hasAnonymousDeny, "PipeSecurity must deny AnonymousSid");
        Assert.True(hasAgentReadWrite, "PipeSecurity must grant ReadWrite only to allowed client SID");
        return Task.CompletedTask;
    }
}
