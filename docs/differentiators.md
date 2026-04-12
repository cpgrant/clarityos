# ClarityClaw Differentiators

This document tracks standout product directions that could make ClarityClaw meaningfully better than a generic assistant wrapper.

These are not all committed roadmap items. They are strategy notes to help identify which ideas are worth protecting as the runtime evolves.

## Near-Term Differentiators

### Auditable Continuity

ClarityClaw should be able to continue long-running assistant threads without turning continuity into hidden prompt stuffing.

What makes this different:

- summaries are explicit and inspectable
- source references remain visible
- operators can see continuity state directly
- bounded carry-forward is part of the product, not an implementation accident

### Explicit Memory, Not Vibes

ClarityClaw already treats memory as typed state rather than an implicit side effect. Future work should preserve that shape.

What makes this different:

- memory records have explicit schemas and scopes
- memory access is policy-controlled
- memory can be inspected, queried, and audited outside the model

### Thin Surfaces Over A Visible Runtime

Assistant surfaces should stay thin while the runtime remains the real product.

What makes this different:

- browser and widget surfaces stay replaceable
- workflow, queue, memory, and recovery behavior remain shared
- operators inspect the same state the assistant uses

## Promising Mid-Term Directions

### Preference Memory With Consent

The assistant could eventually remember durable user preferences, but only in an explicit, user-respectful way.

Promising shape:

- clearly scoped preference records
- easy review and deletion
- no hidden behavioral profile

### Safe Recurring Helper Behaviors

The runtime could support narrow, approved recurring actions that help a user over time.

Promising shape:

- opt-in automation rules
- narrow action classes
- visible logs and approvals
- easy disable path

Examples:

- remind about release checks
- regenerate derived docs or diagrams after approved edits
- flag drift between roadmap, README, and release notes

### Operator-Visible Personal Continuity

ClarityClaw could become unusually strong at "personal assistant over time" behavior without becoming spooky or opaque.

Promising shape:

- continuity summaries visible in operator views
- carry-forward decisions visible and bounded
- session and memory lifecycle supportable in production

## Filters For New Ideas

New "winner feature" ideas are more likely to fit ClarityClaw well if they are:

- explicit rather than magical
- inspectable rather than hidden
- bounded rather than open-ended
- user-controlled rather than assumed
- operator-supportable rather than consumer-app-only

If an idea only works by hiding state, masking autonomy, or weakening runtime visibility, it is probably not a good ClarityClaw differentiator.
