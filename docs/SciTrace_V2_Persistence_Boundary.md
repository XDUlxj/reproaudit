# SciTrace V2 --- Persistence Boundary

> Status: V1 architecture decision\
> Scope: SciTrace business entities, LangGraph runtime state,
> ArtifactStore, and persistence responsibility boundaries.

## 1. Decision

SciTrace separates **runtime persistence** from **business
persistence**.

-   LangGraph `checkpointer` persists the current agent/thread state for
    resume, HITL, fault recovery, and conversation continuity.
-   SciTrace's application database persists durable domain facts such
    as `Task`, `ResearchResource`, `ExperimentSpec`, and
    `ExperimentRun`.
-   ArtifactStore persists heavy files such as logs, checkpoints, result
    files, stdout/stderr, and other experiment artifacts.
-   Specialist Agents do **not** directly operate PostgreSQL.
-   Business/control flow decides **when an entity becomes durable**; a
    persistence service/repository decides **how it is written**.

This avoids treating LangGraph State as the business database and avoids
giving every Agent unrestricted persistence responsibilities.

## 2. Official framework basis

LangGraph officially distinguishes two persistence concerns:

1.  **Checkpointer** --- persists graph-state snapshots scoped to a
    thread. It is intended for thread continuity, HITL, time travel, and
    fault tolerance.
2.  **Store** --- persists application-defined information outside graph
    state and can be shared across threads.

SciTrace additionally has an explicit domain model and PostgreSQL
schema. Therefore its scientific records remain application/domain
persistence rather than being encoded only in checkpoints.

Official reference:
https://docs.langchain.com/oss/python/langgraph/persistence

## 3. Persistence layers

``` text
SciTrace
│
├── LangGraph Checkpointer
│   └── runtime/thread state
│       ├── messages
│       ├── task_id
│       ├── resources (working snapshot)
│       ├── experiment_spec (current working object)
│       ├── experiment_run (current working object)
│       └── required_specialist
│
├── PostgreSQL / Domain Persistence
│   ├── Task
│   ├── ResearchResource
│   ├── ExperimentSpec
│   └── ExperimentRun
│
└── ArtifactStore
    ├── stdout / stderr
    ├── experiment logs
    ├── checkpoints
    ├── result files
    └── other large artifacts
```

The Main State is a **working snapshot**, not the authoritative
historical database.

## 4. Core rule: business decides WHEN, persistence layer decides HOW

Do not implement a generic rule such as:

``` python
if isinstance(value, Record):
    database.save(value)
```

An object being entity-shaped does not mean it has reached a valid
business commit point.

Instead:

``` text
Business event / accepted result
          ↓
Is this now a durable domain fact?
          ↓ yes
Persistence Service / Repository
          ↓
PostgreSQL
          ↓ success
Update Main State
          ↓
ToolMessage / continue Agent Loop
```

The persistence layer may provide generic mechanics such as create,
update, transaction handling, retries, serialization, and tracing. It
must not decide business lifecycle transitions by inspecting object
types.

## 5. Entity commit points

### Task

Persist when the user's request formally enters SciTrace.

``` text
User request
    ↓
create Task
    ↓
persist Task
    ↓
start SciTraceAgent
```

### ResearchResource

Persist after Discovery has produced an accepted resource that SciTrace
intends to retain.

``` text
DiscoveryAgent
    ↓
DiscoveryResult
    ↓
normalize / validate / accept
    ↓
persist ResearchResource
    ↓
merge canonical resource into Main State
```

A raw search candidate is not automatically a durable
`ResearchResource`.

### ExperimentSpec

`ExperimentSpecDraft` is not a formal experiment specification and must
not be auto-persisted as one.

``` text
AnalysisAgent
    ↓
ProposeSpec
    ↓
ExperimentSpecDraft
    ↓
Policy / HITL if required
    ↓ accepted
materialize ExperimentSpec
    ↓
persist ExperimentSpec
    ↓
state.experiment_spec = persisted_spec
```

When revising a spec:

``` text
new_spec.parent_spec_id = current_spec.id
```

The existing spec remains historical data.

### ExperimentRun

`ExperimentRun` has a real lifecycle and therefore is persisted more
than once.

``` text
Execution starts
    ↓
create ExperimentRun(status="running")
    ↓
persist
    ↓
process executes / monitoring
    ↓
update runtime facts
    ↓
terminal status
    ├── succeeded
    ├── failed
    └── interrupted
    ↓
persist terminal Run
```

A failed `ExperimentRun` does not automatically mean the top-level
`Task` failed.

## 6. Persist before publishing the fact to Main State

For newly accepted durable facts, use:

``` text
Specialist result
      ↓
validate / materialize
      ↓
PERSIST
      ↓ success
UPDATE MAIN STATE
      ↓
ToolMessage
      ↓
next Agent-loop iteration
```

Avoid publishing a new durable fact into Main State first and hoping the
database write succeeds later.

### Consistency limitation

PostgreSQL business persistence and a LangGraph checkpoint are not
automatically one distributed transaction. A crash can occur after a
database commit but before the next graph checkpoint.

Therefore persistence operations that may be replayed should be designed
to be **idempotent** where practical:

-   preserve stable entity IDs;
-   use deterministic uniqueness/identity rules where appropriate;
-   make create/update operations safe to retry;
-   avoid duplicate entities merely because a wrapper was re-executed.

Do not claim PostgreSQL + LangGraph checkpointing is atomic unless an
explicit transaction protocol is implemented.

## 7. Specialist responsibility

Specialists return domain results; they should not contain arbitrary
database logic.

``` text
DiscoveryAgent → DiscoveryResult
AnalysisAgent  → AnalysisResult
ExecutionAgent → ExecutionResult
```

The wrapper/application boundary interprets those results and performs
the appropriate commit.

Preferred:

``` python
result = discovery_agent.invoke(...)
resources = resource_service.accept_and_persist(result.discovered_resources)
return Command(update={...})
```

Avoid embedding raw `postgres.execute(...)` / `commit()` calls in the
specialist reasoning loop.

## 8. State vs database vs artifact store

  -----------------------------------------------------------------------
  Concern                             Owner
  ----------------------------------- -----------------------------------
  Current Agent-loop working context  `SciTraceState` / checkpointer

  Conversation and ToolMessages       LangGraph State / checkpointer

  Durable Task                        PostgreSQL

  Durable ResearchResource            PostgreSQL

  Versioned ExperimentSpec            PostgreSQL

  ExperimentRun lifecycle             PostgreSQL

  Historical Specs/Runs               PostgreSQL

  Large logs/checkpoints/result files ArtifactStore

  Current lightweight artifact        `ExperimentRun` / State as needed
  metadata                            
  -----------------------------------------------------------------------

A file being persistent does not imply it needs an independent
`Artifact` entity. For V1, `ArtifactOutput` can remain an embedded value
object containing persistent URI/hash metadata.

## 9. Middleware boundary

Middleware is appropriate for cross-cutting concerns such as tracing,
logging, retry instrumentation, token/cost accounting, validation hooks,
and common persistence instrumentation.

Middleware should **not** silently decide that every `Record` must be
committed.

The business wrapper/service should explicitly trigger a domain commit
at the correct lifecycle point. Middleware may wrap/observe the
operation, but should not invent the lifecycle transition.

Official references:
https://docs.langchain.com/oss/python/langchain/middleware/overview\
https://docs.langchain.com/oss/python/langchain/middleware/custom

## 10. V1 implementation shape

``` python
class TaskRepository:
    ...

class ResourceRepository:
    ...

class ExperimentSpecRepository:
    ...

class ExperimentRunRepository:
    ...


class ResourceService:
    def accept_and_persist(self, resources):
        # normalize / deduplicate / validate / upsert
        ...


class ExperimentService:
    def materialize_spec(self, draft, parent_spec_id=None):
        # construct formal ExperimentSpec and persist it
        ...


class ExecutionService:
    def create_run(self, spec):
        ...

    def update_run(self, run):
        ...
```

Exact repository APIs are implementation details and should be designed
when persistence code is implemented.

## 11. V1 invariants

1.  `SciTraceState` is not the historical database.
2.  Checkpoints are runtime persistence, not a replacement for domain
    persistence.
3.  Specialist Agents do not directly own PostgreSQL writes.
4.  `ExperimentSpecDraft` is never silently treated as a formal
    `ExperimentSpec`.
5.  Formal entities are persisted only at explicit business commit
    points.
6.  A newly committed fact is persisted before it is published into Main
    State.
7.  Persistence operations should tolerate replay where practical.
8.  Heavy artifacts stay outside checkpoints and PostgreSQL rows where
    appropriate.
9.  Do not add an entity merely because something is stored on disk.
10. Keep V1 explicit; avoid persistence magic.

## 12. Official references

-   LangGraph Persistence:
    https://docs.langchain.com/oss/python/langgraph/persistence
-   LangChain Middleware Overview:
    https://docs.langchain.com/oss/python/langchain/middleware/overview
-   LangChain Custom Middleware:
    https://docs.langchain.com/oss/python/langchain/middleware/custom
