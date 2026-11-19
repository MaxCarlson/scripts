using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PrivExecBroker;

public static class DescriptorLoader
{
    private static readonly Regex Sha256Regex = new("^[0-9a-fA-F]{64}$", RegexOptions.Compiled);

    public static IReadOnlyDictionary<string, CapabilityDescriptor> LoadFromDirectory(string descriptorsDir)
    {
        SecurityAndAcl.AssertNoReparsePoints(descriptorsDir, "Descriptors directory");
        if (!Directory.Exists(descriptorsDir))
        {
            throw new DirectoryNotFoundException($"Descriptors directory not found: '{descriptorsDir}'.");
        }

        var result = new Dictionary<string, CapabilityDescriptor>(StringComparer.Ordinal);
        string[] files = Directory.GetFiles(descriptorsDir, "*.json", SearchOption.TopDirectoryOnly);
        Array.Sort(files, StringComparer.OrdinalIgnoreCase);

        foreach (string file in files)
        {
            SecurityAndAcl.AssertNoReparsePoints(file, $"Descriptor file '{Path.GetFileName(file)}'");
            CapabilityDescriptor desc = LoadSingle(file);
            if (!result.TryAdd(desc.CapabilityId, desc))
            {
                throw new InvalidOperationException($"Duplicate capability descriptor ID '{desc.CapabilityId}'.");
            }
        }

        return result;
    }

    public static CapabilityDescriptor LoadSingle(string filePath)
    {
        string raw = File.ReadAllText(filePath);
        using JsonDocument doc = JsonDocument.Parse(raw);
        JsonElement root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
        {
            throw new InvalidOperationException($"Descriptor '{filePath}' must be a JSON object.");
        }

        int schemaVersion = root.GetProperty("schema_version").GetInt32();
        if (schemaVersion != 1)
        {
            throw new InvalidOperationException($"Unsupported descriptor schema_version {schemaVersion} in '{filePath}'.");
        }

        string capabilityId = GetRequiredString(root, "capability_id", filePath);
        string version = GetRequiredString(root, "version", filePath);
        string runnerType = GetRequiredString(root, "runner_type", filePath);
        if (runnerType is not ("synthetic" or "powershell" or "python"))
        {
            throw new InvalidOperationException($"Unsupported runner_type '{runnerType}' in '{filePath}'.");
        }

        string? executablePath = GetOptionalString(root, "executable_path");
        string? executableSha256 = GetOptionalString(root, "executable_sha256");
        string? scriptPath = GetOptionalString(root, "script_path");
        string? scriptSha256 = GetOptionalString(root, "script_sha256");
        string? workingDir = GetOptionalString(root, "working_directory");

        if (runnerType is "powershell" or "python")
        {
            if (string.IsNullOrWhiteSpace(executablePath) || string.IsNullOrWhiteSpace(scriptPath))
            {
                throw new InvalidOperationException($"Descriptor '{capabilityId}' requires executable_path and script_path.");
            }
            if (string.IsNullOrWhiteSpace(scriptSha256) || !Sha256Regex.IsMatch(scriptSha256))
            {
                throw new InvalidOperationException($"Descriptor '{capabilityId}' requires a valid 64-hex script_sha256.");
            }
            if (!string.IsNullOrWhiteSpace(executableSha256) && !Sha256Regex.IsMatch(executableSha256))
            {
                throw new InvalidOperationException($"Descriptor '{capabilityId}' executable_sha256 must be 64 hex chars.");
            }
        }

        var targetTypes = ReadStringList(root, "target_types");
        var allowedTargets = ReadOptionalStringList(root, "allowed_targets");
        bool supportsDryRun = root.TryGetProperty("supports_dry_run", out var sdr) && sdr.GetBoolean();
        bool supportsApply = root.TryGetProperty("supports_apply", out var sa) && sa.GetBoolean();
        bool isMutating = root.TryGetProperty("is_mutating", out var im) && im.GetBoolean();
        int maxDuration = root.TryGetProperty("max_duration_seconds", out var md) ? md.GetInt32() : 60;
        if (maxDuration <= 0 || maxDuration > 3600)
        {
            throw new InvalidOperationException($"Descriptor '{capabilityId}' max_duration_seconds must be in 1..3600.");
        }
        bool requiresGuestCred = root.TryGetProperty("requires_guest_credential", out var rgc) && rgc.GetBoolean();
        var fixedArgs = ReadOptionalStringList(root, "fixed_args");

        var paramSchema = new Dictionary<string, ParameterRule>(StringComparer.Ordinal);
        if (root.TryGetProperty("parameter_schema", out JsonElement psEl) && psEl.ValueKind == JsonValueKind.Object)
        {
            foreach (JsonProperty prop in psEl.EnumerateObject())
            {
                JsonElement ruleEl = prop.Value;
                string pType = GetRequiredString(ruleEl, "type", filePath);
                bool required = ruleEl.TryGetProperty("required", out var reqEl) && reqEl.GetBoolean();
                string? pattern = GetOptionalString(ruleEl, "pattern");
                List<string>? allowedValues = ruleEl.TryGetProperty("allowed_values", out var avEl) && avEl.ValueKind == JsonValueKind.Array
                    ? ReadStringArray(avEl)
                    : null;
                long? min = ruleEl.TryGetProperty("min", out var minEl) && minEl.ValueKind == JsonValueKind.Number ? minEl.GetInt64() : null;
                long? max = ruleEl.TryGetProperty("max", out var maxEl) && maxEl.ValueKind == JsonValueKind.Number ? maxEl.GetInt64() : null;
                string? cliFlag = GetOptionalString(ruleEl, "cli_flag");
                string modeScope = GetOptionalString(ruleEl, "mode_scope") ?? "any";

                paramSchema[prop.Name] = new ParameterRule(pType, required, pattern, allowedValues, min, max, cliFlag, modeScope);
            }
        }

        return new CapabilityDescriptor(
            schemaVersion,
            capabilityId,
            version,
            runnerType,
            executablePath,
            executableSha256,
            scriptPath,
            scriptSha256,
            workingDir,
            targetTypes,
            allowedTargets,
            supportsDryRun,
            supportsApply,
            isMutating,
            maxDuration,
            requiresGuestCred,
            fixedArgs,
            paramSchema
        );
    }

    private static string GetRequiredString(JsonElement el, string key, string filePath)
    {
        if (!el.TryGetProperty(key, out JsonElement val) || val.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(val.GetString()))
        {
            throw new InvalidOperationException($"Descriptor '{filePath}' missing required string '{key}'.");
        }
        return val.GetString()!;
    }

    private static string? GetOptionalString(JsonElement el, string key)
    {
        if (!el.TryGetProperty(key, out JsonElement val) || val.ValueKind == JsonValueKind.Null)
        {
            return null;
        }
        return val.GetString();
    }

    private static List<string> ReadStringList(JsonElement el, string key)
    {
        if (!el.TryGetProperty(key, out JsonElement arr) || arr.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException($"Missing required array '{key}'.");
        }
        return ReadStringArray(arr);
    }

    private static List<string> ReadOptionalStringList(JsonElement el, string key)
    {
        if (!el.TryGetProperty(key, out JsonElement arr) || arr.ValueKind != JsonValueKind.Array)
        {
            return new List<string>();
        }
        return ReadStringArray(arr);
    }

    private static List<string> ReadStringArray(JsonElement arr)
    {
        var list = new List<string>();
        foreach (JsonElement item in arr.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String || item.GetString() is null)
            {
                throw new InvalidOperationException("Array elements must be strings.");
            }
            list.Add(item.GetString()!);
        }
        return list;
    }
}
