# Agent Note: 通过固定的直接入口脚本运行星云模式

Status: implemented

[English](2026-08-26-xingyun-direct-mode-runtimes.md) | 中文

## 问题

通用的星云命令从请求数据中选择 runtime，尽管调用方已经知道目标路由。共享宿主 adapter 随后解释 Agent 文本和产物，重复了本应属于 Agent runtime 的业务响应决策，并遮蔽了对模型原始输出的直接检查。

## 决策

`run-list-agent.ts`、`run-form-agent.ts` 和 `run-js-agent.ts` 分别通过官方 DSH TypeScript SDK 启动一个明确的 Cordis runtime。每个脚本创建隔离工作区、准备 runtime 输入、等待 SDK 活动完成、读取预期临时产物、写出一个包含 `agentResponse` 与文件元数据/内容的 JSON 对象，然后删除工作区。

list/form 脚本将 `XINGYUN_JS_AGENT_COMMAND` 和 `XINGYUN_JS_AGENT_ARGS` 提供给子进程。它们配置的 `dsh-subagent-dsh-sdk` provider 在 `funText` 非空时拥有可选的 JS 委托；入口脚本不自行调用 JS Agent。

脚本不解析或校验 Agent 业务响应、生成 JSON、JS 语法、字段、摘要或完成状态。调用方得到原样的最终 Agent 文本和临时产物内容，并自行处理。

## 考虑过的替代方案

**保留一个按请求模式选择 runtime 的 `run-xingyun.ts` 命令。** 否决，因为面向调用方的路由已经标识目标 runtime，该命令增加了路由入口却没有增加能力。

**共享一个 list/form runtime 和文件 adapter。** 否决，因为入口脚本有意保持与直接 JS 脚本相同的自包含适配形式。

**在入口脚本中校验业务响应和生成产物。** 否决，因为这些脚本只负责驱动 Agent runtime 并返回输出；业务校验属于配置的 Agent 或拥有下一应用步骤的调用方。

**从 list/form 脚本直接启动 JS Agent。** 否决，因为 list/form Cordis 组合已经通过官方 SDK provider 拥有 JS 子 Agent，包括其模型路由、环境、生命周期和 `funText` 合并。

## 后果

每个调用方选择一个固定入口，并得到原始 Agent 文本和临时输出文件内容。返回文件本身不能证明请求的生成或增强已经成功；需要 completed 状态保证的消费方必须自行增加校验。list/form 运行仍可在内部创建嵌套 JS runtime，而不向入口脚本暴露该进程边界。
