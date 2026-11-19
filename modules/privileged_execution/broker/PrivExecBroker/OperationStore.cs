using System;
using System.Collections.Generic;
using System.Text.Json;

namespace PrivExecBroker;

public enum IdempotencyLookupKind
{
    NewRequest,
    ReplayExisting,
    PayloadMismatch
}

public sealed record IdempotencyLookup(IdempotencyLookupKind Kind, OperationRecord? ExistingRecord);

public interface IOperationStore
{
    IdempotencyLookup CheckIdempotency(string clientSid, string requestId, string canonicalPayloadHash);
    void InsertOperation(OperationRecord record);
    void UpdateOperationState(
        string operationId,
        OperationState state,
        int? exitCode,
        DateTimeOffset? finishedAtUtc,
        string? diagnosticCategory,
        JsonElement? resultJson,
        List<string> evidence,
        bool postconditionVerified,
        string? error);
    OperationRecord? GetByOperationId(string operationId);
    bool TryAcquireTargetMutationLock(string targetId, string operationId);
    void ReleaseTargetMutationLock(string targetId, string operationId);
    int MarkInterruptedExecutionsAsOutcomeUnknown();
}

public sealed class InMemoryOperationStore : IOperationStore
{
    private readonly object _sync = new();
    private readonly Dictionary<string, OperationRecord> _byOpId = new(StringComparer.Ordinal);
    private readonly Dictionary<string, OperationRecord> _byClientReq = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _activeTargetMutations = new(StringComparer.OrdinalIgnoreCase);

    private static string CompositeKey(string clientSid, string requestId) => $"{clientSid}\n{requestId}";

    public IdempotencyLookup CheckIdempotency(string clientSid, string requestId, string canonicalPayloadHash)
    {
        lock (_sync)
        {
            if (!_byClientReq.TryGetValue(CompositeKey(clientSid, requestId), out OperationRecord? existing))
            {
                return new IdempotencyLookup(IdempotencyLookupKind.NewRequest, null);
            }
            if (!string.Equals(existing.CanonicalPayloadHash, canonicalPayloadHash, StringComparison.Ordinal))
            {
                return new IdempotencyLookup(IdempotencyLookupKind.PayloadMismatch, existing);
            }
            return new IdempotencyLookup(IdempotencyLookupKind.ReplayExisting, existing);
        }
    }

    public void InsertOperation(OperationRecord record)
    {
        lock (_sync)
        {
            _byOpId[record.OperationId] = record;
            if (!string.IsNullOrEmpty(record.RequestId))
            {
                _byClientReq[CompositeKey(record.ClientSid, record.RequestId)] = record;
            }
        }
    }

    public void UpdateOperationState(
        string operationId,
        OperationState state,
        int? exitCode,
        DateTimeOffset? finishedAtUtc,
        string? diagnosticCategory,
        JsonElement? resultJson,
        List<string> evidence,
        bool postconditionVerified,
        string? error)
    {
        lock (_sync)
        {
            if (!_byOpId.TryGetValue(operationId, out OperationRecord? existing))
            {
                throw new KeyNotFoundException($"Unknown operation '{operationId}'.");
            }
            OperationRecord updated = existing with
            {
                State = state,
                ExitCode = exitCode,
                FinishedAtUtc = finishedAtUtc,
                DiagnosticCategory = diagnosticCategory,
                ResultJson = resultJson,
                Evidence = new List<string>(evidence),
                PostconditionVerified = postconditionVerified,
                Error = error
            };
            _byOpId[operationId] = updated;
            if (!string.IsNullOrEmpty(updated.RequestId))
            {
                _byClientReq[CompositeKey(updated.ClientSid, updated.RequestId)] = updated;
            }
        }
    }

    public OperationRecord? GetByOperationId(string operationId)
    {
        lock (_sync)
        {
            return _byOpId.TryGetValue(operationId, out OperationRecord? rec) ? rec : null;
        }
    }

    public bool TryAcquireTargetMutationLock(string targetId, string operationId)
    {
        lock (_sync)
        {
            if (_activeTargetMutations.ContainsKey(targetId))
            {
                return false;
            }
            _activeTargetMutations[targetId] = operationId;
            return true;
        }
    }

    public void ReleaseTargetMutationLock(string targetId, string operationId)
    {
        lock (_sync)
        {
            if (_activeTargetMutations.TryGetValue(targetId, out string? owner) &&
                string.Equals(owner, operationId, StringComparison.Ordinal))
            {
                _activeTargetMutations.Remove(targetId);
            }
        }
    }

    public int MarkInterruptedExecutionsAsOutcomeUnknown() => 0;
}
