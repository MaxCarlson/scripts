using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace PrivExecBroker;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        string pipeName = ProtocolConstants.DefaultPipeName;
        string descriptorsDir = Path.Combine(AppContext.BaseDirectory, "descriptors");
        string stateDir = Path.Combine(AppContext.BaseDirectory, "state");
        string? grantFile = null;
        int ttlSeconds = 1800;
        bool allowSameUser = false;

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--pipe":
                    pipeName = RequireArg(args, ref i, "--pipe");
                    break;
                case "--descriptors-dir":
                    descriptorsDir = RequireArg(args, ref i, "--descriptors-dir");
                    break;
                case "--state-dir":
                    stateDir = RequireArg(args, ref i, "--state-dir");
                    break;
                case "--grant-file":
                    grantFile = RequireArg(args, ref i, "--grant-file");
                    break;
                case "--ttl-seconds":
                    ttlSeconds = int.Parse(RequireArg(args, ref i, "--ttl-seconds"));
                    break;
                case "--allow-same-user":
                    allowSameUser = true;
                    break;
                case "--help":
                case "-h":
                    Console.WriteLine("PrivExecBroker --pipe <name> --descriptors-dir <dir> --state-dir <dir> [--grant-file <json>] [--ttl-seconds <n>] [--allow-same-user]");
                    return 0;
                default:
                    Console.Error.WriteLine($"Unknown argument: {args[i]}");
                    return 2;
            }
        }

        string operatorSid = SecurityAndAcl.GetCurrentProcessUserSid();
        IReadOnlyDictionary<string, CapabilityDescriptor> descriptors = DescriptorLoader.LoadFromDirectory(descriptorsDir);
        SessionGrant grant = BuildSessionGrant(operatorSid, grantFile, ttlSeconds, allowSameUser);

        Directory.CreateDirectory(stateDir);
        SecurityAndAcl.AssertNoReparsePoints(stateDir, "State directory");
        string dbPath = Path.Combine(stateDir, "privexec.db");

        using var cts = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            grant.Revoked = true;
            cts.Cancel();
        };

        var authorizer = new SessionAuthorizer(grant);
        using var store = new SqliteOperationStore(dbPath);
        int recoveredUnknown = store.MarkInterruptedExecutionsAsOutcomeUnknown();
        if (recoveredUnknown > 0)
        {
            Console.WriteLine($"PRIVEXEC_CRASH_RECOVERY marked_outcome_unknown={recoveredUnknown}");
        }
        var executor = new ProcessCapabilityExecutor(stateDir);
        var engine = new BrokerEngine(authorizer, descriptors, store, executor, null, () => cts.Cancel());
        var pipeSecurity = SecurityAndAcl.BuildPipeSecurity(operatorSid, grant.AllowedClientSids);
        var server = new PipeBrokerServer(pipeName, pipeSecurity, engine);

        await server.RunAsync(cts.Token, () =>
        {
            Console.WriteLine($"PRIVEXEC_BROKER_READY pipe={pipeName} session={grant.SessionId} descriptors={descriptors.Count} expires={grant.ExpiresAtUtc:O}");
        });
        Console.WriteLine($"PRIVEXEC_BROKER_STOPPED session={grant.SessionId}");
        return 0;
    }

    private static SessionGrant BuildSessionGrant(string operatorSid, string? grantFile, int ttlSeconds, bool allowSameUser)
    {
        var allowedClients = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var allowedCaps = new HashSet<string>(StringComparer.Ordinal);
        var allowedTargets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var allowedMutationCaps = new HashSet<string>(StringComparer.Ordinal);
        bool allowMutation = false;

        if (!string.IsNullOrWhiteSpace(grantFile))
        {
            SecurityAndAcl.AssertNoReparsePoints(grantFile, "Grant file");
            using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(grantFile));
            JsonElement root = doc.RootElement;
            if (root.TryGetProperty("allowed_client_sids", out var sids))
            {
                foreach (var s in sids.EnumerateArray())
                {
                    string? v = s.GetString();
                    if (!string.IsNullOrWhiteSpace(v)) allowedClients.Add(v);
                }
            }
            if (root.TryGetProperty("allowed_capabilities", out var caps))
            {
                foreach (var c in caps.EnumerateArray())
                {
                    string? v = c.GetString();
                    if (!string.IsNullOrWhiteSpace(v)) allowedCaps.Add(v);
                }
            }
            if (root.TryGetProperty("allowed_targets", out var targets))
            {
                foreach (var t in targets.EnumerateArray())
                {
                    string? v = t.GetString();
                    if (!string.IsNullOrWhiteSpace(v)) allowedTargets.Add(v);
                }
            }
            if (root.TryGetProperty("allow_mutation", out var am))
            {
                allowMutation = am.GetBoolean();
            }
            if (root.TryGetProperty("allowed_mutation_capabilities", out var mcaps))
            {
                foreach (var mc in mcaps.EnumerateArray())
                {
                    string? v = mc.GetString();
                    if (!string.IsNullOrWhiteSpace(v)) allowedMutationCaps.Add(v);
                }
            }
            if (root.TryGetProperty("ttl_seconds", out var ttlEl) && ttlEl.TryGetInt32(out int fileTtl))
            {
                ttlSeconds = fileTtl;
            }
        }

        if (allowSameUser)
        {
            allowedClients.Add(operatorSid);
        }

        return new SessionGrant
        {
            OperatorSid = operatorSid,
            AllowedClientSids = allowedClients,
            AllowedCapabilities = allowedCaps,
            AllowedTargets = allowedTargets,
            AllowMutation = allowMutation,
            AllowedMutationCapabilities = allowedMutationCaps,
            ExpiresAtUtc = DateTimeOffset.UtcNow.AddSeconds(Math.Clamp(ttlSeconds, 1, 86400))
        };
    }

    private static string RequireArg(string[] args, ref int idx, string flag)
    {
        if (idx + 1 >= args.Length)
        {
            throw new ArgumentException($"Missing value for {flag}");
        }
        return args[++idx];
    }
}
