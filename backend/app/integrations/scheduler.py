"""Background scheduler using thread timers.

Offline-first, zero external dependencies (no Celery, Redis, or APScheduler).
Parses cron expressions, triggers sync actions, automation workflows, or agent tasks.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.base import get_db
from app.integrations.models import ScheduledJob, ScheduledJobRun

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BackgroundScheduler:
    """In-process scheduled task runner."""

    def __init__(self):
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._running = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._schedule_next_tick()
            logger.info("Background integration scheduler started.")

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            logger.info("Background integration scheduler stopped.")

    def _schedule_next_tick(self) -> None:
        # Check every 10 seconds for due jobs
        self._timer = threading.Timer(10.0, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _tick(self) -> None:
        if not self._running:
            return

        db_session_factory = get_db()
        db = next(db_session_factory)
        try:
            now_dt = _now()
            due_jobs = db.query(ScheduledJob).filter(
                ScheduledJob.is_active.is_(True),
                ScheduledJob.next_run_at <= now_dt,
            ).all()

            for job in due_jobs:
                self._execute_job(db, job)

        except Exception as e:
            logger.error(f"Scheduler tick error: {e}")
        finally:
            db.close()

        # Reschedule next check
        with self._lock:
            if self._running:
                self._schedule_next_tick()

    def _execute_job(self, db: Session, job: ScheduledJob) -> None:
        run = ScheduledJobRun(
            job_id=job.id,
            status="running",
            started_at=_now(),
        )
        db.add(run)
        db.commit()

        t0 = time.perf_counter()
        status = "completed"
        error_msg = None
        result = {}

        try:
            action = job.action
            action_type = action.get("type")
            action_config = action.get("config", {})

            if action_type == "sync":
                # Trigger a connector sync
                conn_id = action_config.get("connector_id")
                from app.integrations.sdk.runtime import ConnectorRuntime
                runtime = ConnectorRuntime(db, job.workspace_id, job.owner_id)
                res = runtime.execute_with_telemetry(
                    connector_id=conn_id,
                    operation_name="sync",
                    func=lambda c: c.sync(),
                )
                result = {"synced": True, "details": str(res)}

            elif action_type == "automation":
                # Trigger an automation workflow
                wf_id = action_config.get("workflow_id")
                from app.integrations.automation import AutomationEngine
                engine = AutomationEngine(db)
                res = engine.execute_workflow(wf_id)
                result = {"workflow_executed": True, "execution_id": res.id}

            elif action_type == "agent":
                # Directly execute an agent task
                agent_type = action_config.get("agent_type", "research")
                prompt = action_config.get("prompt", "Perform scheduled workspace audit.")

                from app.orchestration.interfaces import TaskNode, TaskGraph
                from app.orchestration.orchestrator import Orchestrator

                orchestrator = Orchestrator(db)
                node_id = f"sch_{uuid.uuid4().hex[:8]}"
                node = TaskNode(id=node_id, name=f"Scheduled Task", agent_type=agent_type, prompt=prompt)
                graph = TaskGraph(nodes={node_id: node}, dependencies={})
                res = orchestrator.execute_graph(job.owner_id, job.workspace_id, graph)
                result = {"agent_task_completed": True, "result": res}

            else:
                status = "failed"
                error_msg = f"Unknown action type: {action_type}"

        except Exception as e:
            status = "failed"
            error_msg = str(e)
            logger.error(f"Scheduled job '{job.id}' failed: {e}")

        # Save run results
        duration_ms = (time.perf_counter() - t0) * 1000
        run.status = status
        run.duration_ms = duration_ms
        run.completed_at = _now()
        run.result = result
        run.error = error_msg

        # Update job schedule cursors
        job.last_run_at = run.completed_at
        job.run_count += 1

        if job.max_runs and job.run_count >= job.max_runs:
            job.is_active = False
            job.next_run_at = None
        else:
            job.next_run_at = self.calculate_next_run(job.job_type, job.schedule, run.completed_at)

        db.commit()

    def calculate_next_run(self, job_type: str, schedule: str, base_time: datetime) -> datetime:
        """Determines the next execution time based on type and schedule."""
        if job_type == "interval":
            # schedule represents seconds, e.g. "3600"
            try:
                seconds = int(schedule)
            except ValueError:
                seconds = 3600
            return base_time + timedelta(seconds=seconds)
        elif job_type == "one_time":
            # schedule is ISO format, e.g. "2026-07-13T12:00:00"
            try:
                return datetime.fromisoformat(schedule)
            except ValueError:
                return base_time + timedelta(days=1)
        else:
            # simple cron: hourly, daily, weekly stubs
            if schedule == "hourly":
                return base_time + timedelta(hours=1)
            elif schedule == "daily":
                return base_time + timedelta(days=1)
            elif schedule == "weekly":
                return base_time + timedelta(weeks=1)
            else:
                # default fallback
                return base_time + timedelta(hours=1)


# Singleton scheduler instance
scheduler = BackgroundScheduler()
