# 星云代码生成 DSH MVP 执行文档

本文档描述第一阶段只在 DeepSeek Harness 内跑通列表 JSON、表单 JSON 和 JS 增强的执行范围。

它建立在[需求文档](XINGYUN_UI_JSON_CODEGEN_REQUIREMENTS.md)和[技术选型文档](XINGYUN_UI_JSON_CODEGEN_TECHNICAL_SELECTION.md)的已确认决策上。

要以 DSH 官方文档及其相关配置为中心，不能随意写代码。任何官方文档未覆盖的编排字段都不写进配置。
## 1. MVP 目标

MVP 的可观察结果是：调用方选择列表、表单或 JS 三个固定入口之一，入口启动对应的 DSH runtime，使用对应的 WeKnora 知识库生成最终文件，并原样输出 Agent 最终文本及临时文件内容。

```text
请求 -> 固定模式入口 -> 对应 Agent runtime -> WeKnora -> Agent 内部生成/修复 -> 文件响应
```

本阶段不接入中台前端、不接入平台预览接口、不建设字段元数据接口、不使用附件引用，也不增加额外的 JSON/JS 自动修复循环。

## 2. 已确认的决策

| 事项 | MVP 决策 |
| --- | --- |
| Agent 拓扑 | 三个固定入口各自启动独立的 DSH runtime |
| 列表 Agent | 使用模块设计 WeKnora 知识库 |
| 表单 Agent | 使用表单设计 WeKnora 知识库 |
| JS Agent | 使用 JS 增强 WeKnora 知识库 |
| 模型 | 本地 vLLM 的 `Qwen/Qwen3.6-27B-FP8`，同时处理文本和图片 |
| 模式 | `list`、`form`、`js` |
| 入口路由 | 调用方选择固定入口；请求字段不参与 runtime 选择 |
| 字段 | 用户直接在 `instruction` 中提供字段名；MVP 不调用字段接口 |
| JS 输入 | JS 入口读取调用方提供的本地 `.js` 文件，并写入每次请求的临时工作区 `source.js` |
| 输出 | 每个入口输出 Agent 最终文本和对应临时产物文件内容 |
| JSON 内 JS | 每个列表或表单草稿 JSON 只有一个 `funText`；仅当它包含非空原始 JS 时，目标 Agent 才调用一次 JS Agent，并用返回文本覆盖该字段 |
| 平台版本 | `targetVersion` 可选；未提供时 JS Agent 按 `1.5.0` 处理 |
| 校验与修复 | 由各 Agent 自己已有的能力完成；入口不解析或校验业务响应和产物结构 |
| JS 文本处理 | `funText` 在整个流程中保持原始 JS 文本；不做加密、压缩、Base64 或其他业务编码转换，UTF-8 仅是文件和 JSON 的字符集约定 |
| 前端与预览 | 不属于 MVP |

## 3. WeKnora 前置条件

你当前的本地 WeKnora 地址为：

```text
http://127.0.0.1
```

DSH 插件已经安装：

```powershell
pnpm dsh plugin --profile web add @wxg-prc-cpg/dsh-weknora
```

三个知识库必须分别建立并记录真实 ID：

```text
WEKNORA_LIST_KB_ID   = 模块设计知识库 ID
WEKNORA_FORM_KB_ID   = 表单设计知识库 ID
WEKNORA_JS_KB_ID     = JS 增强知识库 ID
```

WeKnora 的实际可用性以 `POST /api/v1/knowledge-search` 能返回片段为准，不以知识库列表中的 `chunk_count` 单独判断。

在 DSH 启动窗口中设置凭据：

```powershell
$env:WEKNORA_BASE_URL = "http://127.0.0.1"
$env:WEKNORA_API_KEY = "真实的 retrieve 权限 API Key"
```

普通租户 API Key 不需要 `WEKNORA_TENANT_ID`；平台级 API Key 才需要额外设置：

```powershell
$env:WEKNORA_TENANT_ID = "真实 Tenant ID"
```

API Key 不写入 Git、`cordis.yml` 或模型提示词。

## 4. 本地模型配置

每个 DSH runtime 都使用同一个本地 vLLM 路由：

```yaml
llm-pi-ai:
  providers:
    vllm:
      apiKeyEnv: VLLM_API_KEY
      api: openai-completions
      baseURL: http://168.168.190.60:8000/v1
      models:
        - id: Qwen/Qwen3.6-27B-FP8
          input: [text, image]

agent-default-model:
  provider: vllm
  model: Qwen/Qwen3.6-27B-FP8
```

模型条目必须声明 `input: [text, image]`，否则 DSH 会将其当作文本模型，图片请求可能在发送前被拒绝。

## 5. 三个官方子 runtime

三个 Agent 都使用独立的 JSON-RPC runtime；每个固定入口只启动自己的一个 runtime。

```text
examples/xingyun-mvp/
  list-agent.cordis.yml      列表 JSON 子 runtime：模块 WeKnora、PTC、coding 工具
  form-agent.cordis.yml      表单 JSON 子 runtime：表单 WeKnora、PTC、coding 工具
  js-agent.cordis.yml        JS 子 runtime：JS WeKnora、PTC、coding 工具
  run-list-agent.ts          直接启动 list-agent.cordis.yml 并输出临时 JSON 文件内容
  run-form-agent.ts          直接启动 form-agent.cordis.yml 并输出临时 JSON 文件内容
  run-js-agent.ts            直接启动 js-agent.cordis.yml 并输出临时 JS 文件内容
```

列表和表单 runtime 内部调用 JS runtime 时，沿用 DSH 官方的 [`dsh-subagent-dsh-sdk`](packages/subagent/subagent-dsh-sdk/README.md) 和其 e2e fixture [`cordis.yml`](examples/jsonrpc-agent/tests/fixtures/subagent/subagent-dsh-sdk/cordis.yml) / [`child.cordis.yml`](examples/jsonrpc-agent/tests/fixtures/subagent/subagent-dsh-sdk/child.cordis.yml) 的结构。

三个子配置使用官方要求的 `dsh-sdk-jsonrpc-server`。列表和表单配置使用官方 `dsh-subagent`、`dsh-subagent-dsh-sdk` 和 `dsh-tool-subagent` 启动 JS runtime，并将 `maxDepth` 设置为官方为进程外 provider 规定的 `provider-managed`。

`examples/package.json` 显式声明了 WeKnora 插件和 SDK client，使外部 `cordis.yml` 能从 `examples/node_modules` 解析它们；不能依赖 Web profile 中安装的插件路径。

### 5.1 PTC 和 shell 配置

三个子配置都在 agent-spine-demo.config.tools.mode 设置 code，并加载官方 dsh-code-runtime-worker-thread。这就是 DSH 当前的 PTC/Code Mode：模型直接看到 run_code 和生成的 TypeScript 工具 SDK，工具执行仍经过 DSH 的正常工具流水线。

三个子 runtime 都保留 DSH coding Agent 的文件读写、文件搜索、技能、任务和 shell 能力。POSIX runtime 启用官方 bash，Windows runtime 启用官方 pwsh；两者都保留在配置中，但 DSH 的 ctx.shell 只允许一个 provider，因此不会在同一进程同时注册两个 shell 后端。PTC SDK 会生成当前平台实际可用的 shell 工具，模型直接选择该工具。

list-agent.cordis.yml、form-agent.cordis.yml 和 js-agent.cordis.yml 分别只绑定自己的 WeKnora 知识库和工具前缀，不加载其他知识库。

### 5.2 列表和表单的 JS 委托

列表和表单 runtime 也各自注册一个名为 `xingyun-js` 的 SDK provider 及 `xingyun_js_agent` 工具。它们只在生成结果需要 JS 增强时调用该工具，并将 JS Agent 的最终结果合并到自己的 JSON；列表或表单 Agent 不直接检索 JS 知识库。

list/form 入口脚本显式将 `XINGYUN_JS_AGENT_COMMAND` 和 `XINGYUN_JS_AGENT_ARGS` 传给列表与表单 runtime。进程外 SDK provider 使用凭据清理后的环境，不能依赖这两个启动变量恰好从父进程继承。

列表或表单 Agent 先将草稿 JSON 保留在自身工作区。MVP 只允许草稿中有一个 `funText`：用户明确要求 JS、Hook、事件或其他 JS 业务行为时，Agent 在其中生成原始 JS；否则该字段为空字符串并且不调用 JS Agent。非空 `funText` 会被写入一个 UTF-8 临时 `.js` 文件，并以页面类型、用户原始需求、相关字段、`sourcePath` 及可选 `targetVersion` 委托给 JS Agent。JS Agent 完成后，父 Agent 读取该临时文件的文本并覆盖唯一的 `funText`。

## 6. 第一步运行方式

先设置环境变量；变量只在当前 PowerShell 窗口有效：

```powershell
$env:VLLM_BASE_URL = "http://168.168.190.60:8000/v1"
$env:VLLM_API_KEY = "你的本地 vLLM API Key"
$env:WEKNORA_BASE_URL = "http://127.0.0.1"
$env:WEKNORA_API_KEY = "你的 WeKnora retrieve API Key"
$env:XINGYUN_LIST_KB_ID = "模块设计知识库 ID"
$env:XINGYUN_FORM_KB_ID = "表单设计知识库 ID"
$env:XINGYUN_JS_KB_ID = "JS 增强知识库 ID"
```

三个固定入口每次都启动一个新 JSON-RPC runtime，提交一条独立任务，并在结果读取后关闭进程；没有历史对话被带入下一次调用。

```powershell
node --env-file=.env --import tsx/esm examples/xingyun-mvp/run-list-agent.ts .\request-list.json
```

```powershell
node --env-file=.env --import tsx/esm examples/xingyun-mvp/run-form-agent.ts .\request-form.json
node --env-file=.env --import tsx/esm examples/xingyun-mvp/run-js-agent.ts .\path\to\source.js "增加表单保存前校验" "1.5.0"
```

## 7. list/form 固定入口输入协议

list/form 固定入口接收一个 JSON 字符串、JSON 文件路径，或 `-`（标准输入）。请求对象：

```json
{
  "instruction": "生成员工列表，字段为 user_name、department、status。",
  "imagePath": "C:\\input\\reference.png",
 "targetVersion": "1.5.0"
}
```

入口将请求 JSON 原样交给对应 Agent，并补充本次临时工作区的 `outputPath`。`imagePath` 为字符串时，入口会把图片复制到临时工作区并替换其路径。其余业务字段的解释、校验和修复由对应 Agent 决定。

PowerShell 调用示例：

```powershell
node --env-file=.env --import tsx/esm examples/xingyun-mvp/run-form-agent.ts '.\request.json'
```

表单请求文件示例：

```json
{
  "mode": "form",
  "instruction": "生成员工登记表，字段为 user_name、department；保存前要求部门必填。"
}
```

`instruction` 是用户的自然语言需求，也是用户直接提供字段名的位置。本阶段不调用字段接口，Agent 直接使用用户给出的字段名。

`imagePath` 指向本地图片时，固定入口会将图片复制到本次临时工作区。列表和表单 runtime 使用官方 `read_image` 工具读取该图片；不将图片转成 OCR 文本后再发送给第二个模型。

JS 入口接收三个位置参数：原始 `.js` 文件路径、增强说明和可选 `targetVersion`。它不会将完整源码直接放入 Agent 提示词，而是为每次请求创建临时工作区，将原始文件复制为 `source.js`，并向 JS Agent 传递该文件的绝对 `sourcePath`。

UTF-8 是文件到字符串的字符集约定，不是业务加密或编码算法。它保证中文注释、中文字符串和 JSON 传输可以被 Node.js、DSH 和模型一致读取。内部 `funText` 在调用 JS Agent 前也按同一字符集写入临时文件。

子 Agent 使用官方 `read`、`edit`、`grep`、`glob` 和当前平台的 bash/pwsh 工具按需查看或修改 `sourcePath`，无需把数千行源码同时放入模型上下文。JS 入口在 Agent 结束后无条件读取该文件，并与 Agent 最终文本一起输出。

MVP 不使用 `attachmentId`、对象存储 URL 或 Base64 文件协议。临时工作区在调用结束后删除；`dsh-fs-local` 的 `cwd` 不是沙箱，且 shell 可以访问工作区外路径，因此本阶段只在可信的本地开发环境运行。

## 8. 固定模式入口

每个入口只启动一个对应 runtime：

```text
run-list-agent.ts -> list-agent
run-form-agent.ts -> form-agent
run-js-agent.ts   -> js-agent
```

列表或表单 Agent 需要 JS 时，使用 DSH 已有的 `dsh-subagent-dsh-sdk` 调用 JS runtime；这部分调用和 Agent 内部修复留在 DSH 内部，不返回入口的中间补丁。

## 9. 对外输出协议

三个入口都输出 Agent 最终文本和临时产物文件内容：

```json
{
  "agentResponse": "Agent 的最终文本",
  "file": {
    "name": "generated-list.json",
    "mediaType": "application/json",
    "content": "{...}"
  }
}
```

JS 入口输出示例：

```json
{
  "agentResponse": "JS Agent 的最终文本",
  "file": {
    "name": "enhanced.js",
    "mediaType": "application/javascript",
    "content": "this.form_onBeforeSave = ({ _this }) => { return true }"
  }
}
```

入口不将 `agentResponse` 解释为 completed、needs_input 或其他业务状态，也不验证 JSON schema、Hook、JS 语法、字段名或修复次数。调用方根据 Agent 最终文本和产物内容决定后续处理。

## 10. 执行顺序

### 10.1 验证 WeKnora

先用已经跑通的 `knowledge-search` 验证三个知识库各自能返回内容。

```powershell
$headers = @{ "X-API-Key" = $env:WEKNORA_API_KEY }
$body = @{ query = "form.onValuesChange"; knowledge_base_id = $env:WEKNORA_JS_KB_ID } | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "$($env:WEKNORA_BASE_URL)/api/v1/knowledge-search" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

对列表库查询 `ToolTable`，对表单库查询 `Input`，确认每个库都返回对应内容。

### 10.2 验证三个 Agent

按顺序运行三个最小请求：

1. 列表 Agent：`生成员工列表，字段为 user_name、department、status。`
2. 表单 Agent：`生成员工表单，字段为 user_name、department、entry_date。`
3. JS Agent：传入本地 `.js` 文件路径，要求增加一个已知的 JS 增强行为。

每个请求确认：Agent 使用了自己的 WeKnora 知识库，并返回对应 `type` 的最终文件。

### 10.3 验证列表/表单到 JS

发送一个要求列表或表单同时包含 JS 增强的请求，确认列表/表单 Agent 能在 DSH 内部调用 JS Agent，并最终只返回一个完整 JSON 文件。

### 10.4 暂停在 DSH 输出

上述流程全部通过后，MVP 即完成。平台预览接口、中台接口正式协议、调用方 UI 和文件附件引用放到后续阶段。

## 11. MVP 验收标准

- 三个 Agent 使用三个独立的 WeKnora `knowledgeBaseIds`。
- 列表 Agent 的检索不会返回表单或 JS 知识库内容；表单和 JS Agent 同理。
- 三个固定入口分别只调用对应 runtime。
- 列表和表单请求可以直接使用 `instruction` 中的字段名，不调用字段接口。
- JS 入口以 UTF-8 读取输入文件，并输出临时 source.js 的完整内容。
- 列表/表单需要 JS 时，能够在 DSH 内部调用 JS Agent。
- 固定入口不新增业务校验器、JS 执行器、修复循环、字段接口或平台预览调用。
- 三个 Agent 都能返回统一的 `type/status/file` 输出。
