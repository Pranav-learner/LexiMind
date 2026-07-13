"""Task Dispatcher and specialized pool orchestration."""
import time
from typing import Dict, Any, Callable, Optional
from app.platform.interfaces.queue import QueueProvider
from app.platform.worker.pool import SpecializedWorkerPool

class TaskDispatcher:
    """Consumes tasks from QueueProvider and routes them to specialized pools."""

    def __init__(self, queue_provider: QueueProvider):
        self.queue = queue_provider
        self.pools: Dict[str, SpecializedWorkerPool] = {}
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {}

        # Pre-register specialized pools
        self.create_pool("api_worker", concurrency=3)
        self.create_pool("embedding_worker", concurrency=2)
        self.create_pool("media_worker", concurrency=1)
        self.create_pool("graph_worker", concurrency=1)
        self.create_pool("agent_worker", concurrency=2)
        self.create_pool("evaluation_worker", concurrency=1)
        self.create_pool("learning_worker", concurrency=1)
        self.create_pool("optimization_worker", concurrency=1)
        self.create_pool("automation_worker", concurrency=2)
        self.create_pool("scheduler_worker", concurrency=1)

    def create_pool(self, pool_name: str, concurrency: int = 1) -> SpecializedWorkerPool:
        pool = SpecializedWorkerPool(pool_name, concurrency)
        self.pools[pool_name] = pool
        return pool

    def register_handler(self, job_type: str, handler_fn: Callable[[Dict[str, Any]], Any]) -> None:
        """Register execution business logic for a job type."""
        self._handlers[job_type] = handler_fn

    def submit_job(self, pool_name: str, job_type: str, payload: Dict[str, Any], priority: int = 0) -> str:
        """Submit a task to the queue for a specialized worker pool."""
        envelope = {
            "job_type": job_type,
            "payload": payload
        }
        return self.queue.enqueue(pool_name, envelope, priority)

    def start(self) -> None:
        """Start consumption loop for all registered worker pools."""
        for pool_name, pool in self.pools.items():
            # Create standard closure for this pool
            consumer_fn = self._make_consumer(pool_name, pool)
            pool.start(consumer_fn)

    def stop(self) -> None:
        """Stop all worker pools."""
        for pool in self.pools.values():
            pool.stop()

    def _make_consumer(self, pool_name: str, pool: SpecializedWorkerPool) -> Callable[[], None]:
        def consume() -> None:
            envelope = self.queue.dequeue(pool_name)
            if not envelope:
                return

            job_id = envelope.get("job_id", "job_unknown")
            payload_data = envelope.get("payload", {})
            job_type = payload_data.get("job_type", "unknown")
            actual_payload = payload_data.get("payload", {})

            handler = self._handlers.get(job_type)
            if not handler:
                pool.register_job(job_id, actual_payload)
                pool.deregister_job(job_id, success=False)
                return

            pool.register_job(job_id, actual_payload)
            start_time = time.time()
            success = True
            try:
                # Execute the job
                handler(actual_payload)
            except Exception:
                success = False
            finally:
                duration_ms = (time.time() - start_time) * 1000.0
                pool.deregister_job(job_id, success=success, duration_ms=duration_ms)

        return consume

    def get_status(self) -> Dict[str, Any]:
        """Aggregate statuses of all specialized worker pools."""
        return {
            "queue_metrics": self.queue.get_metrics(),
            "pools": {name: p.get_status() for name, p in self.pools.items()}
        }
