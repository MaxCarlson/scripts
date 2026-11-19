using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace PrivExecBroker;

public sealed class ProtocolValidationException : Exception
{
    public string Category { get; }

    public ProtocolValidationException(string category, string message) : base(message)
    {
        Category = category;
    }
}

public static class ProtocolValidator
{
    private static readonly Regex RequestIdRegex = new("^[A-Za-z0-9._:-]{1,128}$", RegexOptions.Compiled);
    private static readonly Regex CapabilityRegex = new("^[a-z0-9._-]{1,64}$", RegexOptions.Compiled);
    private static readonly Regex TargetTypeRegex = new("^[a-z0-9_-]{1,32}$", RegexOptions.Compiled);
    private static readonly Regex OperationIdRegex = new("^[A-Za-z0-9._:-]{1,128}$", RegexOptions.Compiled);

    private static readonly HashSet<string> AllowedStatusKeys = new(StringComparer.Ordinal)
    {
        "protocol_version", "action"
    };

    private static readonly HashSet<string> AllowedShutdownKeys = new(StringComparer.Ordinal)
    {
        "protocol_version", "action"
    };

    private static readonly HashSet<string> AllowedResultKeys = new(StringComparer.Ordinal)
    {
        "protocol_version", "action", "operation_id"
    };

    private static readonly HashSet<string> AllowedRunKeys = new(StringComparer.Ordinal)
    {
        "protocol_version", "action", "request_id", "capability", "target", "mode", "parameters"
    };

    private static readonly HashSet<string> AllowedTargetKeys = new(StringComparer.Ordinal)
    {
        "type", "id"
    };

    private static readonly HashSet<string> ForbiddenKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        "authorized", "approval", "approved", "sid", "user", "username", "role",
        "executable", "executable_path", "script", "script_path", "script_block",
        "command", "credential", "password", "secret"
    };

    public static ParsedClientMessage ParseAndValidate(string jsonText)
    {
        if (string.IsNullOrWhiteSpace(jsonText))
        {
            throw new ProtocolValidationException("malformed_request", "Empty request body.");
        }

        JsonDocument doc;
        try
        {
            doc = JsonDocument.Parse(jsonText, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 16
            });
        }
        catch (JsonException ex)
        {
            throw new ProtocolValidationException("malformed_request", $"Invalid JSON request: {ex.Message}");
        }

        using (doc)
        {
            JsonElement root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new ProtocolValidationException("malformed_request", "Request root must be a JSON object.");
            }

            if (!root.TryGetProperty("protocol_version", out JsonElement verEl) ||
                verEl.ValueKind != JsonValueKind.Number ||
                !verEl.TryGetInt32(out int ver))
            {
                throw new ProtocolValidationException("protocol_mismatch", "Missing or non-integer protocol_version.");
            }

            if (ver != ProtocolConstants.ProtocolVersion)
            {
                throw new ProtocolValidationException(
                    "protocol_mismatch",
                    $"Unsupported protocol_version {ver}; expected {ProtocolConstants.ProtocolVersion}.");
            }

            if (!root.TryGetProperty("action", out JsonElement actionEl) || actionEl.ValueKind != JsonValueKind.String)
            {
                throw new ProtocolValidationException("malformed_request", "Missing or invalid 'action'.");
            }

            string action = actionEl.GetString() ?? string.Empty;
            return action switch
            {
                "status" => ValidateStatus(root),
                "shutdown" => ValidateShutdown(root),
                "result" => ValidateResult(root),
                "run" => ValidateRun(root),
                _ => throw new ProtocolValidationException("malformed_request", $"Unsupported action '{action}'.")
            };
        }
    }

    private static ParsedClientMessage ValidateStatus(JsonElement root)
    {
        AssertExactAllowedKeys(root, AllowedStatusKeys, "status request");
        return new ParsedClientMessage("status", null, null);
    }

    private static ParsedClientMessage ValidateShutdown(JsonElement root)
    {
        AssertExactAllowedKeys(root, AllowedShutdownKeys, "shutdown request");
        return new ParsedClientMessage("shutdown", null, null);
    }

    private static ParsedClientMessage ValidateResult(JsonElement root)
    {
        AssertExactAllowedKeys(root, AllowedResultKeys, "result request");
        if (!root.TryGetProperty("operation_id", out JsonElement opEl) || opEl.ValueKind != JsonValueKind.String)
        {
            throw new ProtocolValidationException("malformed_request", "Missing or invalid 'operation_id'.");
        }
        string opId = opEl.GetString() ?? string.Empty;
        if (!OperationIdRegex.IsMatch(opId))
        {
            throw new ProtocolValidationException("malformed_request", "Invalid 'operation_id' format.");
        }
        return new ParsedClientMessage("result", null, opId);
    }

    private static ParsedClientMessage ValidateRun(JsonElement root)
    {
        AssertExactAllowedKeys(root, AllowedRunKeys, "run request");

        string requestId = GetRequiredString(root, "request_id");
        if (!RequestIdRegex.IsMatch(requestId))
        {
            throw new ProtocolValidationException("malformed_request", "Invalid 'request_id' format.");
        }

        string capability = GetRequiredString(root, "capability");
        if (!CapabilityRegex.IsMatch(capability))
        {
            throw new ProtocolValidationException("malformed_request", "Invalid 'capability' format.");
        }

        if (!root.TryGetProperty("target", out JsonElement targetEl) || targetEl.ValueKind != JsonValueKind.Object)
        {
            throw new ProtocolValidationException("malformed_request", "Missing or invalid 'target' object.");
        }
        AssertExactAllowedKeys(targetEl, AllowedTargetKeys, "target");

        string targetType = GetRequiredString(targetEl, "type");
        if (!TargetTypeRegex.IsMatch(targetType))
        {
            throw new ProtocolValidationException("malformed_request", "Invalid 'target.type' format.");
        }
        string targetId = GetRequiredString(targetEl, "id");
        if (targetId.Length > 256 || HasWhitespace(targetId))
        {
            throw new ProtocolValidationException("malformed_request", "Invalid 'target.id'.");
        }

        string mode = "dry_run";
        if (root.TryGetProperty("mode", out JsonElement modeEl))
        {
            if (modeEl.ValueKind != JsonValueKind.String)
            {
                throw new ProtocolValidationException("malformed_request", "'mode' must be a string.");
            }
            mode = modeEl.GetString() ?? string.Empty;
        }
        if (mode != "dry_run" && mode != "apply")
        {
            throw new ProtocolValidationException("malformed_request", $"Invalid mode '{mode}'; expected 'dry_run' or 'apply'.");
        }

        var parameters = new Dictionary<string, object?>(StringComparer.Ordinal);
        if (root.TryGetProperty("parameters", out JsonElement paramsEl))
        {
            if (paramsEl.ValueKind != JsonValueKind.Object)
            {
                throw new ProtocolValidationException("malformed_request", "'parameters' must be a JSON object.");
            }
            AssertNoForbiddenKeysRecursive(paramsEl, "parameters");
            foreach (JsonProperty prop in paramsEl.EnumerateObject())
            {
                parameters[prop.Name] = ConvertPrimitiveOrReject(prop.Value, prop.Name);
            }
        }

        string canonical = BuildCanonicalPayload(capability, targetType, targetId, mode, parameters);
        var runReq = new ValidatedRunRequest(
            ProtocolConstants.ProtocolVersion,
            requestId,
            capability,
            new TargetRef(targetType, targetId),
            mode,
            parameters,
            canonical
        );
        return new ParsedClientMessage("run", runReq, null);
    }

    public static string BuildCanonicalPayload(
        string capability,
        string targetType,
        string targetId,
        string mode,
        IReadOnlyDictionary<string, object?> parameters)
    {
        var sortedParams = new SortedDictionary<string, object?>(StringComparer.Ordinal);
        foreach (var kv in parameters)
        {
            sortedParams[kv.Key] = kv.Value;
        }
        var canonicalObj = new
        {
            capability,
            mode,
            parameters = sortedParams,
            target = new { id = targetId, type = targetType }
        };
        return JsonSerializer.Serialize(canonicalObj);
    }

    public static string Sha256Hex(string text)
    {
        byte[] hash = SHA256.HashData(Encoding.UTF8.GetBytes(text));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static void AssertExactAllowedKeys(JsonElement obj, HashSet<string> allowed, string context)
    {
        foreach (JsonProperty prop in obj.EnumerateObject())
        {
            if (ForbiddenKeys.Contains(prop.Name))
            {
                throw new ProtocolValidationException(
                    "forbidden_property",
                    $"Forbidden property '{prop.Name}' is not permitted in {context}.");
            }
            if (!allowed.Contains(prop.Name))
            {
                throw new ProtocolValidationException(
                    "malformed_request",
                    $"Unexpected property '{prop.Name}' in {context}.");
            }
        }
    }

    private static void AssertNoForbiddenKeysRecursive(JsonElement el, string context)
    {
        if (el.ValueKind == JsonValueKind.Object)
        {
            foreach (JsonProperty prop in el.EnumerateObject())
            {
                if (ForbiddenKeys.Contains(prop.Name))
                {
                    throw new ProtocolValidationException(
                        "forbidden_property",
                        $"Forbidden property '{prop.Name}' is not permitted in {context}.");
                }
                AssertNoForbiddenKeysRecursive(prop.Value, $"{context}.{prop.Name}");
            }
        }
        else if (el.ValueKind == JsonValueKind.Array)
        {
            int idx = 0;
            foreach (JsonElement item in el.EnumerateArray())
            {
                AssertNoForbiddenKeysRecursive(item, $"{context}[{idx++}]");
            }
        }
    }

    private static string GetRequiredString(JsonElement obj, string propName)
    {
        if (!obj.TryGetProperty(propName, out JsonElement el) || el.ValueKind != JsonValueKind.String)
        {
            throw new ProtocolValidationException("malformed_request", $"Missing or non-string property '{propName}'.");
        }
        string val = el.GetString() ?? string.Empty;
        if (string.IsNullOrEmpty(val))
        {
            throw new ProtocolValidationException("malformed_request", $"Property '{propName}' cannot be empty.");
        }
        return val;
    }

    private static object? ConvertPrimitiveOrReject(JsonElement el, string name) => el.ValueKind switch
    {
        JsonValueKind.String => el.GetString(),
        JsonValueKind.Number => el.TryGetInt64(out long l) ? l : el.GetDouble(),
        JsonValueKind.True => true,
        JsonValueKind.False => false,
        JsonValueKind.Null => null,
        _ => throw new ProtocolValidationException(
            "malformed_request",
            $"Parameter '{name}' must be a scalar JSON value (nested objects/arrays are rejected).")
    };

    private static bool HasWhitespace(string value)
    {
        foreach (char c in value)
        {
            if (char.IsWhiteSpace(c)) return true;
        }
        return false;
    }
}
