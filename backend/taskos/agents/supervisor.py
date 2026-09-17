"""Supervisor agent: turns a high-level goal into a validated task DAG.

The model is asked to output tasks using short local labels (e.g. "r1",
"synth") for dependencies, because that's far more reliable to generate than
asking it to invent real ids. This module resolves those labels into real
task ids and validates the result as a DAG before anything else in the system
sees it.
"""

from __future__ import annotations

from taskos.agents.llm import LLMMalformedOutputError, generate_json
from taskos.config import settings
from taskos.core.graph import InvalidGraphError, TaskGraph
from taskos.core.models import AgentType, Run, Task

_ASSIGNABLE_AGENTS = [a for a in AgentType if a is not AgentType.SUPERVISOR]
_AGENT_NAMES = ", ".join(a.value for a in _ASSIGNABLE_AGENTS)


class OutOfScopeError(Exception):
    """Raised when the goal can't be accomplished by any available agent
    (e.g. it asks TaskOS to take a real-world action like controlling the
    user's computer, rather than research/write/illustrate something)."""

SYSTEM_INSTRUCTION = f"""You are the Supervisor of TaskOS, an agentic system that
breaks a goal into a task DAG (directed acyclic graph) for other agents to execute.

Available agent types: {_AGENT_NAMES}
- "research": calls a web search tool and records findings. Independent research
  tasks (e.g. researching different companies or topics) must NOT depend on each
  other, so they can run in parallel.
- "synthesis": merges findings from multiple research tasks. depends_on must list
  every research task it merges.
- "writer": drafts final written output from research or synthesis findings.
- "illustrator": generates one image from a text description. Use it ONLY when
  the goal explicitly asks for a picture, illustration, logo, diagram, or visual
  -- never for a goal that just happens to be about a visual subject (e.g.
  researching a painter does not need an illustrator task).
- "coder": writes and runs a short Python script. Use it ONLY for a goal that
  needs a computation, algorithm, or data transformation carried out (e.g. "is
  17 prime?", "sort this list", "compute compound interest on $500 at 5% for
  10 years") -- never for research or anything requiring internet access, file
  access, or user input, since the code runs headless with no network.

Rules:
- Give every task a short local label for "id" (e.g. "r1", "r2", "synth", "write").
  "depends_on" must reference these local labels, not real ids.
- Only create parallel research tasks when the goal genuinely names multiple
  independent subjects (e.g. multiple companies). Otherwise use one research task.
- An illustrator task's description is the image prompt itself -- describe the
  desired picture directly (subject, style, composition), not "generate an image of...".
- A coder task must be standalone: "depends_on" must be empty. It cannot use
  another task's findings (e.g. research output) as input.
- If the goal cannot be accomplished by any of the available agents -- e.g. it asks
  you to control the user's device, open/run/install/delete something on their
  computer, send a message or email, browse or act on an account, or take any other
  real-world action instead of researching, writing, or illustrating -- do not
  output a task array. Output exactly this JSON object instead, with no other keys:
  {{"unsupported": true}}
- Otherwise, output ONLY a JSON array, no prose, no markdown fences. Each element:
  {{"id": "<local label>", "description": "<specific, actionable task description>",
    "agent": "<one of: {_AGENT_NAMES}>", "depends_on": ["<local label>", ...]}}
"""

_OUT_OF_SCOPE_MESSAGE = (
    "TaskOS is currently only able to research topics, generate images, and "
    "run short code snippets -- it can't take real-world actions like this yet."
)


def _build_prompt(goal: str) -> str:
    return f"Goal: {goal}\n\nProduce the task DAG as a JSON array."


async def plan(goal: str) -> Run:
    """Ask Gemini to plan a goal, then return a Run with a validated task DAG.

    Raises OutOfScopeError if the goal isn't something any available agent can
    do (not retryable -- the goal itself needs to change, not the plan).
    Raises LLMMalformedOutputError if the model's output can't be turned into
    a runnable DAG -- callers treat this as a retryable planning failure.
    """
    raw = await generate_json(_build_prompt(goal), system_instruction=SYSTEM_INSTRUCTION)
    if isinstance(raw, dict) and raw.get("unsupported"):
        raise OutOfScopeError(_OUT_OF_SCOPE_MESSAGE)
    if not isinstance(raw, list) or not raw:
        raise LLMMalformedOutputError("Expected a non-empty JSON array of tasks")

    run = Run(goal=goal)
    label_to_id: dict[str, str] = {}
    depends_on_labels: dict[str, list[str]] = {}
    tasks: list[Task] = []

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise LLMMalformedOutputError(f"Task #{i} is not a JSON object")

        label = item.get("id")
        description = item.get("description")
        agent_name = item.get("agent")
        if not label or not description or not agent_name:
            raise LLMMalformedOutputError(f"Task #{i} is missing id/description/agent")
        if label in label_to_id:
            raise LLMMalformedOutputError(f"Duplicate task label '{label}'")

        try:
            agent = AgentType(agent_name)
        except ValueError:
            raise LLMMalformedOutputError(
                f"Task '{label}' has unknown agent type '{agent_name}'"
            ) from None
        if agent not in _ASSIGNABLE_AGENTS:
            raise LLMMalformedOutputError(f"Task '{label}' cannot be assigned to '{agent_name}'")
        if agent is AgentType.CODER and item.get("depends_on"):
            raise LLMMalformedOutputError(f"Task '{label}' is a coder task but has depends_on")

        task = Task(
            run_id=run.run_id,
            description=description,
            assigned_agent=agent,
            max_attempts=settings.max_task_retries,
        )
        label_to_id[label] = task.task_id
        depends_on_labels[task.task_id] = item.get("depends_on") or []
        tasks.append(task)

    for task in tasks:
        resolved: list[str] = []
        for label in depends_on_labels[task.task_id]:
            if label not in label_to_id:
                raise LLMMalformedOutputError(
                    f"Task '{task.description}' depends on unknown label '{label}'"
                )
            resolved.append(label_to_id[label])
        task.depends_on = resolved

    try:
        TaskGraph(tasks).validate()
    except InvalidGraphError as exc:
        raise LLMMalformedOutputError(f"Supervisor produced an invalid DAG: {exc}") from exc

    run.tasks = tasks
    return run
