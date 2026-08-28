# Xingyun Web presets

English | [中文](README.zh.md)

This example adds four Xingyun Agent Presets to the DSH Web profile without changing the standalone Xingyun interface scripts or their Cordis compositions.

## Start the Web profile

Run from the repository root after building the project:

```powershell
pnpm run build
$env:DSH_HOME = (Resolve-Path ".\examples\xingyun-web").Path
$env:XINGYUN_JSONRPC_BIN = (Resolve-Path ".\packages\examples\jsonrpc-demo\lib\bin.js").Path
$env:XINGYUN_JS_AGENT_CONFIG = (Resolve-Path ".\examples\xingyun-mvp\js-agent.cordis.yml").Path
pnpm dsh web --patch ".\examples\xingyun-web\xingyun-web.cordis.yml" --no-open
```

The Web process discovers the four presets from `$DSH_HOME/.agent-presets`. Select a preset before creating a new conversation; a conversation keeps the preset selected when it starts.

This overlay enables the official `compaction-basic`, `tool-result-pruner`, and `command-compact` plugins. Automatic compaction and tool-result pruning apply independently to each Web session and never mix histories across presets or sessions; when idle, use `/compact` to compact the current session manually.

## Presets

- `xingyun-list` retrieves the list knowledge base and writes `generated-list.json`. When `funText` contains an explicit JavaScript behavior, the preset calls the existing JS runtime through the official `dsh-subagent-dsh-sdk` provider.
- `xingyun-form` retrieves the form knowledge base and writes `generated-form.json`. Its JS delegation uses the same official SDK provider as the list preset.
- `xingyun-js` retrieves the JS knowledge base and edits one JavaScript file in the current workspace.
- `xingyun-auto` is one Agent with three prefixed WeKnora tool groups. It chooses list or form from the user's language and image, uses only the selected page knowledge base, and uses the JS knowledge base only when the user explicitly asks for JavaScript behavior.

The Web preset compositions own model-facing personas and tools. The overlay owns the shared vLLM route, the preset roster, and the host-side JS child runtime provider. The Web UI and its host API remain responsible for session state, workspace access, and file presentation.

The overlay does not invoke the four standalone `run-*.ts` scripts. Those scripts remain direct interfaces for CLI or BFF callers.

## Environment

The model and WeKnora credentials are read from the normal DSH environment or `.env` file. The overlay expects `VLLM_BASE_URL`, `VLLM_API_KEY`, `WEKNORA_BASE_URL`, `WEKNORA_API_KEY`, and the three `XINGYUN_*_KB_ID` variables. `XINGYUN_JSONRPC_BIN` and `XINGYUN_JS_AGENT_CONFIG` are used only when list/form presets delegate to the JS runtime.
