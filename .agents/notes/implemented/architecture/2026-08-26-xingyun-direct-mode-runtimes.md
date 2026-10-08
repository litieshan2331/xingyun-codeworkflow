# Agent Note: Run Xingyun modes through fixed direct entry scripts

Status: implemented

English | [中文](2026-08-26-xingyun-direct-mode-runtimes.zh.md)

## Problem

A generic Xingyun command selected a runtime from request data even though the caller already knew the intended route. A shared host adapter then interpreted Agent text and artifacts, duplicating business-response decisions that belong to the Agent runtime and obscuring direct inspection of model output.

## Decision

`run-list-agent.ts`, `run-form-agent.ts`, and `run-js-agent.ts` each launch one explicit Cordis runtime through the official DSH TypeScript SDK. Each script creates an isolated workspace, prepares its runtime input, waits for the SDK activity, reads its expected temporary artifact, writes one JSON object containing `agentResponse` and file metadata/content, then removes the workspace.

The list/form scripts supply `XINGYUN_JS_AGENT_COMMAND` and `XINGYUN_JS_AGENT_ARGS` to their child process. Their configured `dsh-subagent-dsh-sdk` provider owns the optional JS delegation when `funText` is non-empty; the entry scripts do not invoke the JS Agent themselves.

The scripts do not parse or validate the Agent's business response, generated JSON, JS syntax, fields, checksums, or completion state. The caller receives the final Agent text and temporary artifact content unchanged for its own handling.

## Alternatives considered

**Keep one `run-xingyun.ts` command that selects by request mode.** Rejected because the caller-facing route already identifies the intended runtime, so the command adds a routing surface without adding a capability.

**Share a list/form runtime and file adapter.** Rejected because the entry scripts are intentionally self-contained adapters in the same form as the direct JS script.

**Validate business responses and generated artifacts in the entry scripts.** Rejected because these scripts only drive an Agent runtime and return its output; business validation belongs to the configured Agent or the caller that owns the next application step.

**Start the JS Agent directly from the list/form scripts.** Rejected because list/form Cordis compositions already own the JS subagent through the official SDK provider, including its model route, environment, lifecycle, and `funText` merge.

## Consequences

Each caller chooses a fixed entry and receives raw Agent text plus the temporary output file's content. A returned file does not by itself prove that the requested generation or enhancement succeeded, and consumers that need a completed-state guarantee must add their own validation. List/form runs can still create nested JS runtimes internally without exposing that process boundary to the entry script.
