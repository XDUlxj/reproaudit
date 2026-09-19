# SciTrace V2 --- Autonomous Routing and Specialist Delegation

> Status: V1 architecture decision\
> Goal: preserve a true autonomous Supervisor Agent Loop while allowing
> a small number of deterministic specialist-delegation constraints.

## 1. Decision

SciTrace V1 uses the LangChain **Subagents** pattern:

``` text
SciTraceAgent (main/supervisor)
        │
        ├── basic tools
        ├── DiscoveryAgent-as-Tool
        ├── AnalysisAgent-as-Tool
        └── ExecutionAgent-as-Tool
```

The default mode is autonomous:

``` text
model
  ↓
choose tool / respond
  ↓
tool execution
  ↓
ToolMessage
  ↓
model
  ↓
...
```

We do **not** build a global workflow state machine and do **not**
hard-code a permanent `Discovery → Analysis → Execution` pipeline.

For cases where the system already has an unambiguous business
requirement, SciTrace records:

``` python
required_specialist: Literal[
    "discovery",
    "analysis",
    "execution",
] | None = None
```

A middleware layer uses this control state to dynamically restrict the
specialist tools exposed to the next model call. When no specialist is
required, the Supervisor remains autonomous.

## 2. Official framework basis

LangChain's official Subagents documentation defines a central main
agent/supervisor that coordinates subagents by calling them as tools.
The main agent decides which subagent to invoke, what input to provide,
and how to combine results. It distinguishes a Supervisor from a
one-shot Router: the Supervisor is a full agent that maintains context
and dynamically delegates over multiple turns.

The same documentation shows subagents wrapped as tools and shows
wrappers returning `Command(update=...)` when structured state must be
passed back to the main agent.

Official reference:
https://docs.langchain.com/oss/python/langchain/multi-agent/subagents

LangChain custom middleware officially supports dynamic tool selection
by intercepting model calls and replacing the model-visible tool list
based on state/context.

Official reference:
https://docs.langchain.com/oss/python/langchain/middleware/custom#dynamically-selecting-tools

Therefore SciTrace uses:

``` text
Subagents
+
structured Main State
+
dynamic tool gating
```

instead of introducing a custom workflow topology before it is
necessary.

## 3. Main State

``` python
from typing import Literal
from langgraph.graph import MessagesState


class SciTraceState(MessagesState):
    """SciTraceAgent main working state."""

    task_id: str
    resources: list[ResearchResource]

    experiment_spec: ExperimentSpec | None = None
    experiment_run: ExperimentRun | None = None

    required_specialist: Literal[
        "discovery",
        "analysis",
        "execution",
    ] | None = None
```

Meaning:

``` text
required_specialist is None
    → autonomous mode

required_specialist == "discovery"
    → DiscoveryAgent delegation is currently required

required_specialist == "analysis"
    → AnalysisAgent delegation is currently required

required_specialist == "execution"
    → ExecutionAgent delegation is currently required
```

This is not a global `phase`, `current_agent`, or workflow state
machine. It represents only an **outstanding delegation constraint**.

## 4. Normal autonomous mode

Normally:

``` python
state["required_specialist"] is None
```

The Main LLM can see its normal tool set:

``` text
basic tools
├── retrieval / RAG
├── search
├── file / parsing tools
└── ...

specialist tools
├── discovery_agent
├── analysis_agent
└── execution_agent
```

The Supervisor may call a basic tool, delegate to a specialist, or
answer directly when the task is satisfied.

## 5. Constrained mode

Some structured specialist results already establish the next necessary
scientific operation.

Examples:

``` text
AnalysisResult.NeedResources
    → required_specialist = "discovery"

ExecutionSucceeded
    → required_specialist = "analysis"

ExecutionFailed
    → required_specialist = "analysis"
```

Then:

``` text
SciTraceState.required_specialist
            ↓
Tool-selection middleware
            ↓
restrict model-visible specialist tools
            ↓
Main LLM delegates to required specialist
```

Once the required delegation has been fulfilled, its wrapper clears or
replaces the constraint according to the structured result.

## 6. Filtering vs forcing

Filtering tools and forcing a tool call are not identical.

``` text
tools = [analysis_agent]
```

prevents the model from choosing another registered tool, but the
model/provider may still allow a normal answer without any tool call.

Therefore:

-   **tool filtering** is the baseline mechanism;
-   if a business invariant truly requires a call, configure the chosen
    model/provider's supported tool-choice mechanism so the required
    tool must be invoked;
-   do not claim filtering alone is a hard guarantee.

The exact forced-tool API is model/provider dependent and should be
verified against the integration actually used by SciTrace.

## 7. V1 routing table

  ----------------------------------------------------------------------------------------
  Result / condition                 Required specialist     Reason
  ---------------------------------- ----------------------- -----------------------------
  No explicit constraint             `None`                  Preserve autonomous
                                                             Supervisor behavior

  `AnalysisResult.NeedResources`     `discovery`             Analysis explicitly lacks
                                                             required scientific resources

  Discovery performed to satisfy     `analysis`              Resume the interrupted
  `NeedResources`                                            scientific analysis

  `ExecutionSucceeded`               `analysis`              Technical success still needs
                                                             scientific verification

  `ExecutionFailed`                  `analysis`              Analysis diagnoses whether
                                                             scientific/spec/resource
                                                             changes are needed

  `AnalysisResult.KeepSpec`          `None`                  Keeping the spec does not
                                                             itself mandate another
                                                             execution

  `AnalysisResult.ProposeSpec`       not a specialist route  Enter Spec
                                                             Policy/HITL/materialization
                                                             boundary

  `AnalysisResult.GoalSatisfied`     not a specialist route  Task completion path

  `AnalysisResult.UnableToResolve`   not a specialist route  HITL/failure policy

  `ExecutionInterrupted`             `None` initially        Main/Policy handles
                                                             interruption reason
  ----------------------------------------------------------------------------------------

Keep this table deliberately small.

## 8. LangGraph/LangChain-style pseudocode

The following is **architectural pseudocode**, not guaranteed copy-paste
production code. It follows the official `create_agent` +
subagent-as-tool + middleware + `Command(update=...)` patterns.

``` python
from collections.abc import Callable
from typing import Annotated, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import InjectedToolCallId, tool
from langgraph.graph import MessagesState
from langgraph.types import Command


# ------------------------------------------------------------
# Main state
# ------------------------------------------------------------

class SciTraceState(MessagesState):
    task_id: str
    resources: list[ResearchResource]
    experiment_spec: ExperimentSpec | None = None
    experiment_run: ExperimentRun | None = None
    required_specialist: Literal[
        "discovery",
        "analysis",
        "execution",
    ] | None = None


# ------------------------------------------------------------
# Specialist agents
# ------------------------------------------------------------

discovery_agent = create_agent(
    model=MODEL,
    tools=DISCOVERY_TOOLS,
    response_format=DiscoveryResult,
)

analysis_agent = create_agent(
    model=MODEL,
    tools=ANALYSIS_TOOLS,
    response_format=AnalysisResult,
)

execution_agent = create_agent(
    model=MODEL,
    tools=EXECUTION_TOOLS,
    response_format=ExecutionResult,
)


# ------------------------------------------------------------
# Subagent-as-tool wrappers
# Wrapper controls context input and state/result output.
# ------------------------------------------------------------

@tool("discovery_agent")
def call_discovery(
    task: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime,
) -> Command:
    parent = runtime.state

    result = discovery_agent.invoke({
        "task_id": parent["task_id"],
        "resources": parent["resources"],
        "recovery_count": 0,
        "messages": [HumanMessage(content=task)],
    })
    discovery_result = extract_structured_result(result)

    # Business persistence boundary: persist before publishing to Main State.
    canonical_resources = resource_service.accept_and_persist(
        discovery_result.discovered_resources
    )
    merged_resources = merge_resources(
        parent["resources"],
        canonical_resources,
    )

    # If this Discovery fulfilled a mandatory NeedResources request,
    # resume Analysis.
    next_required = (
        "analysis"
        if parent.get("required_specialist") == "discovery"
        else None
    )

    return Command(update={
        "resources": merged_resources,
        "required_specialist": next_required,
        "messages": [
            ToolMessage(
                tool_call_id=tool_call_id,
                content=render_discovery_summary(discovery_result),
            )
        ],
    })


@tool("analysis_agent")
def call_analysis(
    task: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime,
) -> Command:
    parent = runtime.state

    result = analysis_agent.invoke({
        "task_id": parent["task_id"],
        "resources": parent["resources"],
        "experiment_spec": parent.get("experiment_spec"),
        "experiment_run": parent.get("experiment_run"),
        "recovery_count": 0,
        "messages": [HumanMessage(content=task)],
    })
    analysis_result = extract_structured_result(result)

    updates = {"required_specialist": None}

    if analysis_result.action == "need_resources":
        updates["required_specialist"] = "discovery"

    elif analysis_result.action == "propose_spec":
        # Never directly overwrite experiment_spec with a draft.
        handle_spec_proposal(analysis_result.proposal)

    elif analysis_result.action == "keep_spec":
        pass

    elif analysis_result.action == "goal_satisfied":
        handle_goal_satisfied(analysis_result)

    elif analysis_result.action == "unable_to_resolve":
        handle_unable_to_resolve(analysis_result)

    updates["messages"] = [
        ToolMessage(
            tool_call_id=tool_call_id,
            content=render_analysis_summary(analysis_result),
        )
    ]
    return Command(update=updates)


@tool("execution_agent")
def call_execution(
    task: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    runtime: ToolRuntime,
) -> Command:
    parent = runtime.state

    spec = require_formal_spec(parent["experiment_spec"])
    execution_resources = select_resources(
        parent["resources"],
        spec.resource_ids,
    )

    result = execution_agent.invoke({
        "task_id": parent["task_id"],
        "experiment_spec": spec,
        "resources": execution_resources,
        "messages": [HumanMessage(content=task)],
    })
    execution_result = extract_structured_result(result)

    run = execution_service.persist_result(execution_result)

    next_required = None
    if execution_result.status in {"succeeded", "failed"}:
        next_required = "analysis"

    return Command(update={
        "experiment_run": run,
        "required_specialist": next_required,
        "messages": [
            ToolMessage(
                tool_call_id=tool_call_id,
                content=render_execution_summary(execution_result),
            )
        ],
    })


# ------------------------------------------------------------
# Dynamic tool gating middleware
# Official pattern: wrap_model_call + request.override(tools=...)
# ------------------------------------------------------------

SPECIALIST_TOOL_BY_NAME = {
    "discovery": call_discovery,
    "analysis": call_analysis,
    "execution": call_execution,
}


class SpecialistRoutingMiddleware(AgentMiddleware):
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        required = request.state.get("required_specialist")

        if required is None:
            # Autonomous mode.
            return handler(request)

        required_tool = SPECIALIST_TOOL_BY_NAME[required]

        constrained_request = request.override(
            tools=[required_tool],
        )

        # If a HARD call guarantee is required, additionally use the
        # chosen model/provider's supported forced-tool-choice API here.
        # Verify the exact integration API when implementing.

        return handler(constrained_request)


# ------------------------------------------------------------
# Main autonomous Supervisor
# ------------------------------------------------------------

scitrace_agent = create_agent(
    model=MODEL,
    tools=[
        *BASIC_SCITRACE_TOOLS,
        call_discovery,
        call_analysis,
        call_execution,
    ],
    middleware=[
        SpecialistRoutingMiddleware(),
        # HumanInTheLoopMiddleware(...),
        # tracing / retry / other focused middleware
    ],
    state_schema=SciTraceState,
    checkpointer=CHECKPOINTER,
    system_prompt=SCITRACE_SYSTEM_PROMPT,
)
```

## 9. Why wrapper returns both State update and ToolMessage

Official Subagents documentation shows a wrapper returning
`Command(update=...)` when the supervisor needs structured state in
addition to prose.

SciTrace uses:

``` text
Structured specialist result
          │
          ├── confirmed machine facts
          │       ↓
          │   Command(update=...)
          │       ↓
          │   Main State
          │
          └── concise reasoning context
                  ↓
              ToolMessage
                  ↓
              Main LLM
```

This keeps machine-readable facts out of fragile prose while still
giving the Supervisor enough context to reason.

## 10. What V1 deliberately does not implement

Do not add these merely for routing:

``` text
current_agent
next_agent
phase
route
workflow_status
global retry_count
last_analysis_result
last_execution_result
```

Do not build a fixed graph:

``` text
START → Discovery → Analysis → Execution → Analysis → END
```

That would turn SciTrace into a mostly deterministic workflow rather
than the intended Supervisor Agent.

## 11. Routing vs Policy

These are separate.

**Routing constraint** asks:

> Which specialist must be delegated to next?

Represented by `required_specialist`.

**Policy** asks:

> Is the requested action allowed?

Examples include spec approval/HITL, execution-attempt budget, command
safety, and Task completion/failure rules.

Policy + HITL should be designed separately.

## 12. Checkpoint/resume

Because `required_specialist` is part of `SciTraceState`, it is
checkpointed with the thread state.

If execution stops after:

``` text
AnalysisResult.NeedResources
→ required_specialist = "discovery"
```

the resumed run can read the structured obligation instead of asking the
LLM to reconstruct it from old prose.

LangChain custom middleware explicitly supports custom state properties
for state that must persist across hooks and for conditional/dynamic
behavior.

References:
https://docs.langchain.com/oss/python/langchain/middleware/custom\
https://docs.langchain.com/oss/python/langgraph/persistence

## 13. One unresolved implementation detail

The architecture is settled, but one API-level detail must be verified
against SciTrace's actual model integration:

> How to force a specific tool call, not merely filter the tool list.

Dynamic tool filtering is explicitly documented. Hard `tool_choice`
behavior depends on the selected model/provider integration.

Implementation order:

1.  implement dynamic filtering;
2.  verify the selected integration's forced-tool API;
3.  use hard forcing only for genuinely mandatory delegations;
4.  unit-test that mandatory delegation cannot be bypassed.

Do not invent a framework API in advance.

## 14. V1 invariants

1.  SciTraceAgent remains the central Supervisor.
2.  Specialists remain Agent-as-Tool.
3.  Default routing is autonomous LLM tool selection.
4.  Deterministic delegation is used only for explicit business
    invariants.
5.  `required_specialist` is an outstanding constraint, not a workflow
    phase.
6.  Middleware implements dynamic tool exposure.
7.  Filtering alone is not falsely described as hard forcing.
8.  Structured facts update State; ToolMessage informs the Main LLM.
9.  Subagent context is explicitly projected by wrappers rather than
    blindly sharing all parent messages.
10. No global state machine for V1.

## 15. Official references

-   LangChain Subagents:
    https://docs.langchain.com/oss/python/langchain/multi-agent/subagents

-   LangChain Middleware Overview:
    https://docs.langchain.com/oss/python/langchain/middleware/overview

-   LangChain Custom Middleware --- dynamic tool selection:
    https://docs.langchain.com/oss/python/langchain/middleware/custom#dynamically-selecting-tools

-   LangGraph Persistence:
    https://docs.langchain.com/oss/python/langgraph/persistence
