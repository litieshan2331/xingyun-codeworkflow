# 星云中台 UI JSON 生成需求与 DSH 多 Agent 设计

## 1. 目标

在中台提供一个对话入口，用户输入自然语言描述、可选 UI 图片、可选 JS 文件和可选数据表信息后，系统生成一份 JSON 或增强后的 JS 文件，并提交给平台预览接口。

系统支持三种目标：模块列表 JSON、表单 JSON 与 JS 增强。

当 JSON 需要 JS 增强时，系统补齐符合星云平台真实 Hook 的 JS 代码，再输出完整 JSON；当用户上传 JS 文件时，系统直接返回增强后的 JS 文件。

中台 BFF 负责接收输入文件、把任务交给 DSH 和提交平台预览；DSH 内部的 Agent 负责生成、校验和自动修复输出文件。两侧均不执行生成的 JS，也不写数据库。

## 2. 知识库使用结论

| 知识库 | 实际内容 | 使用方式 | 运行时规则 |
| --- | --- | --- | --- |
| `星云表单设计知识库.md` | 2,253 行、55 个章节、85 个 JSON 示例；包含表单整体结构、组件 schema、全局约束和字段绑定规则 | `@wxg-prc-cpg/dsh-weknora` | 导入 WeKnora 的表单知识库，由表单 Agent 通过插件检索；全局规则由该 Agent 自己的提示词/skill 使用，不由中台校验 |
| `星云模块设计知识库.md` | 1,579 行、62 个章节、80 个 JSON 示例；包含列表组件树、查询区、表头、布局和全局约束 | `@wxg-prc-cpg/dsh-weknora` | 导入 WeKnora 的模块知识库，由列表 Agent 通过插件检索；布局和表头规则由该 Agent 自己处理，不由中台校验 |
| `星云js增强完整知识库.md` | 1,797 行、181 个细粒度 Hook、242 个 JavaScript 示例；以挂载点、参数、限制和模板组织 | `@wxg-prc-cpg/dsh-weknora` | 导入 WeKnora 的 JS 增强知识库，由 JS Agent 通过检索和文档读取获取 Hook 上下文；校验和自动修复仍由 DSH Agent 自己完成 |

表单和模块知识库的内容会随“页面类型、组件、业务字段、布局”变化，需要语义检索才能把相关章节交给模型，因此在各自 DSH Agent 内使用 RAG。

两份知识库开头的全局强制规则不能只做 RAG 文本，例如组件必填属性、默认样式、key 命名、栅格约束、列表容器关系、表头复制关系和选项兜底规则；这些规则进入列表或表单 Agent 自己的 DSH skill 和系统提示词，不在中台 BFF 重复实现。

JS 知识库的正确性取决于一个精确 Hook、函数参数、是否允许异步、返回值和 JSON 中的真实挂载位置，因此 JS Agent 通过 WeKnora 检索相关 Hook 文档并读取完整上下文，再由 Agent 自己生成和修复代码。

三份知识库在 WeKnora 中保持独立知识库范围；JS 知识库不向列表或表单 Agent 暴露。

## 3. 用户流程与功能需求

1. 中台接口支持“自动选择”“生成列表 JSON”“生成表单 JSON”“JS 增强”四种 `mode`。自动选择不是第四个业务 Agent，而是 DSH 内部使用同一个本地 Qwen 多模态模型执行一次意图识别，再转给三个既有 Agent。

2. 用户提交说明、可选 UI 图片、可选 JS 文件、可选数据表信息和目标平台版本。显式选择列表、表单或 JS 时，中台 BFF 直接转发；选择自动时，中台把 `mode: auto` 和原始输入转发给 DSH 路由步骤。

3. 自动选择时，DSH 根据用户文字、图片和上传文件类型返回 `list`、`form` 或 `js`，然后只调用对应的一个业务 Agent；不并行生成两种 JSON，也不在 BFF 中重复意图识别。

4. 自动选择无法可靠区分目标时，DSH 返回 `needs_input`，要求用户选择模式；不调用两个业务 Agent 做结果比较。

5. 当列表或表单需求涉及数据绑定、查询条件、列表列或表单字段时，选中的 Agent 必须先调用只读字段元数据工具。JS 增强模式不查询数据库字段，除非用户在同一请求中明确要求生成新的数据绑定 JSON。

6. 列表或表单 Agent 仅检索各自的 RAG 知识库。需要 JS 增强时，由 DSH 内部编排调用 JS 增强 Agent；中台 BFF 不扫描 JSON 或决定 Hook。

7. JS 增强 Agent 在 DSH 内部完成 Hook 选择、模板读取、代码生成、补丁合并、语法检查和自动修复，并返回最终 JSON 或完整 JS 文件。

8. 直接 JS 增强调用中，中台只上传原始 JS 文件与需求，并接收 DSH 返回的完整 JS 文件。JSON 内 JS 增强的中间补丁是 DSH 内部实现细节，不进入中台 BFF。

9. DSH 返回文件前完成 JSON/JS 校验、字段引用、布局、全局规则、Hook 限制和 JS 语法校验。中台 BFF 只执行认证、传输大小限制、允许的文件媒体类型和响应解码，不做业务校验或改写代码。

10. DSH 返回可预览文件后，中台预览适配器将 JSON 或 JS 文件提交到平台已有预览接口。接口返回输出文件和平台预览结果，例如预览标识、URL 或处理状态；适配器透传平台定义的结果，不推断未定义字段。DSH 返回 `needs_input` 时不调用预览接口。

11. 每个已确认目标的 DSH 响应都必须带有根级 `type` 字段：模块/列表为 `"list"`，表单为 `"form"`，直接 JS 增强为 `"js"`。自动选择完成意图识别后才写入该字段；该值由 DSH 内部编排写入，中台 BFF 只透传并校验其取值。

`type` 位于对话服务的响应包装层，不写入平台消费的列表或表单 JSON 根对象，避免改变平台 JSON schema。

```json
{
  "type": "form",
  "status": "completed",
  "file": {
    "name": "generated-form.json",
    "mediaType": "application/json",
    "content": "{...}"
  },
  "preview": {
    "status": "succeeded"
  }
}
```

```text
Explicit: request -> middle-platform BFF -> selected DSH Agent -> platform preview -> response
Auto: request -> middle-platform BFF -> DSH intent router -> one selected DSH Agent -> platform preview -> response
```

## 4. 多 Agent 与多个 DSH 的设计

不建议部署三个独立 DSH 进程。

建议部署一个 DSH Host，并在其内运行列表 Agent、表单 Agent 和 JS 增强 Agent。中台 BFF 只调用这一套 DSH 组合，不编排三个 Agent。

自动意图识别、字段查询、JS 增强、自动修复和文件校验由 DSH 内部的 `ui-codegen-orchestrator` 完成；中台 BFF 只负责请求转发、响应包装和预览提交。

DSH 内部可以通过现有 subagent seam 调用 `ctx.subagents.start('spawn')`，或使用已部署 JS Agent 的既有调用入口；这属于 DSH 自己的组合配置。

`spawn` 子 Agent 在同一进程中拥有独立 session，并不会获得父对话 transcript，适合接收经过编排器整理的独立任务。

列表 Agent 只可使用列表 WeKnora 检索和字段元数据工具；表单 Agent 只可使用表单 WeKnora 检索和字段元数据工具；JS 增强 Agent 只可使用 JS WeKnora 检索和自身已有的代码生成能力。

中台 BFF 不向 JS Agent 传递 persona、`toolFilter`、Hook 白名单或修复次数；这些策略归 DSH Agent 自己的 preset、skill 和配置所有。

字段元数据服务仍必须根据认证用户、租户和表级白名单独立授权；DSH 内部的工具可见性不替代 BFF 授权。

固定生产流水不应使用 `dsh-workflow` 的模型编写脚本。工作流脚本适合开放式编排；这里的顺序、失败处理和安全边界是产品规则，必须由普通 Host 代码确定。

建议的外置包边界如下：

- `dsh-xingyun-ui-codegen-orchestrator`：DSH 内的路由、子 Agent 调用、JS 增强、自动修复、校验和审计。
- `@wxg-prc-cpg/dsh-weknora`：DSH 的 WeKnora RAG 插件；列表、表单和 JS Agent 各自绑定一个独立知识库范围。
- `dsh-xingyun-schema`：字段元数据能力的 Service Definition、BFF Service Provider 和给列表/表单 Agent 使用的 Consumer 工具。
- `dsh-xingyun-js-knowledge`：JS 增强 Agent 对 WeKnora JS 知识库的配置与输入输出适配。
- `dsh-xingyun-preview`：中台 BFF 将 DSH 最终文件提交到平台预览接口的适配器。

这些 DSH 包应作为 DSH 侧的外置插件或组合包维护，不修改 `core/agent-loop`。中台只需要三个 DSH Agent 的输入输出接口；接入前需要确认每个 Agent 的 id、调用入口和返回 schema。

## 5. 中台接口

正式产品只提供中台接口，不在本项目中建设对话框、模式按钮、文件选择器或其他前端界面。调用方可以是中台现有前端、其他业务系统或自动化客户端。

接口接收 `mode`（`auto`、`list`、`form`、`js`）、文本说明、可选图片、可选 `.js` 文件、表名/数据源和目标平台版本。

接口将原始输入转发给 DSH；自动选择的意图识别由 DSH 完成。接口返回 DSH 的 `type`、`status`、输出文件和平台预览结果，不暴露 Agent 对话、WeKnora 片段或内部修复细节。

DSH Web 仅作为内部调试、联调和故障排查入口，不作为正式产品 UI。中台接口不读取 WeKnora、不判断 Hook、不执行 JS，也不修改 DSH 返回文件。

## 6. 字段元数据接口与权限

桌面 JS 知识库的 12.11 节给出了字段属性接口：`GET /online/cgformhead/getTablePropertyByDataSource/{tableName}`，可选查询参数为 `dbSource`。

列表和表单 Agent 只能通过中台提供的 `get_table_fields({ tableName, dbSource? })` 输入输出接口使用该能力，不能直接访问数据库、拼接任意 URL、执行 SQL 或查询数据行。

该工具必须由中台 BFF 代为调用，并强制传递用户身份、租户范围、允许的数据源和表白名单、请求超时与响应大小限制。

知识库未定义接口响应 JSON，因此实施前必须使用一个有权限的真实响应建立适配器，明确 Agent 可见的最小字段元数据，例如字段名、类型、备注、是否可空和枚举信息；不存在于真实响应中的信息不能由模型或适配器补造。

第一版要求用户显式提供 `tableName`，或使用服务端维护的已批准业务别名映射。没有精确表名时，系统应请求补充信息，不能猜测数据库表。

工具结果只返回生成 JSON 必需的脱敏元数据，绝不返回表数据、凭据或未脱敏 BFF 响应。

## 7. 三个 Agent 的输入、输出与职责

| Agent | 输入 | 可用知识/工具 | 结构化输出 | 禁止事项 |
| --- | --- | --- | --- | --- |
| 列表 Agent | 用户说明、图片、可选目标版本、已授权字段元数据 | 模块 WeKnora、字段元数据工具、按需 JS Agent | 列表 JSON 草稿及其唯一 `funText` | 不检索表单或 JS WeKnora 知识库、不猜字段 |
| 表单 Agent | 用户说明、图片、可选目标版本、已授权字段元数据 | 表单 WeKnora、字段元数据工具、按需 JS Agent | 表单 JSON 草稿及其唯一 `funText` | 不检索模块或 JS WeKnora 知识库、不猜字段 |
| JS 增强 Agent | 列表/表单 Agent 写出的 `funText` 临时 JS 文件，或中台上传的完整 JS 文件；增强需求、页面类型和可选目标版本 | JS WeKnora、Agent 自己已有的校验和修复能力 | 完整 JS 文件，以及 `type` 和可选来源信息 | 不检索列表/表单 WeKnora 知识库；不执行 JS |

MVP 中每个列表或表单草稿 JSON 只有一个 `funText`。用户明确要求 JS、Hook、事件或其他 JS 业务行为时，列表或表单 Agent 先在该字段生成原始 JS；字段去除空白后非空时，将其以 UTF-8 写入临时 `.js` 文件并且只调用一次 JS Agent。JS Agent 完成后，父 Agent 读取临时文件文本并覆盖 `funText`。用户未提出 JS 行为时，`funText` 为空字符串且不调用 JS Agent。

JS Agent 的补丁条件、自动修复和最终文件正确性由 DSH 内部负责；中台 BFF 只接受符合输出包装 schema 的最终文件。

在整个 MVP 流程中，`funText` 直接保存 JS 原始文本：列表/表单 Agent 生成原始文本，JS Agent 修改原始文本，中台和预览适配器直接传递原始文本，不做加密、压缩、Base64 或其他业务编码转换。UTF-8 只作为文件读写和 JSON 文本传输的字符集约定，不属于业务处理步骤。

## 8. 平台预览接口

所有通过 DSH 校验的输出文件都必须调用平台现有预览接口：列表和表单提交 JSON 文件，直接 JS 增强提交 JS 文件，包含 JS 的 JSON 提交编码后的最终 JSON 文件。

预览能力由 `dsh-xingyun-preview` 经中台 BFF 调用。它的输入至少包括文件类型、文件名、内容、目标平台版本和由 BFF 注入的用户/租户身份；它的输出保留平台返回的预览标识、预览地址、可下载文件或错误信息。

平台接口的 URL、认证方式、文件字段名、是否接受原始文本或 multipart、是否异步、成功响应 schema 和错误码尚未提供。适配器必须在拿到接口文档和真实集成样例后固定请求/响应 schema；在此之前不得伪造预览地址或成功结果。

预览接口暂时不可用、超时或异步处理中时，响应仍返回已通过 DSH 校验的输出文件和根级 `type`，并使用 `status: "processing"`；中台按 DSH 返回的幂等标识重试或轮询。需要表名、权限、Hook 或其他事实时，DSH 返回 `status: "needs_input"`；中台不发送文件到平台。

## 9. 校验、审计与失败处理

DSH 返回文件前至少校验：JSON 可解析且根结构符合列表或表单格式（适用时）、全局规则、key 唯一性、布局与 slot 关系、字段均来自已授权元数据（适用时）、列表表头关系（适用时）、JS 语法、Hook 参数/异步限制和文件类型。

DSH 和中台 BFF 均不执行生成的 JS；代码只交给中台预览。

每次生成保留请求标识、所选模式、响应 `type`、知识库版本和章节标识、字段查询标识、子 session 标识、输出文件指纹、预览请求标识和预览结果，以支持问题复现；Hook、校验和修复细节由 DSH Agent 自己记录。

审计记录和模型上下文不得包含凭据、表数据行或完整的原始 BFF 响应。

自动意图识别不确定、缺少表名、字段接口无权限、JS Hook 无唯一匹配或校验无法自动修复时，DSH 返回 `needs_input`，中台不调用预览接口。平台预览暂时不可用时返回 `processing`，并保留已校验的输出文件供后续处理。

## 10. 验收标准

- 中台接口接受 `auto`、`list`、`form`、`js` 四种 `mode`；显式模式直接调用对应 Agent，自动模式由 DSH 意图路由决定。
- 每个已确认目标的接口响应均含根级 `type`：列表/模块为 `list`、表单为 `form`、直接 JS 增强为 `js`；该字段不进入平台 JSON 文件。
- 自动选择不确定时返回 `needs_input`，要求调用方补充模式；接口不并行调用两个业务 Agent。
- 数据绑定的列表和表单在输出字段前调用字段元数据工具，并拒绝未授权字段。
- 表单和模块 RAG 相互隔离；每次生成都应用固定全局规则和 JSON 骨架。
- 中台 BFF 对 JS 增强只转发输入和输出；Hook 匹配、补丁和自动修复均由 DSH Agent 完成。
- 通过 DSH 校验的 JSON 或 JS 文件都会调用平台预览接口；平台暂时不可用时返回 `processing` 和输出文件，需要用户补充事实时返回 `needs_input`。
+ 返回给预览端的文件由 DSH 完成适用的结构、字段、关系和 JS 语法校验；中台 BFF 不修改文件内容。
- 关键路径拥有无密钥的组装快照：显式列表/表单/JS、自动选择到三种模式、自动选择歧义、上传 JS 的增强场景，以及字段授权 `needs_input`、未知 Hook、修复耗尽和平台预览 `processing` 场景。
- 审计可复现知识来源、字段查询、Hook 选择和预览请求，但不泄露凭据或业务数据行。

## 11. 实施前必须确认的事项

1. 字段属性接口的真实响应 JSON、认证方式、租户与表级权限规则。

2. 平台预览接口的 URL、认证方式、输入文件协议、JSON/JS 文件字段名、同步或异步语义、成功/失败响应 schema、预览地址有效期和重试幂等键。

3. 中台预览所需 JSON 的精确 schema、列表与表单的版本兼容范围，以及预览接口是否直接接受原始 `funText` 文本。

4. 图片和上传 JS 是否允许发送给路由和生成模型，以及文件保存、脱敏和保留期限。

5. 业务方是否愿意在第一版提供精确 `tableName`；若否，需要先建设受权限保护的业务别名解析服务。

6. 三份知识库的维护人、发布版本、导入频率和回归样例；每次导入都应更新来源指纹并运行回归测试。
