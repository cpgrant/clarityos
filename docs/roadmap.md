# ClarityOS Roadmap

This document is the detailed milestone plan for ClarityOS.

Update this file first when milestone scope changes, then keep the summary in the repository root `README.md` aligned with it.

## Current Status

- Latest completed milestone: `v1.6`
- Current release: `v1.6`
- Current focus: `v1.7` deployment and operator maturity
- Next planned step: `v1.7` Slice 4 release path for repeatable self-hosted deployment
- Active execution plan: [`docs/v1.7-checklist.md`](./v1.7-checklist.md)
- Companion planning notes: [`docs/differentiators.md`](./differentiators.md) and [`docs/v1.7-release-path.md`](./v1.7-release-path.md)
- Recent release notes: [`docs/v1.6-checklist.md`](./v1.6-checklist.md), [`docs/v1.6-release-path.md`](./v1.6-release-path.md), [`docs/architecture-v1.6.md`](./architecture-v1.6.md), and [`docs/history/v1.6.md`](./history/v1.6.md)

## Milestones

1. `v0.1` - execution
Status: completed

2. `v0.2` - traceability
Status: completed

3. `v0.2.1` - lightweight testing
Status: completed

4. `v0.2.2` - multi-provider support
Status: completed

5. `v0.3` - explicit tools
Status: completed

6. `v0.4` - control and safety
Status: completed

7. `v0.5` - workflows and control plane
Status: completed

8. `v0.6` - queues and jobs
Status: completed

9. `v0.7` - memory and retrieval
Status: completed

Goal:
Add explicit, typed memory and bounded retrieval without breaking the runtime's inspectability.

Slices:

- Slice 1: typed memory layers - completed
- Slice 2: bounded retrieval - completed
- Slice 3: agent integration - completed
- Slice 4: workflow memory lifecycle - completed
- Slice 5: retrieval safety and operator controls - completed

Acceptance criteria:

- Typed memory records exist with explicit schemas such as `fact`, `summary`, `observation`, and `artifact_ref`.
- Durable memory storage supports create, read, list, and bounded query operations.
- `memory_read` and `memory_write` are enforced through the existing policy layer.
- Retrieval is bounded by explicit limits and returns source metadata instead of silently dumping full memory state into prompts.
- Memory activity appears in traces and the workflow control plane.
- Automated tests cover memory CRUD, bounded retrieval, policy denial, and workflow integration.

10. `v0.8` - multi-agent coordination
Status: completed

Goal:
Coordinate multiple agents through explicit workflows, bounded delegation, and scoped memory access.

Slices:

- Slice 1: bounded delegation foundations - completed
- Slice 2: child workflow execution and lineage - completed
- Slice 3: scoped shared memory handoff - completed
- Slice 4: operator inspection and failure isolation - completed

Acceptance criteria:

- Workflows can coordinate bounded child agents with explicit lineage and role assignment.
- Agent delegation respects configurable limits for depth, fan-out, and allowed capabilities.
- Agents can read shared memory selectively and write scoped memory intentionally.
- Multi-agent execution is inspectable through traces, workflow state, and control-plane views.
- Failures in one child workflow do not silently corrupt sibling or parent workflow state.
- Automated tests cover delegation, lineage, scoped memory access, and failure isolation.

11. `v0.9` - production hardening
Status: completed

Goal:
Prepare the runtime for sustained production operation with recovery, governance, and operational visibility.

Slices:

- Slice 1: state versioning and migrations - completed
- Slice 2: operator recovery and pruning controls - completed
- Slice 3: observability and incident debugging - completed
- Slice 4: auth, deployment, and resilience hardening - completed

Acceptance criteria:

- Durable state formats are versioned and have a clear migration path.
- Operators can inspect, replay, prune, and recover workflows, jobs, artifacts, and memory safely.
- Auth, access control, retention, and audit expectations are defined for production deployment.
- Queue, worker, memory, and workflow subsystems expose enough observability for incident debugging.
- System behavior under retry, reclaim, restart, and partial-failure conditions is documented and tested.
- Production hardening includes load, soak, and recovery validation beyond the minimal unit suite.

12. `v1.0` - release readiness and first production profile
Status: completed

Goal:
Translate the hardened runtime into a repeatable, supportable production profile with explicit rollout defaults, operational playbooks, and a narrow first live use case.

Slices:

- Slice 1: soak, load, and recovery validation - completed
- Slice 2: rollout defaults and deployment profile - completed
- Slice 3: operator governance and maintenance playbooks - completed
- Slice 4: first production path and release criteria - completed

Acceptance criteria:

- Soak, restart, reclaim, retry, and failure-recovery drills are repeatable and documented beyond the unit suite.
- A production deployment profile exists with explicit env defaults, policy posture, retention guidance, and operator expectations.
- Operators have documented playbooks for incident response, safe maintenance, migration, recovery, and pruning.
- The first production use case is intentionally narrow, measurable, and supported by release gates rather than informal judgment.

First production use case:

- single-tenant, self-hosted, API-first workflow runtime
- bounded assistant and researcher-style tasks started through workflow and job APIs
- operator-managed recovery, replay, prune, and inspection flows
- no chat surface, plugin marketplace, or many-channel product scope yet

Release gates:

- targeted trusted-runtime drills pass
- full unit suite passes
- production env, operator auth, and explicit config selection are in place
- operator profile confirms the intended runtime posture
- queue and worker health start clean on release candidates
- documented playbooks map directly to real operator endpoints

13. `v1.1` - first assistant surface and session gateway
Status: completed

Goal:
Deliver the first real “OpenClaw-ish” use case on top of the hardened runtime: one assistant surface, one explicit session model, and one thin operator-facing UI, while preserving ClarityOS’s stronger guarantees and bounded execution model.

Slices:

- Slice 1: session and conversation model - completed
- Slice 2: first assistant surface - completed
- Slice 3: operator UI and conversation inspection - completed
- Slice 4: first external channel or gateway adapter - completed

Acceptance criteria:

- The runtime supports explicit conversation/session records that map inbound user interactions to workflows, memory scope, and operator-visible history.
- A first assistant surface exists, ideally web-first, that can send user messages into the runtime and receive async workflow-backed responses.
- Operators can inspect sessions, related workflows, incidents, and recovery actions through a simple UI rather than API-only access.
- Channel integration remains thin: surface adapters hand work to the existing workflow, queue, memory, and control-plane layers rather than duplicating runtime logic.
- The shipped use case is intentionally narrow and reliable, with one strong surface before broader channel expansion.

Chosen first adapter:

- embeddable web widget loaded through `/widget.js` and rendered by `/widget`
- browser-only, same-runtime, and self-hosted
- explicitly not Telegram, Slack, or broad multi-channel routing at this stage

14. `v1.2` - assistant deployment hardening
Status: completed

Goal:
Turn the new assistant-facing surfaces into a narrowly deployable assistant profile with explicit auth, embed posture, and operator support boundaries.

Slices:

- Slice 1: session ownership and surface auth - complete
- Slice 2: embed policy and branded deployment profile - complete
- Slice 3: assistant operator playbooks and maintenance flows - complete
- Slice 4: first assistant deployment path and release criteria - complete

Acceptance criteria:

- Assistant and operator surfaces have explicit auth and session-ownership expectations rather than relying on development-only posture.
- Embed origins, branding defaults, and surface configuration are documented and adjustable without code changes.
- Operators have playbooks for assistant-surface incidents, recovery, pruning, and deployment maintenance.
- One narrow assistant deployment path is measurable, supportable, and clearly in scope before broader surface expansion.

First deployment path:

- self-hosted browser-first assistant through `/assistant`
- optional embeddable widget through `/widget` and `/widget.js`
- explicit session ownership and operator-authenticated maintenance
- intentionally no non-browser transport, marketplace, or hosted hub

Release gates:

- `scripts/run_release_validation.sh` passes
- `python -m unittest discover -s tests -v` passes
- assistant session token posture is explicit
- widget deployment posture is explicit
- operator playbooks are runnable
- session archive/prune and workflow recovery flows are supportable

## Proposed Next Roadmap

This section is intentionally forward-looking. Unlike the milestones above, these entries are proposed planning targets rather than committed release scope.

15. `v1.3` - assistant quality and grounding
Status: completed

Goal:
Make the deployed assistant meaningfully useful by improving answer quality, context grounding, and task structure before broadening channel scope.

Delivered focus:

- repo-grounded assistant behavior for docs, codebase, and runtime questions
- stronger use of explicit tools for retrieval and inspection
- less repetitive, more structured answer formatting
- better browser-surface usability and end-to-end validation

Delivered use cases:

- browser-first research assistant
- repo-aware ClarityOS copilot
- operator-visible troubleshooting assistant

Explicitly not the focus:

- many-channel expansion
- media-heavy assistant behaviors
- marketplace-style plugin growth

Current progress note:

- Slice 1 is complete
- Slice 2 is complete through guarded repo/runtime retrieval, policy-aware controlled external fetches, runtime-ID inspection summaries, and stronger working-answer framing to improve assistant answers without adding a second execution path
- Slice 3 is complete through browser-surface smoke validation and clearer loading, empty, error, and session-state behavior for `/assistant`, `/operator`, and `/widget`
- Slice 4 is complete through an explicit `v1.3` release path and measurable assistant-quality gates

16. `v1.4` - tooling maturity and capability depth
Status: completed

Goal:
Strengthen the assistant's explicit tool layer so it can inspect, retrieve, and act usefully without losing ClarityOS's inspectability and policy boundaries.

Delivered focus:

- richer repo and runtime inspection tools
- controlled external retrieval such as `fetch_url` or `http_get`
- clearer tool argument and output schemas
- cleaner tool organization as the registry grows

Delivered use cases:

- deeper repo and docs research
- runtime-aware operator assistance
- more capable structured task execution

Current progress note:

- Slice 1 is complete through an internal split of the tool layer into explicit repo, web, runtime-inspection, memory, utility, and shared-support modules while preserving `runtime.tools` as the single registry facade
- Slice 2 is complete through richer retrieval output shapes, compact runtime/web summaries, a bounded `list_directory` helper, and clearer documented examples for testing and interpreting the stronger retrieval layer
- Slice 3 is complete through narrow operator-safe action tools, a dedicated `runtime_write` capability, denial coverage for non-maintenance agents, and an explicit decision to keep `v1.4` runtime-maintenance-only on the action side
- Slice 4 is complete through an explicit `v1.4` release path and release gates for the stronger tool layer
- The current `v1.4` action decision is to keep the shipped set runtime-maintenance-only and explicitly defer repo write helpers until a later milestone

Explicitly not the focus:

- broad write or exec-by-default behavior
- repo write helpers in `v1.4`
- hidden skills or opaque agent magic

17. `v1.5` - memory and continuity maturity
Status: completed

Goal:
Make long-running assistant sessions more coherent through better memory lifecycle controls, continuity summaries, and bounded carry-forward behavior.

Companion notes:

- [`docs/v1.5-memory-strategy.md`](./v1.5-memory-strategy.md)
- [`docs/differentiators.md`](./differentiators.md)
- [`docs/v1.5-release-path.md`](./v1.5-release-path.md)

Current progress note:

- Slice 1 is complete through explicit session continuity compaction helpers, persisted compaction metadata with source references, an operator-invoked compaction path, and control-plane visibility for active continuity state
- Slice 2 is complete through session-level continuity summaries, bounded carry-forward context for assistant turns, and visibility for continuity summaries in session and control-plane state
- Slice 3 is complete through continuity budget rules, operator-facing recommendations for compact/recompact decisions, and playbook guidance for continuity cleanup flows
- Slice 4 is complete through an explicit `v1.5` release path and release gates for memory and continuity maturity
- `v1.5` is now the current release, and follow-on work moves to `v1.6` multi-agent work quality

Delivered focus:

- memory summarization and compaction
- stronger session continuity across long-lived conversations
- clearer memory budgeting and carry-forward rules
- better operator inspection of continuity state

Delivered use cases:

- persistent browser-first personal assistant
- longer-running research threads
- operator-supported continuity across sessions

Explicitly not the focus:

- broad multi-user shared-memory collaboration
- opaque long-context dumping into prompts

18. `v1.6` - multi-agent work quality
Status: completed

Goal:
Improve the quality of bounded multi-agent work so delegation produces better outcomes rather than just more parallelism.

Companion notes:

- [`docs/v1.6-checklist.md`](./v1.6-checklist.md)
- [`docs/differentiators.md`](./differentiators.md)
- [`docs/v1.6-release-path.md`](./v1.6-release-path.md)

Current progress note:

- `v1.6` is now the current release
- Slice 1 is complete through explicit delegation contract fields, default bounded child-task briefs, earlier validation for invalid subruns, and control-plane visibility for child task intent
- Slice 2 is complete through bounded child-result synthesis, supervisor-style next-action guidance, and clearer child rollups in workflow inspection
- Slice 3 is complete through delegated-run audit summaries, contract-gap and result-gap surfacing, and delegation-denied trace visibility in incident review
- Slice 4 is complete through an explicit `v1.6` release path and release gates for higher-quality bounded multi-agent work
- Release validation and milestone closeout have passed for `v1.6`

Delivered focus:

- stronger task decomposition patterns
- supervisor-style bounded coordination
- better delegation contracts and role discipline
- clearer child-result synthesis and failure isolation

Delivered use cases:

- planner/researcher/executor workflows
- bounded multi-agent research and troubleshooting
- operator-auditable task decomposition

Explicitly not the focus:

- open-ended autonomous agent swarms
- unbounded delegation depth or fan-out
- hidden multi-agent orchestration that only exists in prompts

19. `v1.7` - deployment and operator maturity
Status: in progress

Goal:
Make ClarityOS easier to package, deploy, and operate repeatedly as a self-hosted assistant system.

Companion notes:

- [`docs/v1.7-checklist.md`](./v1.7-checklist.md)
- [`docs/differentiators.md`](./differentiators.md)
- [`docs/v1.7-release-path.md`](./v1.7-release-path.md)

Current progress note:

- `v1.7` is now the active milestone with a concrete execution checklist
- Slice 1 is complete through a first `Containerfile`, `compose.yaml`, `.dockerignore`, a packaged worker loop, and documented packaged startup posture for API and background execution
- Slice 2 is complete through an explicit `CLARITYOS_STATE_ROOT` contract, operator-visible storage and backup posture, a single packaged state mount, and a storage/backup playbook
- Slice 3 is complete through a runtime-posture dashboard summary, clearer packaged-runtime guidance in the operator console, and an operator runtime playbook for repeated self-hosted operation
- Slice 4 will define the narrow release path and release gates for the first supportable packaged deployment profile
- The next planned step is Slice 4 implementation

Planned focus:

- Podman or container packaging
- repeatable deployment and runtime profile guidance
- improved operator ergonomics, monitoring, and maintenance flows
- cleaner environment and storage layout expectations

Planned use cases:

- repeatable self-hosted assistant deployment
- cleaner operator onboarding and maintenance
- more production-friendly local and team setups

Explicitly not the focus:

- hosted hub infrastructure
- broad SaaS-style multi-tenancy

20. `v1.8` - careful external integration
Status: proposed

Goal:
Add one or two narrow integrations beyond the browser surfaces without turning ClarityOS into a many-channel product prematurely.

Likely focus:

- one careful external integration beyond `/assistant` and `/widget`
- thin adapters that hand work to the existing workflow and session runtime
- deployment-safe boundary rules for external surfaces

Likely use cases:

- one narrow external assistant touchpoint
- webhook-driven or controlled integration scenarios

Explicitly not the focus:

- Telegram, Slack, Discord, WhatsApp, and similar sprawl all at once
- broad channel parity with OpenClaw

21. `v1.9` - product refinement and supported workflows
Status: proposed

Goal:
Refine ClarityOS into a clearer, more polished self-hosted assistant product with explicit supported workflows and stronger day-to-day usability.

Likely focus:

- tighter product polish across assistant, operator, and embed surfaces
- clearer supported assistant workflows and boundaries
- higher confidence from real usage, reliability, and maintenance feedback
- release discipline around what is intentionally supported

Likely use cases:

- polished browser-first daily-use assistant
- clearer self-hosted assistant offering for bounded tasks
- more credible operator-facing assistant product identity

Explicitly not the focus:

- trying to match OpenClaw channel breadth feature-for-feature
- broad ecosystem expansion before the core experience is strong
