# Agent Note: 通过一个自动 Agent 生成星云页面

Status: implemented

[English](2026-08-27-xingyun-auto-single-agent.md) | 中文

## 问题

固定的列表和表单入口要求调用方在请求进入 harness 前选择页面类型。一些调用方需要一个自动页面生成端点，由它分类请求页面，并决定是否应在 `funText` 中包含 JavaScript 行为。

## 决策

`auto-agent.cordis.yml` 挂载一个 Agent runtime，并注册三个独立前缀的 WeKnora 工具组：`auto_list_kb`、`auto_form_kb` 和 `auto_js_kb`。Agent 根据 instruction 和可选图片将请求分类为 list 或 form，只检索选中的页面类型知识库，并且只有用户明确提出 JavaScript、Hook、事件或校验行为时才检索 JS 知识库。它将最终页面 JSON 写入提供的 `outputPath`。

`run-auto-agent.ts` 创建隔离工作区、提供该 `outputPath`、将可选图片复制到工作区、通过官方 DSH TypeScript SDK 驱动 runtime，并返回最终 Agent 文本和临时生成文件内容。它不注册或调用 subagent，不解析业务响应字段，也不校验生成内容。

## 考虑过的替代方案

**复用已删除的根 Agent 和子 runtime。** 否决，因为自动页面分类和生成在一个拥有所需知识工具的 Agent 内完成，避免模型到模型的交接和子进程链路。

**挂载一个合并的 WeKnora 工具组。** 否决，因为独立前缀让 Agent 明确选择页面知识库，并在请求不需要 `funText` 行为时不使用 JS 知识库。

**始终检索 JS 知识库。** 否决，因为没有 JavaScript 行为的请求需要空 `funText`；不必要的检索会消耗上下文并可能引入无关实现细节。

**在入口脚本中校验生成 JSON。** 否决，因为直接脚本只驱动 Agent 并暴露原始文本和文件产物；调用方拥有下一步校验。

## 后果

自动端点只生成 list 或 form 页面产物，不增强既有的独立 JS 文件。自然语言最终响应和生成文件会一起返回，宿主不计算完成状态。需要验证页面类型、schema 或成功状态的调用方必须自行校验返回产物。
