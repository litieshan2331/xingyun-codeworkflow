# 星云代码生成 DSH MVP 执行文档

本文档描述第一阶段只在 DeepSeek Harness 内跑通列表 JSON、表单 JSON 和 JS 增强的执行范围。

它建立在[需求文档](XINGYUN_UI_JSON_CODEGEN_REQUIREMENTS.md)和[技术选型文档](XINGYUN_UI_JSON_CODEGEN_TECHNICAL_SELECTION.md)的已确认决策上。

## 1. MVP 目标

MVP 的可观察结果是：调用一个 DSH 输入入口，选择或自动识别模式，按需启动对应的子 DSH runtime，使用对应的 WeKnora 知识库生成最终文件，并返回统一结果。

```text
请求 -> 根 DSH -> 自动路由或指定 Agent -> WeKnora -> Agent 内部生成/修复 -> 文件响应
```

本阶段不接入中台前端、不接入平台预览接口、不建设字段元数据接口、不使用附件引用，也不在根 DSH 重复实现 JSON/JS 校验和自动修复。

## 2. 已确认的决策

| 事项 | MVP 决策 |
| --- | --- |
| Agent 拓扑 | 一个根 DSH，按需启动三个独立的子 DSH runtime |
| 列表 Agent | 使用模块设计 WeKnora 知识库 |
| 表单 Agent | 使用表单设计 WeKnora 知识库 |
| JS Agent | 使用 JS 增强 WeKnora 知识库 |
| 模型 | 本地 vLLM 的 `Qwen/Qwen3.6-27B-FP8`，同时处理文本和图片 |
| 模式 | `auto`、`list`、`form`、`js` |
| 自动路由 | 根 DSH 使用本地 Qwen 判断 `list/form/js`，只调用一个目标 Agent |
| 字段 | 用户直接在 `instruction` 中提供字段名；MVP 不调用字段接口 |
| JS 输入 | 调用方将上传的 JS 文件读取为 UTF-8 文本，放入 `jsSource` |
| JS 输出 | JS Agent 返回增强后的完整 JS 文本 |
| 校验与修复 | 由各 Agent 自己已有的能力完成；根 DSH 不增加校验器或修复循环 |
| 前端与预览 | 不属于 MVP |

## 3. WeKnora 前置条件

你当前的本地 WeKnora 地址为：

```text
http://127.0.0.1:8080
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
$env:WEKNORA_BASE_URL = "http://127.0.0.1:8080"
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

## 5. 三个子 DSH runtime

使用 `@deepseek-ai/dsh-subagent-dsh-sdk` 启动完整子 DSH runtime。

每个子 runtime 有自己的 `cordis.yml`，因此可以分别拥有：

- 一个固定的 WeKnora `knowledgeBaseIds`；
- 一个 Agent persona；
- 自己的模型和工具组合；
- 自己已有的校验与修复策略；
- 独立的 session 和进程生命周期。

建议目录：

```text
examples/xingyun-mvp/
  root.cordis.yml
  list-agent.cordis.yml
  form-agent.cordis.yml
  js-agent.cordis.yml
  prompts/
    root-router.md
    list-agent.md
    form-agent.md
    js-agent.md
```

根 DSH 的三个 SDK provider 分别指向三个子配置：

```yaml
- id: list-agent-runtime
  name: '@deepseek-ai/dsh-subagent-dsh-sdk'
  config:
    providerName: list-agent
    command: node
    args:
      - ./packages/examples/jsonrpc-demo/lib/bin.js
      - ./examples/xingyun-mvp/list-agent.cordis.yml
    provider: vllm
    model: Qwen/Qwen3.6-27B-FP8
    env:
      VLLM_API_KEY: !!js process.env.VLLM_API_KEY
      WEKNORA_BASE_URL: !!js process.env.WEKNORA_BASE_URL
      WEKNORA_API_KEY: !!js process.env.WEKNORA_API_KEY
      WEKNORA_TENANT_ID: !!js process.env.WEKNORA_TENANT_ID

- id: form-agent-runtime
  name: '@deepseek-ai/dsh-subagent-dsh-sdk'
  config:
    providerName: form-agent
    command: node
    args:
      - ./packages/examples/jsonrpc-demo/lib/bin.js
      - ./examples/xingyun-mvp/form-agent.cordis.yml
    provider: vllm
    model: Qwen/Qwen3.6-27B-FP8
    env:
      VLLM_API_KEY: !!js process.env.VLLM_API_KEY
      WEKNORA_BASE_URL: !!js process.env.WEKNORA_BASE_URL
      WEKNORA_API_KEY: !!js process.env.WEKNORA_API_KEY
      WEKNORA_TENANT_ID: !!js process.env.WEKNORA_TENANT_ID

- id: js-agent-runtime
  name: '@deepseek-ai/dsh-subagent-dsh-sdk'
  config:
    providerName: js-agent
    command: node
    args:
      - ./packages/examples/jsonrpc-demo/lib/bin.js
      - ./examples/xingyun-mvp/js-agent.cordis.yml
    provider: vllm
    model: Qwen/Qwen3.6-27B-FP8
    env:
      VLLM_API_KEY: !!js process.env.VLLM_API_KEY
      WEKNORA_BASE_URL: !!js process.env.WEKNORA_BASE_URL
      WEKNORA_API_KEY: !!js process.env.WEKNORA_API_KEY
      WEKNORA_TENANT_ID: !!js process.env.WEKNORA_TENANT_ID
```

`command` 和 `args` 必须使用当前构建产物的真实路径；上面的路径以仓库内的 JSON-RPC demo 为例，完成 build 后再确认文件存在。

## 6. 子 runtime 的 WeKnora 配置

三个子配置都挂载 `@wxg-prc-cpg/dsh-weknora`，但每个配置只绑定自己的知识库。

列表 Agent：

```yaml
- id: weknora
  name: '@wxg-prc-cpg/dsh-weknora'
  config:
    baseUrl: !!js process.env.WEKNORA_BASE_URL
    apiKey: !!js process.env.WEKNORA_API_KEY
    tenantId: !!js process.env.WEKNORA_TENANT_ID
    knowledgeBaseIds:
      - 'WEKNORA_LIST_KB_ID'
    tools:
      listKnowledgeBases: false
      search: true
      readDocument: true
      ask: false
```

表单 Agent 只把 `WEKNORA_LIST_KB_ID` 替换为 `WEKNORA_FORM_KB_ID`；JS Agent 只把它替换为 `WEKNORA_JS_KB_ID`。

三个 runtime 不共享 `knowledgeBaseIds`，也不让模型先列出知识库再自行选择。

## 7. Agent persona

列表 Agent 的 persona 只说明列表 JSON 生成任务，并要求使用模块知识库：

```text
你是星云列表 JSON 生成 Agent。
只使用当前 runtime 中配置的模块 WeKnora 知识库。
用户在 instruction 中直接提供字段名；不要调用数据库字段接口。
根据用户文字和图片生成最终列表 JSON。
如果需求包含 JS 增强，使用当前 DSH 已配置的 JS Agent 调用方式完成增强。
最终只返回统一输出对象，不解释内部检索过程。
```

表单 Agent 使用同样结构，但将模块替换为表单。

JS Agent 的 persona：

```text
你是星云 JS 增强 Agent。
只使用当前 runtime 中配置的 JS 增强 WeKnora 知识库。
根据 instruction 和 jsSource 生成增强后的完整 JS 文本。
不执行 JS，不访问列表或表单知识库。
如果无法确认适用 Hook 或页面上下文，返回 needs_input 和需要补充的信息。
最终只返回统一输出对象，不解释内部检索过程。
```

## 8. 内部输入协议

根 DSH 的输入统一为 JSON 对象：

```json
{
  "mode": "auto | list | form | js",
  "instruction": "生成员工列表，字段为 user_name、department、status。",
  "image": null,
  "jsSource": null,
  "targetVersion": "1.5.0"
}
```

`instruction` 是用户的自然语言需求，也是用户直接提供字段名的位置。本阶段不调用字段接口，Agent 直接使用用户给出的字段名。

`image` 是可选图片内容，实际承载方式由根 DSH 的输入适配器接入现有 LLM image content 机制；不把图片转成 OCR 文本后再走第二个模型。

`jsSource` 是可选的 JavaScript 源码字符串。调用方先把上传的 `.js` 文件读取为 UTF-8 文本，再放入该字段：

```json
{
  "mode": "js",
  "instruction": "增加保存前校验。",
  "jsSource": "this.form_onBeforeSave = ({ _this }) => { return true }",
  "targetVersion": "1.5.0"
}
```

UTF-8 是文件到字符串的编码约定，不是 JavaScript 语法格式。它保证中文注释、中文字符串和 JSON 传输可以被 Node.js、DSH 和模型一致读取。

MVP 不使用 `attachmentId`、临时文件路径、对象存储 URL 或 Base64 文件协议。

## 9. 模式调度

显式模式只启动一个目标 runtime：

```text
mode=list -> list-agent
mode=form -> form-agent
mode=js   -> js-agent
```

自动模式先由根 DSH 的本地 Qwen 模型根据 `instruction`、图片和文件类型输出一个枚举：

```json
{
  "mode": "list | form | js | needs_input"
}
```

随后根 DSH 只启动被选中的一个 runtime。自动路由不并行调用两个 Agent，也不比较两份生成结果。

列表或表单 Agent 需要 JS 时，使用 DSH 已有的 `dsh-subagent-dsh-sdk` 调用 JS runtime；这部分调用和 Agent 内部修复留在 DSH 内部，不返回根 DSH 的中间补丁。

## 10. 内部输出协议

目标 Agent 返回统一对象：

```json
{
  "type": "list | form | js",
  "status": "completed",
  "file": {
    "name": "generated-list.json",
    "mediaType": "application/json",
    "content": "{...}"
  }
}
```

JS 输出示例：

```json
{
  "type": "js",
  "status": "completed",
  "file": {
    "name": "enhanced.js",
    "mediaType": "application/javascript",
    "content": "this.form_onBeforeSave = ({ _this }) => { return true }"
  }
}
```

需要用户补充信息时，Agent 返回：

```json
{
  "status": "needs_input",
  "message": "请说明该 JS 增强挂载在表单还是列表。"
}
```

根 DSH 只做输出协议解包和模式字段补充，不验证星云 JSON schema、Hook、JS 语法、字段名或修复次数。

## 11. 执行顺序

### 11.1 验证 WeKnora

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

### 11.2 验证三个 Agent

按顺序运行三个最小请求：

1. 列表 Agent：`生成员工列表，字段为 user_name、department、status。`
2. 表单 Agent：`生成员工表单，字段为 user_name、department、entry_date。`
3. JS Agent：传入 `jsSource`，要求增加一个已知的 JS 增强行为。

每个请求确认：Agent 使用了自己的 WeKnora 知识库，并返回对应 `type` 的最终文件。

### 11.3 验证列表/表单到 JS

发送一个要求列表或表单同时包含 JS 增强的请求，确认列表/表单 Agent 能在 DSH 内部调用 JS Agent，并最终只返回一个完整 JSON 文件。

### 11.4 验证自动模式

分别用列表描述、表单描述、JS 文件和图片请求 `mode=auto`，确认根 DSH 只启动一个目标 Agent。

### 11.5 暂停在 DSH 输出

上述流程全部通过后，MVP 即完成。平台预览接口、中台接口正式协议、调用方 UI 和文件附件引用放到后续阶段。

## 12. MVP 验收标准

- 三个 Agent 使用三个独立的 WeKnora `knowledgeBaseIds`。
- 列表 Agent 的检索不会返回表单或 JS 知识库内容；表单和 JS Agent 同理。
- `mode=list/form/js` 只调用对应 runtime。
- `mode=auto` 只调用一个目标 runtime；无法判断时返回 `needs_input`。
- 列表和表单请求可以直接使用 `instruction` 中的字段名，不调用字段接口。
- JS 文件以 UTF-8 文本传入 `jsSource`，JS Agent 返回增强后的完整 JS 文本。
- 列表/表单需要 JS 时，能够在 DSH 内部调用 JS Agent。
- 根 DSH 不新增业务校验器、JS 执行器、修复循环、字段接口或平台预览调用。
- 三个 Agent 都能返回统一的 `type/status/file` 输出。
