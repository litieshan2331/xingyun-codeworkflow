# 阶段一：星云知识库检索测评方案

## 1. 目标

阶段一只验证单次知识库工具调用是否能检索到高质量、与问题相关的分块（chunk），并抑制该知识库内的误召回。本阶段不生成页面 JSON 或 JavaScript，也不评估代码是否正确使用检索内容。

阶段一的结果是一个稳定的检索基线，为后续代码生成和 Faithfulness 测评提供输入。检索基线未达标时，不进入下一阶段。

## 2. 被测范围

测试覆盖 form、list 和 js 三个单知识库工具；`knowledge_base` 表示该问题的目标知识库，用于分组统计。form+js 和 list+js 需要多次工具调用，不纳入本阶段单次调用数据集。

Agent 使用与生产环境相同的 WeKnora 检索配置。`xingyun-auto` 和 `xingyun-js` 只作为实际调用入口；本阶段不评价它们的页面路由、JS 触发、文件修改或最终回复格式。

三个知识库使用同一版本的内容。评分唯一使用 WeKnora 原始搜索结果的 `data[].id` 作为子 chunk ID；`knowledge_id` 是文档 ID，`chunk_index` 是文档内序号，二者都不能单独算作召回。评测数据中的 `reference_context_ids` 必须直接保存原始子 chunk `id`，不得拼接 `knowledge_id`、`chunk_index` 或自定义章节编号。

## 3. 测试集规模

首版开发集使用 120 个案例：form 单库 30 个、list 单库 30 个、js 单库 60 个。查询按路由顺序排列，并用 `route_group` 和 `query_type` 标记覆盖范围；js 单库保留 20 个同库多跳案例用于验证最终上下文容量。

问题覆盖以下内容：

- 组件、字段或 API 的使用约束；
- 全局禁止事项、兜底规则或布局规则；
- 典型 Hook、回调或参数配置；
- 同一事实的不同业务表达和章节标题表达。

阶段一的问题应模拟真实知识查询，但不要求模型生成代码。运行器先按 WeKnora 查询理解模板执行单轮改写，再发送改写后的问题；问题应保留组件、字段和 API 等具体检索词，避免把模型记忆中的答案误当作检索结果。

## 4. 最小案例格式

测试集文件为 `datasets/retrieval.v1.jsonl`，每行一个案例：

```json
{
  "case_id": "form-001",
  "knowledge_base": "form",
  "search_knowledge_bases": ["form"],
  "target_knowledge_bases": ["form"],
  "route_group": "form-single",
  "query_type": "single_fact",
  "query": "根据星云表单知识库，下拉框没有配置选项时应遵守什么规则？",
  "reference_context_ids": ["wk-chunk-8f31..."]
}
```

字段约定：

- `case_id`：全局唯一的案例 ID；
- `knowledge_base`：只能是 `form`、`list` 或 `js`；
- `search_knowledge_bases`：本次请求实际搜索的逻辑知识库，当前必须只有 `knowledge_base`；
- `target_knowledge_bases`：该问题允许作为正确证据的知识库集合，当前必须只有 `knowledge_base`；
- `route_group`：固定为 `form-single`、`list-single` 或 `js-single`，用于按单工具路由汇总；
- `query_type`：用于定位查询类型；所有案例均为正常业务查询，命中质量由参考 ID 和实际检索内容判断；
- `query`：发送给 Agent 的检索问题；
- `reference_context_ids`：人工标注的最小相关 chunk 原始 ID 集合。

阶段一不要求 `reference_answer`、`generated_code` 或 `unambiguous` 字段。参考答案和代码要求属于后续 Faithfulness 测评。

## 5. 人工标注

标注者阅读对应知识库的源文档，为每个问题选择回答所需的最小 `reference_context_ids`。如果一个问题需要两个章节共同支撑，则两个 ID 都必须列出；与问题主题相似但不能支撑答案的分块不得列入参考集。

两个标注者独立完成全部 120 个案例。ID 集合不一致时由领域负责人裁决，并记录裁决后的集合。知识库文档或分块发生变化时，重新核对受影响案例，不得直接沿用旧 ID 集合。

## 6. 运行结果格式

运行器将结果写入 `runs/<run-id>.jsonl`，每行至少包含：

```json
{
  "case_id": "form-001",
  "query": "原始用户问题",
  "rewritten_query": "用于检索的改写问题",
  "rewrite_applied": true,
  "rewrite_error": null,
  "retrieval_hits": [
    {
      "retrieval_hit_id": "wk-child-chunk-8f31...",
      "retrieved_context": "Agent 实际看到的文本",
      "parent_chunk_id": "wk-parent-chunk-7c20..."
    }
  ],
  "status": "completed",
  "error": null
}
```

运行器先以无历史、无图片和无附件的输入执行一次 WeKnora 风格查询改写，再对同一个知识库调用两次检索：`hybrid-search` 返回 RRF 后、Rerank 前的候选集合，`knowledge-search` 返回 Rerank 和最终合并后的上下文集合。`query` 保留原始用户问题，`rewrite_applied` 表示改写文本是否变化，`rewrite_error` 记录改写失败后的原问题回退原因。`candidate_retrieval_hits` 用于 Recall，`final_retrieval_hits` 用于父块 Precision；每个命中元素包含 `retrieval_hit_id`、`retrieved_context` 和审计用的 `parent_chunk_id`。

运行器不设置本地命中数量上限，完整记录 RRF 后、Rerank 前的候选结果和 Rerank 后的最终结果。候选结果用于 Recall，最终结果用于父块 Precision。评测脚本不会再次截断；候选集数量由 `embedding_top_k`、向量阈值和关键词阈值控制，最终结果数量由 `rerank_top_k`、Rerank 阈值、重排序和去重控制。

WeKnora 先在向量检索和关键词检索通道应用 `vector_threshold`、`keyword_threshold`，再执行 RRF 融合；这两个阈值属于候选 Recall 阶段。RRF 后才进入 Rerank，`rerank_threshold` 和 `rerank_top_k` 影响最终模型上下文，因此只用于父块 Precision。

WeKnora 返回的 `chunk_type=summary` 是文档摘要，不是原始子 chunk。本阶段运行器会过滤这类结果；它们不参与 Recall、Precision 或父块指标。

## 7. 指标

每个案例先计算 ID 交集：

```text
candidate_hits = unique(candidate_retrieval_hits[].retrieval_hit_id) ∩ reference_context_ids
child_recall = |candidate_hits| / |reference_context_ids|
parent_recall = |candidate_parent_ids ∩ reference_parent_ids| / |reference_parent_ids|
parent_precision = |final_parent_ids ∩ reference_parent_ids| / |final_parent_ids|
```

空结果按以下规则处理：参考集非空而实际结果为空时 Recall 和 Precision 均为 0；参考集和实际结果都为空的案例不纳入测试集。

评分器按单知识库案例计算全局宏平均，并按目标 `knowledge_base` 分组。子块 Recall/Precision 的分母是该案例实际返回的全部结果；父块 Recall/Precision 先将参考子块映射到 chunk 清单的 `parent_chunk_id`，没有父块时以子块自身为上下文单元，再与实际 `parent_chunk_id` 比较。

如果 WeKnora 返回重复的原始 chunk ID，评分器先去重再计算；同一文档的多个 chunk 按各自原始 ID 计数。文档级和分块级结果不得在同一运行中混用。

## 8. 调优顺序

### 8.1 先调 Recall

使用开发集调节问题表达、chunk 切分、候选 `embedding_top_k`、查询改写和标题信息，优先保证每个单知识库工具中的所有参考 ID 能被召回。此阶段允许返回较多候选分块。

### 8.2 再调 Precision

在 Recall 达到 0.90 后，继续使用开发集调节每个单知识库工具的全局 `rerank_top_k`、相似度阈值、重排序和去重，逐步减少无关分块。调节后 Recall 仍必须保持不低于 0.90。

### 8.3 最后用冻结集确认

将案例划分为开发集和冻结集。开发集用于调参，冻结集只用于最终验证，不用于修改检索配置。冻结集的总体指标和三个知识库分组指标都达到门槛，阶段一才算完成。

## 9. 实施步骤

1. 确认三个 WeKnora 知识库 ID，并记录知识库、文档和分块版本。
2. 创建 120 个案例并完成双人标注，生成 `datasets/retrieval.v1.jsonl`。
3. 实现运行器，保存每个案例的原始问题、改写问题、实际 ID 和完整检索文本。
4. 实现单知识库工具结果的 ID Recall、ID Precision、父块指标和按路由分组的报告。
5. 用开发集先调 Recall，再在保持 Recall 的条件下调 Precision。
6. 后续新增冻结集并运行最终基线，保存报告和配置版本。

建议的最小命令为：

```text
python scripts/run_cases.py --dataset datasets/retrieval.v1.jsonl --out runs/<run-id>.jsonl
python scripts/score_retrieval.py --dataset datasets/retrieval.v1.jsonl --run runs/<run-id>.jsonl --chunk-inventory datasets/chunks.v1.jsonl --out reports/<run-id>.json
```

## 10. 阶段一输出

阶段一至少输出：测试集文件、知识库版本记录、运行结果文件、子块与父块的总体 Recall/Precision、各知识库分组结果、不可评分案例数、失败案例的参考 ID 与实际 ID，以及本次使用的检索配置。

阶段一通过后，保留相同的 `case_id` 和 `reference_context_ids`，再为代码生成案例增加 `source_code`、`expected_code_requirements` 和 `generated_code` 字段，进入 Faithfulness 测评。阶段一不对这些字段作任何假设。

## 11. 不在阶段一内的内容

页面类型路由、JS 策略、工具调用顺序、页面 JSON Schema、文件修改范围、图片理解、代码语法、代码执行、Faithfulness、延迟和成本均不属于阶段一。
