using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace PrivExecBroker;

public interface ICapabilityExecutor
{
    Task<ExecutionOutcome> ExecuteAsync(
        CapabilityDescriptor descriptor,
        ValidatedRunRequest request,
        string operationId,
        CancellationToken cancellationToken);
}

public sealed record ExecutionOutcome(
    OperationState FinalState,
    int ExitCode,
    string? DiagnosticCategory,
    JsonElement ResultJson,
    List<string> Evidence,
    bool PostconditionVerified,
    string? Error
);

public sealed class SyntheticCapabilityExecutor : ICapabilityExecutor
{
    public Task<ExecutionOutcome> ExecuteAsync(
        CapabilityDescriptor descriptor,
        ValidatedRunRequest request,
        string operationId,
        CancellationToken cancellationToken)
    {
        if (descriptor.RunnerType != "synthetic")
        {
            JsonElement errResult = JsonSerializer.SerializeToElement(new { message = "External script execution requires Phase 2 ProcessExecutor." });
            return Task.FromResult(new ExecutionOutcome(
                OperationState.Failed,
                1,
                "unsupported_runner",
                errResult,
                new List<string>(),
                false,
                $"Runner '{descriptor.RunnerType}' is not enabled in SyntheticCapabilityExecutor."));
        }

        string msg = request.Parameters.TryGetValue("message", out object? m) && m is string s ? s : "ok";
        JsonElement okResult = JsonSerializer.SerializeToElement(new
        {
            synthetic = true,
            capability = descriptor.CapabilityId,
            target_id = request.Target.Id,
            mode = request.Mode,
            echo = msg
        });

        return Task.FromResult(new ExecutionOutcome(
            OperationState.Succeeded,
            0,
            null,
            okResult,
            new List<string>(),
            true,
            null));
    }
}

public sealed class BrokerEngine
{
    private readonly SessionAuthorizer _authorizer;
    private readonly IReadOnlyDictionary<string, CapabilityDescriptor> _descriptors;
    private readonly IOperationStore _store;
    private readonly ICapabilityExecutor _executor;
    private readonly Func<DateTimeOffset> _clock;
    private readonly Action? _onShutdownRequested;

    public BrokerEngine(
        SessionAuthorizer authorizer,
        IReadOnlyDictionary<string, CapabilityDescriptor> descriptors,
        IOperationStore store,
        ICapabilityExecutor executor,
        Func<DateTimeOffset>? clock = null,
        Action? onShutdownRequested = null)
    {
        _authorizer = authorizer;
        _descriptors = descriptors;
        _store = store;
        _executor = executor;
        _clock = clock ?? (() => DateTimeOffset.UtcNow);
        _onShutdownRequested = onShutdownRequested;
    }

    public async Task<string> HandleRawRequestAsync(
        string rawJson,
        ClientIdentity client,
        CancellationToken cancellationToken)
    {
        ParsedClientMessage msg;
        try
        {
            msg = ProtocolValidator.ParseAndValidate(rawJson);
        }
        catch (ProtocolValidationException ex)
        {
            return SerializeErrorResponse(null, null, null, null, "denied", false, 400, ex.Category, ex.Message);
        }

        switch (msg.Action)
        {
            case "status":
                return HandleStatus(client);
            case "shutdown":
                return HandleShutdown(client);
            case "result":
                return HandleResult(client, msg.OperationId!);
            case "run":
                return await HandleRunAsync(client, msg.RunRequest!, cancellationToken);
            default:
                return SerializeErrorResponse(null, null, null, null, "denied", false, 400, "malformed_request", "Unknown action.");
        }
    }

    private string HandleStatus(ClientIdentity client)
    {
        bool allowed = _authorizer.IsClientAllowed(client.Sid);
        if (!allowed)
        {
            return JsonSerializer.Serialize(new
            {
                protocol_version = ProtocolConstants.ProtocolVersion,
                ok = false,
                authorized = false,
                diagnostic_category = "unauthorized_identity",
                error = $"Client SID '{client.Sid}' is not authorized."
            });
        }

        SessionGrant g = _authorizer.Grant;
        bool active = !g.Revoked && _clock() < g.ExpiresAtUtc;
        return JsonSerializer.Serialize(new
        {
            protocol_version = ProtocolConstants.ProtocolVersion,
            ok = true,
            status = active ? "active" : (g.Revoked ? "revoked" : "expired"),
            session_id = g.SessionId,
            expires_at = g.ExpiresAtUtc.ToString("O"),
            allow_mutation = g.AllowMutation,
            capabilities = g.AllowedCapabilities.OrderBy(x => x, StringComparer.Ordinal).ToArray()
        });
    }

    private string HandleShutdown(ClientIdentity client)
    {
        if (!_authorizer.IsOperator(client.Sid))
        {
            return JsonSerializer.Serialize(new
            {
                protocol_version = ProtocolConstants.ProtocolVersion,
                ok = false,
                authorized = false,
                diagnostic_category = "operator_only_action",
                error = "Only the operator identity may stop or revoke the broker session."
            });
        }

        _authorizer.Revoke();
        _onShutdownRequested?.Invoke();
        return JsonSerializer.Serialize(new
        {
            protocol_version = ProtocolConstants.ProtocolVersion,
            ok = true,
            status = "revoked_and_stopping",
            session_id = _authorizer.Grant.SessionId
        });
    }

    private string HandleResult(ClientIdentity client, string operationId)
    {
        if (!_authorizer.IsClientAllowed(client.Sid) && !_authorizer.IsOperator(client.Sid))
        {
            return SerializeErrorResponse(
                operationId, null, null, null, "denied", false, 403,
                "unauthorized_identity", $"Client SID '{client.Sid}' is not authorized.");
        }

        OperationRecord? rec = _store.GetByOperationId(operationId);
        if (rec is null)
        {
            return JsonSerializer.Serialize(new
            {
                protocol_version = ProtocolConstants.ProtocolVersion,
                ok = false,
                operation_id = operationId,
                diagnostic_category = "operation_not_found",
                error = $"Operation '{operationId}' was not found."
            });
        }

        if (!string.Equals(rec.ClientSid, client.Sid, StringComparison.OrdinalIgnoreCase) &&
            !_authorizer.IsOperator(client.Sid))
        {
            return SerializeErrorResponse(
                operationId, rec.RequestId, rec.Capability, rec.TargetId, "denied", false, 403,
                "unauthorized_identity", "Client SID does not own this operation record.");
        }

        return SerializeOperationRecord(rec);
    }

    private async Task<string> HandleRunAsync(
        ClientIdentity client,
        ValidatedRunRequest req,
        CancellationToken cancellationToken)
    {
        string payloadHash = ProtocolValidator.Sha256Hex(req.CanonicalPayloadJson);
        IdempotencyLookup lookup = _store.CheckIdempotency(client.Sid, req.RequestId, payloadHash);

        if (lookup.Kind == IdempotencyLookupKind.ReplayExisting && lookup.ExistingRecord is not null)
        {
            return SerializeOperationRecord(lookup.ExistingRecord);
        }

        if (lookup.Kind == IdempotencyLookupKind.PayloadMismatch)
        {
            return SerializeErrorResponse(
                lookup.ExistingRecord?.OperationId,
                req.RequestId,
                req.Capability,
                req.Target.Id,
                "denied",
                false,
                409,
                "request_id_payload_mismatch",
                $"request_id '{req.RequestId}' was already used with a different request payload.");
        }

        _descriptors.TryGetValue(req.Capability, out CapabilityDescriptor? descriptor);
        AuthorizationDecision decision = _authorizer.Authorize(client.Sid, req, descriptor);
        string opId = "op-" + Guid.NewGuid().ToString("N")[..16];
        DateTimeOffset startedAt = _clock();

        if (!decision.Authorized || descriptor is null)
        {
            var deniedRecord = new OperationRecord(
                opId,
                req.RequestId,
                client.Sid,
                req.Capability,
                req.Target.Type,
                req.Target.Id,
                req.Mode,
                payloadHash,
                OperationState.Denied,
                false,
                null,
                startedAt,
                _clock(),
                decision.DiagnosticCategory ?? "denied",
                null,
                new List<string>(),
                false,
                decision.Reason ?? "Operation denied.");
            _store.InsertOperation(deniedRecord);
            return SerializeOperationRecord(deniedRecord);
        }

        bool isMutatingExecution = descriptor.IsMutating && req.Mode == "apply";
        if (isMutatingExecution && !_store.TryAcquireTargetMutationLock(req.Target.Id, opId))
        {
            return SerializeErrorResponse(
                null,
                req.RequestId,
                req.Capability,
                req.Target.Id,
                "denied",
                false,
                409,
                "target_mutation_conflict",
                $"Target '{req.Target.Id}' already has an active mutating operation.");
        }

        try
        {
            var executingRecord = new OperationRecord(
                opId,
                req.RequestId,
                client.Sid,
                req.Capability,
                req.Target.Type,
                req.Target.Id,
                req.Mode,
                payloadHash,
                OperationState.Executing,
                true,
                null,
                startedAt,
                null,
                null,
                null,
                new List<string>(),
                false,
                null);
            _store.InsertOperation(executingRecord);

            ExecutionOutcome outcome = await _executor.ExecuteAsync(descriptor, req, opId, cancellationToken);
            DateTimeOffset finishedAt = _clock();

            _store.UpdateOperationState(
                opId,
                outcome.FinalState,
                outcome.ExitCode,
                finishedAt,
                outcome.DiagnosticCategory,
                outcome.ResultJson,
                outcome.Evidence,
                outcome.PostconditionVerified,
                outcome.Error);

            OperationRecord completed = _store.GetByOperationId(opId)!;
            return SerializeOperationRecord(completed);
        }
        finally
        {
            if (isMutatingExecution)
            {
                _store.ReleaseTargetMutationLock(req.Target.Id, opId);
            }
        }
    }

    public static string SerializeOperationRecord(OperationRecord rec)
    {
        return JsonSerializer.Serialize(new
        {
            protocol_version = ProtocolConstants.ProtocolVersion,
            ok = rec.State == OperationState.Succeeded,
            operation_id = rec.OperationId,
            request_id = rec.RequestId,
            capability = rec.Capability,
            target_id = rec.TargetId,
            mode = rec.Mode,
            state = OperationStateNames.ToWire(rec.State),
            authorized = rec.Authorized,
            exit_code = rec.ExitCode,
            started_at = rec.StartedAtUtc.ToString("O"),
            finished_at = rec.FinishedAtUtc?.ToString("O"),
            diagnostic_category = rec.DiagnosticCategory,
            result = rec.ResultJson ?? JsonSerializer.SerializeToElement(new { }),
            evidence = rec.Evidence,
            postcondition_verified = rec.PostconditionVerified,
            error = rec.Error
        });
    }

    private static string SerializeErrorResponse(
        string? operationId,
        string? requestId,
        string? capability,
        string? targetId,
        string state,
        bool authorized,
        int? exitCode,
        string category,
        string error)
    {
        return JsonSerializer.Serialize(new
        {
            protocol_version = ProtocolConstants.ProtocolVersion,
            ok = false,
            operation_id = operationId,
            request_id = requestId,
            capability,
            target_id = targetId,
            state,
            authorized,
            exit_code = exitCode,
            diagnostic_category = category,
            result = new { },
            evidence = Array.Empty<string>(),
            postcondition_verified = false,
            error
        });
    }
}
