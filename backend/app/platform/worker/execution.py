"""AI Resource Scheduler (GPU/CPU allocations, priority scheduling)."""
import heapq
import threading
import time
from typing import Dict, Any, List, Optional
from app.platform.errors import ResilienceError

class AIResourceScheduler:
    """Manages AI model execution slots (CPU/GPU load, priority, concurrent limits)."""

    def __init__(self, max_concurrent_gpu_slots: int = 4, max_concurrent_cpu_slots: int = 8):
        self.max_concurrent_gpu_slots = max_concurrent_gpu_slots
        self.max_concurrent_cpu_slots = max_concurrent_cpu_slots
        self.active_gpu_slots = 0
        self.active_cpu_slots = 0
        self._lock = threading.Lock()
        
        # Priority Queue for waiting tasks: list of (priority, timestamp, task_id, task_meta)
        # Priority lower is higher priority (standard heapq behavior)
        self._waiting_queue: List[Any] = []
        self._active_tasks: Dict[str, Dict[str, Any]] = {}

    def request_execution_slot(self, task_id: str, is_gpu: bool = True, priority: int = 2) -> bool:
        """Request a slot. Returns True if execution can start immediately, False if queued.
        
        Priorities: 0 = critical/realtime, 1 = user/interactive, 2 = background/analytics.
        """
        with self._lock:
            # Check availability
            if is_gpu:
                if self.active_gpu_slots < self.max_concurrent_gpu_slots:
                    self.active_gpu_slots += 1
                    self._active_tasks[task_id] = {"is_gpu": True, "started_at": time.time()}
                    return True
            else:
                if self.active_cpu_slots < self.max_concurrent_cpu_slots:
                    self.active_cpu_slots += 1
                    self._active_tasks[task_id] = {"is_gpu": False, "started_at": time.time()}
                    return True

            # If no slot is free, queue the task
            task_meta = {
                "task_id": task_id,
                "is_gpu": is_gpu,
                "priority": priority
            }
            # Push into priority queue, sorting by priority first, then insertion time
            heapq.heappush(self._waiting_queue, (priority, time.time(), task_id, task_meta))
            return False

    def release_execution_slot(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Release active slot, promoting next queued task from priority queue."""
        next_task = None
        with self._lock:
            active_info = self._active_tasks.pop(task_id, None)
            if not active_info:
                return None
            
            # Decrement slots
            if active_info["is_gpu"]:
                self.active_gpu_slots -= 1
            else:
                self.active_cpu_slots -= 1

            # Try to promote next waiting task matching the slot resource
            temp_list = []
            promoted = False
            
            while self._waiting_queue:
                priority, ts, q_id, q_meta = heapq.heappop(self._waiting_queue)
                req_gpu = q_meta["is_gpu"]
                
                if req_gpu and self.active_gpu_slots < self.max_concurrent_gpu_slots:
                    self.active_gpu_slots += 1
                    self._active_tasks[q_id] = {"is_gpu": True, "started_at": time.time()}
                    next_task = q_meta
                    promoted = True
                    break
                elif not req_gpu and self.active_cpu_slots < self.max_concurrent_cpu_slots:
                    self.active_cpu_slots += 1
                    self._active_tasks[q_id] = {"is_gpu": False, "started_at": time.time()}
                    next_task = q_meta
                    promoted = True
                    break
                else:
                    # Keep waiting
                    temp_list.append((priority, ts, q_id, q_meta))
            
            # Re-push tasks that weren't promoted
            for item in temp_list:
                heapq.heappush(self._waiting_queue, item)
                
            return next_task

    def get_metrics(self) -> Dict[str, Any]:
        """Aggregate current resource usage metrics."""
        with self._lock:
            return {
                "gpu_utilization": self.active_gpu_slots / max(1, self.max_concurrent_gpu_slots),
                "cpu_utilization": self.active_cpu_slots / max(1, self.max_concurrent_cpu_slots),
                "gpu_slots_active": self.active_gpu_slots,
                "gpu_slots_max": self.max_concurrent_gpu_slots,
                "cpu_slots_active": self.active_cpu_slots,
                "cpu_slots_max": self.max_concurrent_cpu_slots,
                "backlog_waiting_count": len(self._waiting_queue)
            }
