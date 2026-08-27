# 星云 Web preset

[English](README.md) | 中文

本示例为 DSH Web 增加四个星云 Agent Preset，不修改独立星云接口脚本及其 Cordis 组合。

## 启动 Web

完成项目构建后，从仓库根目录运行：

```powershell
pnpm run build
$env:DSH_HOME = (Resolve-Path ".\examples\xingyun-web").Path
$env:XINGYUN_JSONRPC_BIN = (Resolve-Path ".\packages\examples\jsonrpc-demo\lib\bin.js").Path
$env:XINGYUN_JS_AGENT_CONFIG = (Resolve-Path ".\examples\xingyun-mvp\js-agent.cordis.yml").Path
pnpm dsh web --patch ".\examples\xingyun-web\xingyun-web.cordis.yml" --no-open
```

Web 进程会从 `$DSH_HOME/.agent-presets` 发现四个 preset。请在新建对话前选择 preset；对话启动后会固定使用创建时选择的 preset。

## Preset

- `xingyun-list` 检索列表知识库并写入 `generated-list.json`。当 `funText` 包含用户明确要求的 JavaScript 行为时，通过官方 `dsh-subagent-dsh-sdk` provider 调用现有 JS runtime。
- `xingyun-form` 检索表单知识库并写入 `generated-form.json`。JS 委托使用与列表 preset 相同的官方 SDK provider。
- `xingyun-js` 检索 JS 知识库，并修改当前工作区中的一个 JavaScript 文件。
- `xingyun-auto` 是一个同时拥有三组带前缀 WeKnora 工具的 Agent。它根据用户文字和图片选择 list 或 form，只使用选中的页面知识库；只有用户明确要求 JavaScript 行为时才使用 JS 知识库。

Web preset 组合负责面向模型的 persona 和工具。overlay 负责共享 vLLM 路由、preset 名单以及宿主侧 JS 子 runtime provider。Web UI 及其 Host API 继续负责会话状态、工作区访问和文件展示。

overlay 不调用四个独立的 `run-*.ts` 脚本；这些脚本继续作为 CLI 或 BFF 的直接接口。

## 环境变量

模型和 WeKnora 凭据从 DSH 的正常环境或 `.env` 文件读取。overlay 需要 `VLLM_BASE_URL`、`VLLM_API_KEY`、`WEKNORA_BASE_URL`、`WEKNORA_API_KEY` 以及三个 `XINGYUN_*_KB_ID` 变量。`XINGYUN_JSONRPC_BIN` 和 `XINGYUN_JS_AGENT_CONFIG` 仅在 list/form preset 委托 JS runtime 时使用。
