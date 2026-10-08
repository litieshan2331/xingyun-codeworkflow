# 星云检索测评

本目录测量星云 Agent 单次知识库工具调用的 RAG 检索质量，不生成页面 JSON 或 JavaScript。每条测试问题只绑定一个知识库，记录原始问题、WeKnora 风格查询改写结果、参考子 chunk ID 和查询类型，便于定位 Recall 与 Precision 问题。

## 数据集分布

当前数据集为 `datasets/retrieval.v1.jsonl`，共 120 条，严格按以下顺序排列：

| 行号范围 | `route_group` | 检索范围 | 案例数 | 主要目的 |
| --- | --- | --- | ---: | --- |
| 1–30 | `form-single` | `form` | 30 | form 单库检索 |
| 31–60 | `list-single` | `list` | 30 | list 单库检索 |
| 61–120 | `js-single` | `js` | 60 | js 单库检索；前 40 条按章节分类，后 20 条验证 5–6 个 chunk 的 JS 多跳 |

`knowledge_base`、`search_knowledge_bases` 和 `target_knowledge_bases` 在当前版本都只包含同一个知识库。每个案例对应一次工具调用，不把 form+js 或 list+js 作为单次检索案例。

## 查询字段

每行至少包含以下字段：

```json
{
  "case_id": "form-single-001",
  "knowledge_base": "form",
  "search_knowledge_bases": ["form"],
  "target_knowledge_bases": ["form"],
  "route_group": "form-single",
  "query_type": "constraint",
  "query": "Stylefile 的默认边框规则是什么？",
  "reference_context_ids": ["当前清单中的原始子 chunk ID"]
}
```

`query_type` 用于定位查询意图：`single_fact` 是单事实，`constraint` 是配置约束，`layout` 是布局，`multi_chunk` 需要多个 chunk，`visual_layout` 是视觉布局规则，`state_props`、`form_callback`、`flow_callback`、`tool`、`module_js`、`boundary` 是 JS 分类。所有查询均为正常业务问题，命中质量由评分报告中的参考 ID、实际 ID 和上下文内容判断。

## 各路由的查询覆盖

### form 单库：`form-single-001` 至 `form-single-030`

覆盖 Stylefile 边框、选项兜底、审批意见、默认字段、formdeploy、ButtonDisplay、tableHeader、RowCol、Tabspane、SubTable、Modular、ButtonContainer、ButtonLayout、Input、TextArea、InputNumber 和 DatePicker 等正常查询主题。

### list 单库：`list-single-001` 至 `list-single-030`

覆盖全局规则、SearchContainer、序号列、DatePicker、选项组件、quotaJoin、name 语义、moduledeploy、CustomAction、modelJson、ToolHeader、ToolTable、布局容器、按钮、图表、ToolTree、ToolFileTree、ToolListShow 和 ToolCardShow 等正常查询主题。

### JS 单库：`js-single-001` 至 `js-single-060`

JS 案例按固定顺序排列：

| 编号 | 分类 | 数量 | 覆盖内容 |
| --- | --- | ---: | --- |
| `js-single-001`–`005` | `state_props` | 5 | state、props、this、tool/form/flow 关系 |
| `js-single-006`–`015` | `form_callback` | 10 | 表单取值、赋值、初始化、保存和动态权限 |
| `js-single-016`–`025` | `flow_callback` | 10 | 流程参数、发送、已阅、选人、作废和按钮回调 |
| `js-single-026`–`030` | `tool` | 5 | axios、dayjs、decimal、confirm 和工具总览 |
| `js-single-031`–`035` | `module_js` | 5 | 列表渲染、打印、列编辑和保存回调 |
| `js-single-036`–`040` | `boundary` | 5 | Markdown 参数边界、状态字段混淆、表单/模块路由、归档和上传 API 区分 |
| `js-single-041`–`060` | `multi_hop` | 20 | 每题 5–6 个 JS chunk，验证多步骤回调、工具调用和状态传递 |

`js-single-036` 至 `040` 覆盖参数位置、运行时状态、`contentType`、归档和上传回调等边界主题的正常查询。

## 评分规则

子 chunk Recall 使用 RRF 后、Rerank 前的 `candidate_retrieval_hits`；候选子块映射到 `parent_chunk_id` 后计算父块 Recall。最终模型上下文的 `final_retrieval_hits` 只用于计算父块 Precision。每个案例只统计一个知识库工具返回的结果。

`target_knowledge_bases` 与 `search_knowledge_bases` 在当前版本均只有一个知识库，避免把一次工具调用误当成跨库合并检索。

WeKnora 的 `vector_threshold` 和 `keyword_threshold` 先在向量、关键词检索通道中筛选候选，再由 RRF 融合；它们属于候选 Recall 阶段。`rerank_threshold` 和 `rerank_top_k` 在候选之后控制最终上下文，属于父块 Precision 阶段。

多跳案例的 `reference_context_ids` 必须包含同一知识库内回答所需的完整证据链，而不是只记录其中一个标题 chunk。JS 多跳案例使用 5–6 个参考 chunk。调节向量/关键词候选配置时观察候选 Recall；调节 `rerank_top_k` 或 `rerank_threshold` 时观察父块 Precision。最终阶段不计算 Recall，后续 Faithfulness 负责验证最终上下文是否足以支撑回答。

## 运行命令

根目录 `.env` 提供 WeKnora 地址、密钥和三个知识库 ID。更新任一知识库后必须重新采集 chunk 清单并重新核对参考 ID：

```powershell
cd D:\Project_Zy\deepseek-harness\evals\xingyun-rag

.\.venv\Scripts\python.exe scripts\discover_chunks.py `
  --out datasets\chunks.v1.jsonl `
  --manifest-out datasets\kb-manifest.v1.json

.\.venv\Scripts\python.exe scripts\run_cases.py `
  --dataset datasets\retrieval.v1.jsonl `
  --out runs\single-kb-rewrite-rerank3.jsonl

.\.venv\Scripts\python.exe scripts\score_retrieval.py `
  --dataset datasets\retrieval.v1.jsonl `
  --run runs\single-kb-rewrite-rerank3.jsonl `
  --chunk-inventory datasets\chunks.v1.jsonl `
  --out reports\single-kb-rewrite-rerank3.json
```

`run_cases.py` 默认执行一次无历史单轮查询改写，然后对同一个知识库调用两次检索：`hybrid-search` 取得 RRF 后、Rerank 前的候选结果，`knowledge-search` 取得 Rerank 和最终合并后的结果。运行结果保存 `candidate_retrieval_hits` 和 `final_retrieval_hits`；前者用于 Recall，后者用于父块 Precision。改写请求使用 WeKnora 查询理解阶段相同的温度 `0.3`、最大输出 `150`，并关闭 vLLM thinking。改写服务默认读取根目录 `.env` 的 `VLLM_BASE_URL`、`VLLM_API_KEY`，模型默认使用 `Qwen/Qwen3.6-27B-FP8`，可用 `XINGYUN_REWRITE_MODEL` 或 `--rewrite-model` 覆盖。`--no-rewrite` 只用于对照实验。

运行器不设置本地结果数量上限，会原样记录两个接口返回的全部文本 chunk。因此候选 Recall 只受 WeKnora 的 `embedding_top_k`、向量阈值和关键词阈值影响；最终父块 Precision 受 `rerank_top_k`、Rerank 阈值、重排序和去重影响，不会被评测脚本再次截断。

本阶段只评分 WeKnora 原始文本 chunk。服务端返回的 `chunk_type=summary` 是文档摘要，不是原始 chunk，运行器会过滤掉，不进入 Recall、Precision 或父块指标。

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
