using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace PrivExecBroker;

public sealed class SessionAuthorizer
{
    private readonly SessionGrant _grant;
    private readonly Func<DateTimeOffset> _clock;

    public SessionAuthorizer(SessionGrant grant, Func<DateTimeOffset>? clock = null)
    {
        _grant = grant;
        _clock = clock ?? (() => DateTimeOffset.UtcNow);
    }

    public SessionGrant Grant => _grant;

    public void Revoke()
    {
        _grant.Revoked = true;
    }

    public bool IsOperator(string clientSid)
    {
        return string.Equals(clientSid, _grant.OperatorSid, StringComparison.OrdinalIgnoreCase);
    }

    public bool IsClientAllowed(string clientSid)
    {
        return _grant.AllowedClientSids.Contains(clientSid);
    }

    public AuthorizationDecision Authorize(
        string clientSid,
        ValidatedRunRequest request,
        CapabilityDescriptor? descriptor)
    {
        if (_grant.Revoked)
        {
            return new AuthorizationDecision(false, "session_revoked", "Operator session has been revoked.");
        }

        if (_clock() >= _grant.ExpiresAtUtc)
        {
            return new AuthorizationDecision(false, "session_expired", "Operator session grant has expired.");
        }

        if (!IsClientAllowed(clientSid))
        {
            return new AuthorizationDecision(
                false,
                "unauthorized_identity",
                $"Client Windows SID '{clientSid}' is not authorized for this session.");
        }

        if (descriptor is null)
        {
            return new AuthorizationDecision(
                false,
                "unknown_capability",
                $"Capability '{request.Capability}' is not registered.");
        }

        if (!_grant.AllowedCapabilities.Contains(request.Capability))
        {
            return new AuthorizationDecision(
                false,
                "unauthorized_capability",
                $"Capability '{request.Capability}' is not authorized in the current session grant.");
        }

        if (!descriptor.TargetTypes.Contains(request.Target.Type))
        {
            return new AuthorizationDecision(
                false,
                "invalid_target_type",
                $"Target type '{request.Target.Type}' is not supported by '{descriptor.CapabilityId}'.");
        }

        if (descriptor.AllowedTargets.Count > 0 &&
            !descriptor.AllowedTargets.Any(t => string.Equals(t, request.Target.Id, StringComparison.OrdinalIgnoreCase)))
        {
            return new AuthorizationDecision(
                false,
                "unauthorized_target",
                $"Target '{request.Target.Id}' is not permitted by capability descriptor '{descriptor.CapabilityId}'.");
        }

        if (!_grant.AllowedTargets.Contains(request.Target.Id))
        {
            return new AuthorizationDecision(
                false,
                "unauthorized_target",
                $"Target '{request.Target.Id}' is not authorized in the current session grant.");
        }

        if (request.Mode == "dry_run" && !descriptor.SupportsDryRun)
        {
            return new AuthorizationDecision(false, "unsupported_mode", $"Capability '{descriptor.CapabilityId}' does not support dry_run.");
        }

        if (request.Mode == "apply")
        {
            if (!descriptor.SupportsApply)
            {
                return new AuthorizationDecision(false, "unsupported_mode", $"Capability '{descriptor.CapabilityId}' does not support apply.");
            }
            if (descriptor.IsMutating)
            {
                if (!_grant.AllowMutation || !_grant.AllowedMutationCapabilities.Contains(request.Capability))
                {
                    return new AuthorizationDecision(
                        false,
                        "mutation_not_authorized",
                        $"Mutating execution of '{request.Capability}' requires an active operator mutation grant.");
                }
            }
        }

        string? paramError = ValidateParameters(request.Parameters, descriptor.ParameterSchema, request.Mode);
        if (paramError is not null)
        {
            return new AuthorizationDecision(false, "invalid_parameters", paramError);
        }

        return new AuthorizationDecision(true, null, null);
    }

    public static string? ValidateParameters(
        IReadOnlyDictionary<string, object?> parameters,
        IReadOnlyDictionary<string, ParameterRule> schema,
        string mode)
    {
        foreach (string key in parameters.Keys)
        {
            if (!schema.ContainsKey(key))
            {
                return $"Unknown parameter '{key}' is not permitted by capability schema.";
            }
        }

        foreach ((string name, ParameterRule rule) in schema)
        {
            bool provided = parameters.TryGetValue(name, out object? value) && value is not null;
            if (!provided)
            {
                if (rule.Required)
                {
                    return $"Missing required parameter '{name}'.";
                }
                continue;
            }

            if (rule.ModeScope == "apply" && mode != "apply")
            {
                return $"Parameter '{name}' is only permitted in 'apply' mode.";
            }
            if (rule.ModeScope == "dry_run" && mode != "dry_run")
            {
                return $"Parameter '{name}' is only permitted in 'dry_run' mode.";
            }

            string? typeError = ValidateTypedValue(name, value!, rule);
            if (typeError is not null)
            {
                return typeError;
            }
        }

        return null;
    }

    private static string? ValidateTypedValue(string name, object value, ParameterRule rule)
    {
        switch (rule.Type)
        {
            case "string":
            case "guid":
            case "enum":
            {
                if (value is not string s)
                {
                    return $"Parameter '{name}' must be a string.";
                }
                if (rule.Type == "guid" && !Guid.TryParse(s, out _))
                {
                    return $"Parameter '{name}' must be a valid GUID.";
                }
                if (rule.AllowedValues is not null && !rule.AllowedValues.Any(v => string.Equals(v, s, StringComparison.Ordinal)))
                {
                    return $"Parameter '{name}' value '{s}' is not in allowed values.";
                }
                if (!string.IsNullOrEmpty(rule.Pattern) && !Regex.IsMatch(s, rule.Pattern, RegexOptions.CultureInvariant))
                {
                    return $"Parameter '{name}' value does not match allowed pattern.";
                }
                return null;
            }
            case "int":
            {
                long num;
                if (value is long l) num = l;
                else if (value is int i) num = i;
                else return $"Parameter '{name}' must be an integer.";

                if (rule.Min.HasValue && num < rule.Min.Value)
                {
                    return $"Parameter '{name}' must be >= {rule.Min.Value}.";
                }
                if (rule.Max.HasValue && num > rule.Max.Value)
                {
                    return $"Parameter '{name}' must be <= {rule.Max.Value}.";
                }
                return null;
            }
            case "bool":
            {
                if (value is not bool)
                {
                    return $"Parameter '{name}' must be a boolean.";
                }
                return null;
            }
            default:
                return string.Create(CultureInfo.InvariantCulture, $"Unsupported parameter schema type '{rule.Type}'.");
        }
    }
}
