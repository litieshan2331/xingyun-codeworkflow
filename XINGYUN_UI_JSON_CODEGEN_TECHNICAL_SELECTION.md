# 星云中台 UI JSON 与 JS 增强助手技术选型

本文档将[需求文档](XINGYUN_UI_JSON_CODEGEN_REQUIREMENTS.md)落实为第一版可实施的技术选择。

适用范围是列表 JSON、表单 JSON、直接 JS 增强、字段元数据查询和平台预览提交。

## 1. 选型原则

- 复用 DeepSeek Harness 已有的 Cordis 插件、subagent、credentials、会话持久化和 telemetry 能力，不修改 agent loop。
- 列表、表单和 JS 代码分别隔离知识来源与工具权限；模型不直接访问数据库、平台凭据或任意 HTTP 地址。
- 能用确定性规则验证的内容不依赖模型或 RAG，例如 JSON 根结构、字段引用、JSON Pointer 补丁、Hook 唯一性和响应 `type`。
- 外部平台接口尚未给出协议时，先定义适配器接口和失败行为，不编造 URL、请求字段或返回值。
- 所有知识库、schema、模板和生成文件都携带版本或内容指纹，支持复现和回归测试。

## 2. 总体选型

| 层级 | 选择 | 责任 | 不选择的方案 |
| --- | --- | --- | --- |
| 运行时 | Node.js 22、TypeScript `strict`、pnpm workspace | 复用当前 DSH 仓库的运行时与构建链 | 新建 Java/Python 主服务 |
| agent 编排 | DeepSeek Harness 内部组合 | DSH 自己编排列表、表单和 JS 增强 Agent；中台仅调用 DSH 输入输出接口 | 中台 BFF 编排三个 Agent、三个独立 DSH 进程或模型编写的固定工作流脚本 |
| 文本与图片模型 | `dsh-llm-pi-ai` 的本地 vLLM 路由，`Qwen/Qwen3.6-27B-FP8` | 同一个声明图文输入的模型处理文本、图片、列表、表单和 JS 任务 | 在代码中固化 API key 或模型端点，或另建 OCR/视觉服务 |
| 表单/模块 RAG | `@wxg-prc-cpg/dsh-weknora` | 列表和表单 Agent 通过 DSH 插件调用 WeKnora 的检索/读文档工具，并按知识库 id 隔离范围 | 在当前 DSH 核心树手写 RAG、另建向量库或在 Host 重复实现检索 |
| embedding | WeKnora 服务自身的 embedding 与索引能力 | DSH 只调用 WeKnora，不在 Host 或 Agent 进程内维护向量 | 假定 Qwen 生成模型同时提供 embedding，或新增独立 embedding 服务 |
| JS 知识 | `@wxg-prc-cpg/dsh-weknora` 的独立 JS 知识库 | JS Agent 通过 WeKnora 检索 Hook 文档；Agent 自己负责生成、校验和修复 | 中台 BFF 复制 JS 知识库或把三库混在一个检索范围 |
| JSON/JS 校验 | 各 DSH Agent 已有的内部能力 | Agent 自己生成、校验和自动修复；Host 不重复增加 Ajv、Acorn、业务校验或修复循环 | 在中台 BFF 复制 Agent 校验逻辑 |
| 平台集成 | 中台 BFF 中的 `fetch`/`FormData` 适配器 | 认证、文件输入输出、字段接口和预览提交；不检查或改写 DSH 业务产物 | 让 Agent 调任意 URL、直接连库或直接持有平台 token |
| 会话与审计 | DSH 现有 session 持久化与 telemetry | 复用 DSH 记录请求和 Agent 子任务；不新增业务审计数据库 | 将原始凭据、表数据行或完整 BFF 响应写入会话日志 |
| 文件处理 | 复用中台现有附件/对象存储；服务仅保存受限文件引用和 SHA-256 | 图片、上传 JS 和生成文件的受控临时保留 | 将附件二进制存进 PostgreSQL 或 RAG 表 |
| 观测 | `dsh-session-telemetry-otel` + OTLP Collector + 脱敏插件 | 调用链、耗时、失败率和版本指纹 | 把原始提示词、JS 和附件内容直接导出到第三方日志平台 |
| 中台接口 | Node 22 `fetch`/`FormData` 适配器 | 接收 mode、文本、图片、JS 文件和表信息，调用 DSH 与平台预览接口 | 在本项目建设正式前端界面或把 UI 逻辑放入 DSH Web |

生成模型使用中台提供的本地 vLLM 路由。模型条目必须声明 `input: [text, image]`；`dsh-llm-pi-ai` 对未声明图片能力的手工模型默认按文本模型处理，并会在发送前拒绝图片。

```yaml
ui-onboarding:
  welcomeNoticeVersion: 2026-08-13.1

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

agent-presets:
  default: minimal
```

`minimal` preset 只提供终端和文件编辑能力，未挂载 WeKnora 或 subagent 工具。因此列表、表单和 JS Agent 必须使用各自的 DSH runtime 配置挂载必要能力；不能仅依赖全局默认 `minimal` preset。

## 3. DSH Host 与多 Agent

部署一个 DSH Host，不部署三个相互调用的 DSH 服务。

中台 BFF 根据用户选择的显式模式直接发送给列表、表单或 JS Agent；选择“自动”时发送给 DSH 内部的意图路由步骤。该步骤只用本地 Qwen 多模态模型返回一个模式枚举，不是第四个业务 Agent。

列表和表单 Agent 在需要 JS 时，通过现有 `@deepseek-ai/dsh-subagent-dsh-sdk` 调用完整的 JS Agent DSH runtime。该 provider 让子 runtime 自己的 `cordis.yml` 决定模型、skill、工具、校验和修复策略；父 Agent 只获得最终输出。

DSH 是唯一能够执行意图路由、选择 Hook、合并补丁、修复和校验产物的组件。中台 BFF 是唯一调用字段和预览平台接口的组件，并透传 DSH 返回的 `type`、状态和文件。

JS Agent 的 WeKnora 知识库范围、persona、工具集和自动修复策略是 DSH 内部配置；中台 BFF 不设置或覆盖它们。JS Agent 不能直接调用平台预览接口。

```text
platform UI
  -> select auto | list | form | js
  -> middle-platform BFF -> DSH intent router when auto
                         -> selected DSH Agent
                              -> optional JS Agent DSH runtime
  <- { type, status, file } <- platform preview adapter
```

| 子 Agent | 模型选择 | 允许工具 | 结构化结果 |
| --- | --- | --- | --- |
| 列表 Agent | `vllm/Qwen/Qwen3.6-27B-FP8` | 模块 WeKnora、只读字段元数据 | JSON 草稿或最终 JSON、`type` |
| 表单 Agent | `vllm/Qwen/Qwen3.6-27B-FP8` | 表单 WeKnora、只读字段元数据 | JSON 草稿或最终 JSON、`type` |
| JS 增强 Agent | `vllm/Qwen/Qwen3.6-27B-FP8` | JS WeKnora、Agent 自己的校验/修复能力 | 最终 JSON 或完整 JS 文件、`type` |

模型 id、最大 token、thinking、图片大小和重试策略均是 `cordis.yml` 配置，不是代码常量。

上线前必须用同一组固定案例评测文本模型和视觉模型的 JSON 合法率、字段正确率、Hook 精确匹配率和预览成功率；模型替换后重新评测。

## 4. 中台接口

正式产品只提供中台接口，不在本项目中建设对话框、模式按钮、文件选择器或其他前端界面。调用方可以是中台现有前端、其他业务系统或自动化客户端。

接口输入包括 `mode`（`auto`、`list`、`form`、`js`）、文本说明、可选图片、可选 `.js` 文件、表名/数据源和目标平台版本。

中台接口把原始输入转发给 DSH，并将 DSH 的 `{ type, status, file }` 与平台预览结果返回给调用方。接口不读取 WeKnora、不判断 Hook、不执行 JS、不做 JSON/JS 业务校验，也不改写 Agent 输出。

DSH Web 只作为内部调试和联调入口，不作为正式产品 UI。Agent 的 RAG 片段、内部修复和子 Agent transcript 不属于中台接口协议。

```text
中台调用方
  -> 中台接口
      -> DSH 自动路由或指定 Agent
      <- { type, status, file }
  -> 平台预览接口
  <- 预览地址/标识/处理状态
```

## 5. 表单与模块 RAG

第一版选用 [`@wxg-prc-cpg/dsh-weknora`](https://github.com/Tencent/WeKnora/tree/main/packages/dsh-weknora)，它把 WeKnora 的混合检索、按文档读取和可选问答能力注册为 DSH 工具。[插件中文说明](https://github.com/Tencent/WeKnora/blob/main/packages/dsh-weknora/README_CN.md)

列表、表单和 JS Agent 各自配置固定的 `knowledgeBaseIds`，只启用生成所需的 `weknora_search` 和 `weknora_read_document`；不让模型在多个业务知识库之间自由选择，也不让任一 Agent 跨库检索。

WeKnora 负责文档切分、embedding、向量索引和检索；中台 BFF 与 DSH Host 不复制这些逻辑，也不维护 PostgreSQL、pgvector、Qdrant、Milvus 或独立 embedding 服务。

WeKnora 的 API key、base URL、tenant id 和知识库 id 由 DSH 组合配置提供。部署时固定兼容的 `dsh-weknora` 与 WeKnora 版本，导入表单、模块和 JS 三份知识库，并由 Agent 自己决定检索后的生成与修复。

## 6. JS WeKnora、文件和校验

JS 知识库导入 WeKnora 的独立知识库范围。JS Agent 使用 `weknora_search` 找到 Hook、页面类型或业务行为，再使用 `weknora_read_document` 读取完整模板上下文；中台 BFF 不读取或解释知识库内容。

JS 增强 Agent 先通过 WeKnora 检索 Hook 上下文，再由 Agent 自己判断适用模板、生成代码并执行已有校验和修复。无法确定 Hook、页面类型或挂载位置时，由 DSH 返回 `needs_input`，中台 BFF 原样转发而不尝试替代 Hook。

直接 JS 模式中，中台上传 UTF-8 `.js` 文件并接收 DSH 返回的完整增强后 JS 文件；JSON 模式的 JSON Pointer 补丁与原值检查留在 DSH 内部，不穿过中台 BFF。

本项目不新增 Ajv、Acorn、业务校验器或 Host 修复循环。JSON/JS 的校验、自动修复和 `needs_input` 由对应 DSH Agent 自己的已有能力完成；中台只检查传输协议和响应包装。

`funText` 的加密/编码算法未确认前，不启用包含 JS 的 JSON 预览提交；原始 JS 不得伪装为编码结果。

### 5.1 自动修复与用户状态

自动修复和重试次数不在本项目中新增配置；各 DSH Agent 使用其已有的内部策略。中台不观察中间补丁、不追加修复轮次，也不把 Agent 的内部校验错误转换成另一套错误协议。

用户响应不使用 `failed` 状态。`status` 和 `preview.status` 使用下列语义：

| 用户状态 | 条件 | 行为 |
| --- | --- | --- |
| `completed` / `succeeded` | 产物通过校验，平台预览已接受或完成 | 返回文件、预览标识或预览地址 |
| `processing` / `processing` | 产物通过本地校验，平台超时、暂时不可用或异步处理中 | 返回文件并进入带幂等键的后台重试；前端订阅或轮询后续预览状态 |
| `needs_input` / `needs_input` | 缺少不可安全推断的事实，例如表名、字段权限、精确 Hook、页面类型或平台编码配置 | 返回明确的补充字段，不伪造字段、Hook 或无效文件，也不调用预览接口 |

内部审计保留校验错误码、平台 HTTP 状态和重试次数，但对话界面只呈现可操作的补充信息或处理进度。

## 7. 平台 BFF 与文件预览

字段元数据和预览提交由中台 BFF 适配器处理；DSH 只通过受控输入输出接口请求所需字段元数据或交付最终文件，不直接访问平台 HTTP。

字段工具固定为只读的 `get_table_fields({ tableName, dbSource? })`，使用已认证用户、租户、数据源白名单和表白名单授权。

预览工具不向 DSH Agent 暴露。中台 BFF 仅在 DSH 返回可预览产物后调用 `submit_preview()`，提交文件类型、文件名、内容、目标平台版本和 BFF 注入的身份信息。

平台未提供预览接口协议，因此 `submit_preview()` 的 URL、认证、文件上传形式、异步轮询、成功响应和错误码以平台 OpenAPI 或真实集成样例为真源；适配器对未定义字段不做猜测。

Node 22 自带的 `fetch`、`AbortSignal` 和 `FormData` 足以实现 BFF HTTP 和 multipart 调用，不新增 axios 等第二套 HTTP 客户端。

上传图片和 JS、生成的 JSON/JS 均放入中台既有附件或对象存储；Host 使用不透明附件标识和 SHA-256 引用它们，并按配置的保留期限清理。

文件在进入模型或预览服务前校验 MIME、扩展名、大小、UTF-8 编码和恶意内容扫描结果。图片只允许已配置模型支持的格式；直接 JS 只接受 `.js`。

对话响应固定使用下列包装，`type` 由 Host 而非模型确定，且不写入平台 JSON 文件。

```json
{
  "type": "list",
  "status": "completed",
  "file": {
    "name": "generated-list.json",
    "mediaType": "application/json",
    "content": "{...}",
    "sha256": "..."
  },
  "preview": {
    "status": "succeeded",
    "platformRequestId": "..."
  }
}
```

`type` 只能是 `list`、`form` 或 `js`。

预览接口出现可重试错误时，响应保留已校验文件和 `type`，并将根级 `status` 与 `preview.status` 标记为 `processing`；后台以租户、目标平台版本和输出 SHA-256 构成的幂等键重试。

字段授权、skill、平台编码或本地校验需要用户提供事实时，响应为 `needs_input`，同时给出必填补充项；不调用平台预览接口，也不生成伪造的输出文件。

## 8. 数据、凭据和观测

### 8.1 持久化

第一版以一个 DSH Host 实例运行，使用现有 `dsh-session-persistence-sqlite` 保存 DSH session。

WeKnora 保存知识库和检索数据；DSH 使用现有 session 持久化和 telemetry 记录运行信息；本项目不复制新的 PostgreSQL 表，也不存储附件二进制。

DSH session 与 telemetry 至少记录请求标识、模式、响应 `type`、WeKnora 配置版本、字段查询标识、输出 SHA-256、预览请求标识、结果状态和时间；不新增生成审计数据库。

多副本 DSH Host、跨进程 continuable subagent 和共享 session 恢复不在第一版范围。需要水平扩展前，先补齐共享 session persistence 方案和跨实例会话路由。

### 8.2 凭据与授权

模型密钥、数据库连接、embedding 服务 token 和平台 BFF 凭据都通过 `dsh-credentials` 引用解析；`cordis.yml`、日志、工具参数和模型 prompt 中不得出现实际密钥。

字段权限和预览权限在 BFF 侧校验，`toolFilter` 只控制模型可见的工具，不被当作授权机制。

使用应用级 allow-list 限制平台 base URL、数据源、表名和可提交文件类型，禁止重定向到用户提供的 URL。

### 8.3 观测

选择当前仓库的 `dsh-session-telemetry-otel` 和 OTLP Collector 记录 trace、metric 与受控日志。

OpenTelemetry JavaScript 支持 Node.js 的 trace、metric 与 log 数据；生产环境通过 Collector 输出 OTLP 是官方建议的部署方式。[OpenTelemetry JavaScript](https://opentelemetry.io/docs/languages/js/) [OTLP exporters](https://opentelemetry.io/docs/languages/js/exporters/)

在导出前安装脱敏监听器，删除或散列用户说明、图片引用、原始 JS、JSON 内容、附件路径、平台响应体和所有 credential 形态字段。

仪表盘只聚合模式、模型、知识库版本、检索命中数、字段工具延迟、子 Agent 时长、校验失败类别、预览成功率和平台错误码。

## 9. 部署与测试

第一版使用现有 DSH Host、三个 Agent runtime 和 WeKnora 服务；图片/产物使用中台既有对象存储或附件服务，不新增 PostgreSQL、向量数据库或 embedding 服务。

Docker Compose 的生产配置使用单独覆盖文件保存环境变量、端口、重启策略和日志设置，镜像中包含应用代码而不挂载生产源码。[Docker Compose production](https://docs.docker.com/compose/how-tos/production/)

测试技术栈复用仓库的 Vitest、keyless snapshot 和 Playwright。

| 测试层 | 技术与覆盖 |
| --- | --- |
| 单元测试 | Vitest：显式/自动模式选择、路由枚举、响应 `type`、文件转发、字段查询转发和预览请求转发 |
| 组装快照 | 三个 DSH runtime 的真实入口：显式列表/表单/JS、自动路由到三种模式、图片、JSON 内 JS、上传 JS，以及 Agent 自己产生的 `needs_input` |
| BFF 集成 | Mock Service Worker 或本地 HTTP fixture：DSH 请求/响应转发、字段/预览请求、超时和平台状态映射 |
| 平台联调 | 受控测试租户：真实字段接口、真实预览接口、`funText` 编码和文件上传协议 |
| RAG 评测 | WeKnora 与 Agent 真实组合：目标知识库命中、跨库隔离、组件/属性选择和最终文件产出 |
| 安全测试 | 权限绕过、无授权表、超大/伪造 MIME 文件、提示词注入、未知 Hook、外部 URL 和日志脱敏 |

## 10. 延后或拒绝的选择

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| PostgreSQL、pgvector、Qdrant、Milvus、Elasticsearch | 拒绝 | WeKnora 已负责知识库、embedding 和检索，本项目不重复建设 RAG 基础设施 |
| 把 JS 知识库混入列表/表单 RAG | 拒绝 | 三类知识库的检索范围必须隔离；JS Agent 独立使用 WeKnora 的 JS 知识库 |
| 三个独立 DSH 服务 | 拒绝 | 增加会话、凭据、权限、重试与结果汇合的跨服务复杂度，现有 `spawn` 可隔离子 Agent |
| `dsh-workflow` 动态脚本 | 拒绝 | 固定生产顺序由 Host 服务控制，模型不应改变安全和预览提交次序 |
| 在 Host 执行生成 JS | 拒绝 | 本期只做静态解析与平台预览提交，不允许执行不可信业务代码 |
| 浏览器或 Node 侧硬编码平台 token | 拒绝 | 违反 BFF、credentials 和最小权限要求 |

## 11. 实施前置条件

1. 平台提供字段接口和预览接口的 OpenAPI、认证方式、请求/响应样例、文件协议和幂等语义。

2. 平台确认 JSON schema、`funText` 编码算法、编码密钥的归属和预览端接受的 JS 文件格式。

3. 中台确认附件存储、病毒扫描、文件保留期限、图片是否可出域到模型服务，以及用户/租户标识的传递方式。

4. 使用真实业务样例建立模型、RAG 和预览评测集，并确定可接受的生成质量、延迟和失败率。

5. 安全团队确认平台 BFF 的表级授权、审计保留期、日志脱敏规则和生产 telemetry 出口。
