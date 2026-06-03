---
description: Review & confirm agent-proposed config changes
argument-hint: [id]
---
Call `list_pending_changes` first.

- If `$ARGUMENTS` contains an id, call `confirm_param_change(id)` and report the applied change.
- Otherwise, show the pending changes as a table (**id · key · value · reason · proposed_by**) and
  ask the user which to confirm.

Never confirm a change without the user's explicit go-ahead — proposals carry an agent's reasoning,
but the human approves.
