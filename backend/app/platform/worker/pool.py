"""Specialized Worker Pools implementation."""
import threading
import time
from typing import Dict, Any, List, Callable
from app.platform.errors import WorkerError

class SpecializedWorkerPool:
    """Represents a specialized worker pool that consumes tasks and executes them."""

    def __init__(self, name: str, concurrency: int = 2):
        self.name = name
        self.concurrency = concurrency
        self._threads: List[threading.Thread] = []
        self._active_jobs: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self.metrics = {
            "processed_count": 0,
            "failed_count": 0,
            "latency_sum_ms": 0.0
        }

    def start(self, task_consumer: Callable[[], None]) -> None:
        """Spawn consumer worker threads."""
        self._stop_event.clear()
        with self._lock:
            if self._threads:
                return # Already started
            
            for i in range(self.concurrency):
                t = threading.Thread(
                    target=self._worker_loop,
                    args=(task_consumer,),
                    name=f"worker-{self.name}-{i}",
                    daemon=True
                )
                self._threads.append(t)
                t.start()

    def stop(self) -> None:
        """Trigger termination event and wait for threads to exit."""
        self._stop_event.set()
        threads_to_join = []
        with self._lock:
            threads_to_join = list(self._threads)
            self._threads.clear()
        
        for t in threads_to_join:
            t.join(timeout=1.0)

    def _worker_loop(self, task_consumer: Callable[[], None]) -> None:
        while not self._stop_event.is_set():
            try:
                task_consumer()
            except Exception:
                time.sleep(0.5) # Avoid CPU burn on consecutive failure loops
            time.sleep(0.05)

    def register_job(self, job_id: str, payload: Any) -> None:
        with self._lock:
            self._active_jobs[job_id] = {
                "payload": payload,
                "started_at": time.time()
            }

    def deregister_job(self, job_id: str, success: bool = True, duration_ms: float = 0.0) -> None:
        with self._lock:
            self._active_jobs.pop(job_id, None)
            if success:
                self.metrics["processed_count"] += 1
                self.metrics["latency_sum_ms"] += duration_ms
            else:
                self.metrics["failed_count"] += 1

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pool_name": self.name,
                "concurrency": self.concurrency,
                "active_threads": len(self._threads),
                "active_jobs_count": len(self._active_jobs),
                "active_jobs": list(self._active_jobs.keys()),
                "processed_total": self.metrics["processed_count"],
                "failed_total": self.metrics["failed_count"],
                "avg_latency_ms": (
                    self.metrics["latency_sum_ms"] / max(1, self.metrics["processed_count"])
                )
            }
