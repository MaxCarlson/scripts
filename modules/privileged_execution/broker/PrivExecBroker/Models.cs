using System;
using System.Collections.Generic;
using System.Text.Json;

namespace PrivExecBroker;

public static class ProtocolConstants
{
    public const int ProtocolVersion = 1;
    public const int MaxFrameBytes = 4 * 1024 * 1024;
    public const string DefaultPipeName = "privexec-broker-v1";
}

public enum OperationState
{
    Requested,
    Validated,
    Denied,
    Approved,
    Executing,
    Succeeded,
    Failed,
    OutcomeUnknown
}

public static class OperationStateNames
{
    public static string ToWire(OperationState state) => state switch
    {
        OperationState.Requested => "requested",
        OperationState.Validated => "validated",
        OperationState.Denied => "denied",
        OperationState.Approved => "approved",
        OperationState.Executing => "executing",
        OperationState.Succeeded => "succeeded",
        OperationState.Failed => "failed",
        OperationState.OutcomeUnknown => "outcome_unknown",
        _ => "outcome_unknown"
    };

    public static OperationState FromWire(string value) => value switch
    {
        "requested" => OperationState.Requested,
        "validated" => OperationState.Validated,
        "denied" => OperationState.Denied,
        "approved" => OperationState.Approved,
        "executing" => OperationState.Executing,
        "succeeded" => OperationState.Succeeded,
        "failed" => OperationState.Failed,
        "outcome_unknown" => OperationState.OutcomeUnknown,
        _ => OperationState.OutcomeUnknown
    };
}

public sealed record TargetRef(string Type, string Id);

public sealed record ValidatedRunRequest(
    int ProtocolVersion,
    string RequestId,
    string Capability,
    TargetRef Target,
    string Mode,
    Dictionary<string, object?> Parameters,
    string CanonicalPayloadJson
);

public sealed record ParsedClientMessage(
    string Action,
    ValidatedRunRequest? RunRequest,
    string? OperationId
);

public sealed record ParameterRule(
    string Type,
    bool Required,
    string? Pattern,
    List<string>? AllowedValues,
    long? Min,
    long? Max,
    string? CliFlag,
    string ModeScope
);

public sealed record CapabilityDescriptor(
    int SchemaVersion,
    string CapabilityId,
    string Version,
    string RunnerType,
    string? ExecutablePath,
    string? ExecutableSha256,
    string? ScriptPath,
    string? ScriptSha256,
    string? WorkingDirectory,
    List<string> TargetTypes,
    List<string> AllowedTargets,
    bool SupportsDryRun,
    bool SupportsApply,
    bool IsMutating,
    int MaxDurationSeconds,
    bool RequiresGuestCredential,
    List<string> FixedArgs,
    List<string> DryRunArgs,
    List<string> ApplyArgs,
    Dictionary<string, ParameterRule> ParameterSchema
);

public sealed class SessionGrant
{
    public string SessionId { get; init; } = Guid.NewGuid().ToString("N");
    public DateTimeOffset CreatedAtUtc { get; init; } = DateTimeOffset.UtcNow;
    public DateTimeOffset ExpiresAtUtc { get; init; }
    public string OperatorSid { get; init; } = string.Empty;
    public HashSet<string> AllowedClientSids { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> AllowedCapabilities { get; init; } = new(StringComparer.Ordinal);
    public HashSet<string> AllowedTargets { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public bool AllowMutation { get; init; }
    public HashSet<string> AllowedMutationCapabilities { get; init; } = new(StringComparer.Ordinal);
    public HashSet<string> AllowedH4Stages { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public bool Revoked { get; set; }
}

public sealed record AuthorizationDecision(
    bool Authorized,
    string? DiagnosticCategory,
    string? Reason
);

public sealed record OperationRecord(
    string OperationId,
    string RequestId,
    string ClientSid,
    string Capability,
    string TargetType,
    string TargetId,
    string Mode,
    string CanonicalPayloadHash,
    OperationState State,
    bool Authorized,
    int? ExitCode,
    DateTimeOffset StartedAtUtc,
    DateTimeOffset? FinishedAtUtc,
    string? DiagnosticCategory,
    JsonElement? ResultJson,
    List<string> Evidence,
    bool PostconditionVerified,
    string? Error
);
