"""Custom platform exceptions for LexiMind."""

class PlatformError(Exception):
    """Base exception for all platform operations."""
    pass

class ConfigurationError(PlatformError):
    """Raised when there is an invalid deployment profile or configuration parameter."""
    pass

class RegistryError(PlatformError):
    """Raised when a requested provider cannot be resolved from the InfrastructureRegistry."""
    pass

class WorkerError(PlatformError):
    """Raised when worker lifecycle or job execution fails."""
    pass

class ResilienceError(PlatformError):
    """Raised when a circuit breaker trips or bulkhead capacity is exceeded."""
    pass
