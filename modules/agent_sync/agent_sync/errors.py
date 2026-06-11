"""Exception types for agent_sync."""


class AgentSyncError(RuntimeError):
    """Base class for all agent_sync errors."""


class ConfigError(AgentSyncError):
    """Raised when worker configuration is invalid."""


class PolicyError(AgentSyncError):
    """Raised when policy prevents a worker invocation."""


class WorkerError(AgentSyncError):
    """Raised when a worker cannot run or returns an invalid result."""
