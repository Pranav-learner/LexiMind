"""Event-driven automation engine.

Binds triggers (events, schedules, webhooks) with action nodes.
Reuses the existing Agent Runtime (AgentTaskService / Orchestrator) for executing
complex AI tasks, executing integrations and notification actions directly.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.integrations.errors import AutomationError, WorkflowNotFound
from app.integrations.event_bus import event_bus
from app.integrations.models import AutomationExecution, AutomationWorkflow, IntegrationEvent
from app.integrations.sdk.runtime import ConnectorRuntime

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AutomationEngine:
    def __init__(self, db: Session):
        self.db = db

    def evaluate_condition(self, condition: Dict[str, Any], event: IntegrationEvent) -> bool:
        """Evaluates a single conditional node against the trigger event payload."""
        field = condition.get("field")
        operator = condition.get("operator")  # equals, contains, starts_with, exists
        value = condition.get("value")

        if not field:
            return True

        # Resolve dotted fields, e.g. 'payload.repository.name'
        parts = field.split(".")
        current: Any = event
        for p in parts:
            if hasattr(current, p):
                current = getattr(current, p)
            elif isinstance(current, dict) and p in current:
                current = current[p]
            else:
                return False if operator != "not_exists" else True

        if operator == "equals":
            return str(current) == str(value)
        elif operator == "contains":
            return str(value) in str(current)
        elif operator == "starts_with":
            return str(current).startswith(str(value))
        elif operator == "exists":
            return current is not None
        elif operator == "not_exists":
            return current is None

        return False

    def check_conditions(self, workflow: AutomationWorkflow, event: IntegrationEvent) -> bool:
        """Verifies if all conditions evaluate to true."""
        for cond in workflow.conditions:
            if not self.evaluate_condition(cond, event):
                return False
        return True

    def execute_workflow(self, workflow_id: str, trigger_event: Optional[IntegrationEvent] = None) -> AutomationExecution:
        """Executes workflow actions sequentially or delegating tasks to the Agent Runtime."""
        workflow = self.db.query(AutomationWorkflow).filter(
            AutomationWorkflow.id == workflow_id,
            AutomationWorkflow.is_active.is_(True),
        ).first()

        if not workflow:
            raise WorkflowNotFound(workflow_id)

        execution = AutomationExecution(
            workflow_id=workflow_id,
            workspace_id=workflow.workspace_id,
            trigger_event_id=trigger_event.id if trigger_event else None,
            status="running",
            steps_completed=0,
            steps_total=len(workflow.actions),
            started_at=_now(),
        )
        self.db.add(execution)
        self.db.commit()

        t0 = time.perf_counter()
        results = []
        status = "completed"
        error_msg = None

        for idx, action in enumerate(workflow.actions, start=1):
            action_type = action.get("type")
            action_config = action.get("config", {})

            try:
                if action_type == "connector_action":
                    # Execute an action via ConnectorRuntime
                    conn_id = action_config.get("connector_id")
                    op = action_config.get("operation")
                    args = action_config.get("arguments", {})

                    runtime = ConnectorRuntime(self.db, workflow.workspace_id, workflow.owner_id)
                    res = runtime.execute_with_telemetry(
                        connector_id=conn_id,
                        operation_name=op,
                        func=lambda c: getattr(c, op)(**args) if hasattr(c, op) else c.sync(),
                    )
                    results.append({"step": idx, "type": action_type, "result": str(res)})

                elif action_type == "agent_task":
                    # Delegate complex prompt/task to Agent Runtime / AgentTaskService
                    agent_type = action_config.get("agent_type", "research")
                    prompt = action_config.get("prompt", "Analyze recent events.")

                    # Reuse existing Orchestrator TaskGraph design if needed
                    from app.orchestration.interfaces import TaskNode, TaskGraph
                    from app.orchestration.orchestrator import Orchestrator

                    # We simulate or direct route to the orchestrator to process
                    orchestrator = Orchestrator(self.db)
                    # Create a single task graph node
                    node_id = f"auto_{uuid.uuid4().hex[:8]}"
                    node = TaskNode(
                        id=node_id,
                        name=f"Automation Action {idx}",
                        agent_type=agent_type,
                        prompt=prompt,
                    )
                    graph = TaskGraph(nodes={node_id: node}, dependencies={})
                    res = orchestrator.execute_graph(workflow.owner_id, workflow.workspace_id, graph)

                    results.append({"step": idx, "type": action_type, "result": res})

                elif action_type == "notification":
                    # Direct dispatch to communications (e.g. Slack/Email)
                    conn_id = action_config.get("connector_id")
                    msg = action_config.get("message", "Automation event triggered.")

                    runtime = ConnectorRuntime(self.db, workflow.workspace_id, workflow.owner_id)
                    res = runtime.execute_with_telemetry(
                        connector_id=conn_id,
                        operation_name="notify",
                        func=lambda c: c.upload("notification", msg.encode("utf-8")) if hasattr(c, "upload") else {"sent": True},
                    )
                    results.append({"step": idx, "type": action_type, "result": res})

                else:
                    raise AutomationError(f"Unknown action type: {action_type}")

                execution.steps_completed = idx
                self.db.commit()

            except Exception as e:
                status = "failed"
                error_msg = str(e)
                logger.error(f"Workflow step {idx} failed: {e}")
                break

        duration_ms = (time.perf_counter() - t0) * 1000
        execution.status = status
        execution.duration_ms = duration_ms
        execution.completed_at = _now()
        execution.result = {"steps": results}
        execution.error = error_msg

        workflow.execution_count += 1
        workflow.last_executed_at = execution.completed_at
        self.db.commit()

        return execution

    def handle_event(self, event: IntegrationEvent) -> None:
        """Callback registered on the event bus to trigger matching workflows."""
        # Find all active workflows that match this event type or wildcard '*'
        workflows = self.db.query(AutomationWorkflow).filter(
            AutomationWorkflow.workspace_id == event.workspace_id,
            AutomationWorkflow.is_active.is_(True),
        ).all()

        for wf in workflows:
            trigger_type = wf.trigger.get("type")
            trigger_pattern = wf.trigger.get("pattern", "")

            if trigger_type == "event" and (trigger_pattern == event.event_type or trigger_pattern == "*"):
                if self.check_conditions(wf, event):
                    # Execute workflow safely in background/inline
                    try:
                        self.execute_workflow(wf.id, event)
                    except Exception as e:
                        logger.error(f"Failed to execute workflow '{wf.id}': {e}")
