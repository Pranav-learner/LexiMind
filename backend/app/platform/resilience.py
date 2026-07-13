"""Resilience patterns (Circuit Breaker, Bulkheads, Retries, Dead-Letter Queue)."""
import time
import functools
import threading
from typing import Callable, Any, Dict, List, Optional
from app.platform.errors import ResilienceError

class CircuitBreaker:
    """Decorator pattern implementing a simple Circuit Breaker.
    
    States: Closed (normal), Open (tripped), Half-Open (trialing).
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 5.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "CLOSED" # CLOSED, OPEN, HALF-OPEN
        self.failure_count = 0
        self.last_state_change = time.time()
        self._lock = threading.Lock()

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self._lock:
                now = time.time()
                # Check if recovery timeout has passed to move from OPEN to HALF-OPEN
                if self.state == "OPEN":
                    if now - self.last_state_change > self.recovery_timeout:
                        self.state = "HALF-OPEN"
                        self.last_state_change = now
                    else:
                        raise ResilienceError(f"Circuit breaker is OPEN for {func.__name__}. Downstream requests blocked.")

            try:
                result = func(*args, **kwargs)
                with self._lock:
                    if self.state == "HALF-OPEN":
                        # Successful call closes the circuit
                        self.state = "CLOSED"
                        self.failure_count = 0
                        self.last_state_change = time.time()
                return result
            except Exception as e:
                with self._lock:
                    self.failure_count += 1
                    if self.state == "CLOSED" and self.failure_count >= self.failure_threshold:
                        self.state = "OPEN"
                        self.last_state_change = time.time()
                    elif self.state == "HALF-OPEN":
                        # Any failure in HALF-OPEN state trips it back immediately
                        self.state = "OPEN"
                        self.last_state_change = time.time()
                raise e
        return wrapper


class Bulkhead:
    """Limits the number of concurrent executions allowed through a function (bulkhead partition)."""

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)

    def __call__(self, func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            acquired = self._semaphore.acquire(blocking=False)
            if not acquired:
                raise ResilienceError(f"Bulkhead concurrency limit ({self.max_concurrent}) exceeded for {func.__name__}.")
            try:
                return func(*args, **kwargs)
            finally:
                self._semaphore.release()
        return wrapper


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0, dlq_callback: Optional[Callable[[Exception, str], None]] = None):
    """Decorator retrying operations with exponential backoff, redirecting to DLQ on exhaustion."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_err = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    if attempt == max_attempts:
                        # Exceeded retries, trigger DLQ if provided
                        if dlq_callback:
                            try:
                                dlq_callback(e, func.__name__)
                            except Exception:
                                pass
                        raise e
                    time.sleep(current_delay)
                    current_delay *= backoff
            raise last_err or Exception("Retry loop completed without execution.")
        return wrapper
    return decorator
