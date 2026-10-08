# Agent Note: Generate Xingyun pages through one automatic Agent

Status: implemented

English | [中文](2026-08-27-xingyun-auto-single-agent.zh.md)

## Problem

The fixed list and form entry scripts require the caller to choose a page type before a request reaches the harness. Some callers need one automatic page-generation endpoint that classifies the requested page and decides whether a JavaScript behavior belongs in `funText`.

## Decision

`auto-agent.cordis.yml` mounts one Agent runtime with three separately prefixed WeKnora tool groups: `auto_list_kb`, `auto_form_kb`, and `auto_js_kb`. The Agent classifies each request as list or form from its instruction and optional image, retrieves only the selected page-type knowledge base, and retrieves the JS knowledge base only for an explicit JavaScript, Hook, event, or validation behavior request. It writes the final page JSON to the supplied `outputPath`.

`run-auto-agent.ts` creates an isolated workspace, supplies that `outputPath`, copies an optional image into the workspace, drives the runtime through the official DSH TypeScript SDK, and returns the final Agent text with the temporary generated file content. It does not register or invoke subagents, parse business response fields, or validate generated content.

## Alternatives considered

**Reuse the deleted root Agent and child runtimes.** Rejected because automatic page classification and generation live in one Agent with the required knowledge tools, avoiding a model-to-model handoff and child process chain.

**Mount one combined WeKnora tool group.** Rejected because distinct prefixes let the Agent choose a page knowledge base explicitly and keep the JS knowledge base unavailable unless the request needs `funText` behavior.

**Always retrieve the JS knowledge base.** Rejected because requests without JavaScript behavior require an empty `funText`; unnecessary retrieval spends context and can introduce irrelevant implementation details.

**Validate the generated JSON in the entry script.** Rejected because the direct script only drives the Agent and exposes its raw text and file artifact; the caller owns any next-step validation.

## Consequences

The automatic endpoint produces only list or form page artifacts; it does not enhance an existing standalone JS file. A natural-language final response and a generated file are returned together without a host-computed completion status. Callers that require a verified page type, schema, or success state must validate the returned artifact themselves.
