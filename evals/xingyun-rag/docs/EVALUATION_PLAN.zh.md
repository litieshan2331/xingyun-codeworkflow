# 星云 RAGAS 测评 MVP 方案

## 1. 目标与范围

本方案只验证星云 Agent 的知识库检索和知识依据质量，首版报告子 chunk 的 Recall/Precision、父上下文块的 Recall/Precision 和 Faithfulness。

被测入口使用 [`examples/xingyun-web`](../../examples/xingyun-web/) 中实际配置的 WeKnora 工具；阶段一只评估一次工具调用，覆盖 form、list、js 三个单知识库范围，三份 Markdown 作为人工标注依据。form-js 和 list-js 属于 Agent 的多次工具调用行为，不在本阶段合并成一次检索。页面路由、JS 触发策略、文件路径、JSON Schema、工具顺序、图片理解和延迟统计不属于本 MVP 的评分指标，留待后续版本。

本方案中的“检索结果”是 WeKnora 返回的文档或分块 ID 及其文本；“回答”是从 Agent 生成页面 JSON 中提取的设计决定摘要，不直接把文件协议包装对象交给 Faithfulness。

## 2. 指标定义与暂定门槛

| 指标 | 含义 | 计算方式 | 暂定门槛 |
|---|---|---|---:|
| 子 chunk Recall | RRF 后、Rerank 前候选子 chunk 中参考子 chunk 的比例 | `候选集命中的参考子 ID 数 / 参考子 ID 总数` | ≥ 0.90 |
| 父块 Recall | RRF 后、Rerank 前候选子 chunk 映射出的参考父块比例 | `候选集命中的参考父块数 / 参考父块总数` | 先记录基线 |
| 父块 Precision | Rerank 和最终合并后模型上下文中的参考父块比例 | `最终命中的参考父块数 / 最终父块总数` | ≥ 0.80 |
| Faithfulness | Agent 的知识库驱动结论是否能由实际检索文本推出 | RAGAS `Faithfulness`，范围 0 到 1 | ≥ 0.90（仅无歧义案例） |

三个指标均按单个案例计算，再报告宏平均；同一文档的多个分块按分块 ID 计数。候选 Recall 使用候选命中集合，最终父块 Precision 使用最终上下文集合。父块指标将每个参考子 chunk 映射到 `parent_chunk_id`，没有父块时以子 chunk 自身作为上下文块。若 WeKnora 只提供文档 ID，则本基准不能评分，不得混用文档粒度。

Recall 使用 RRF 后、Rerank 前的候选集合；Precision 使用 Rerank 后最终父块上下文集合。`vector_threshold`、`keyword_threshold` 和 `embedding_top_k` 调整候选 Recall；`rerank_threshold`、`rerank_top_k` 和 MMR 调整最终父块 Precision。参考集必须覆盖回答所需的最小相关子 chunk；不能根据本次 Agent 实际返回结果反向补标，否则会把漏召回误判为正确。

Faithfulness 只针对能由知识库事实判断的设计决定评分，例如组件属性、布局约束、字段规则和 Hook 写法。用户直接指定的字段名、业务名称或文件路径不作为知识库声明，也不参与该分数。

RAGAS 官方将 Context Recall、Context Precision 和 Faithfulness 用于 RAG 评估；本项目使用 ID 交集计算确定性的检索指标，再使用 RAGAS 评估生成结论的依据性。[RAGAS 指标目录](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/)

## 3. 最小测试集

首版开发集使用 120 个案例：form 单库 30 个、list 单库 30 个、js 单库 60 个。数据按路由顺序排列，并显式标注查询类型；仅 JS 单库包含 20 个同库多跳案例，使用 5–6 个参考 chunk。

案例应覆盖“组件或字段约束”“全局禁止或兜底规则”“典型 Hook/API 用法”三类内容。首版不要求图片案例；图片加入后应另行增加视觉输入和图片证据字段，不能直接混入文本基准。

每个案例使用一行 JSONL，最小字段如下：

```json
{
  "case_id": "form-001",
  "preset": "xingyun-auto",
  "query": "表单中的下拉框没有选项时应如何配置？",
  "knowledge_base": "form",
  "search_knowledge_bases": ["form"],
  "target_knowledge_bases": ["form"],
  "route_group": "form-single",
  "query_type": "single_fact",
  "reference_context_ids": ["form-doc-02#chunk-04"],
  "reference_answer": "需要遵守选项类组件的兜底规则。",
  "unambiguous": true
}
```

字段约定：`case_id` 唯一；`preset` 是实际运行的 preset；`query` 是发送给工具的原始用户问题；`knowledge_base` 取 `form`、`list` 或 `js`，表示该案例的目标知识库；`search_knowledge_bases` 和 `target_knowledge_bases` 当前都只包含该知识库；`route_group` 标识 `form-single`、`list-single` 或 `js-single` 分组；`query_type` 用于定位查询覆盖；`reference_context_ids` 是人工确认的相关原始子 chunk ID；`reference_answer` 是用于检查依据的简短参考答案；`unambiguous` 为 `true` 时该案例才计入 Faithfulness 门槛。

运行结果另存为 `runs/<run-id>.jsonl`，每行至少包含 `case_id`、`candidate_retrieval_hits`、`final_retrieval_hits`、`status` 和 `error`。候选命中用于子 chunk Recall 和父块 Recall；最终命中用于父块 Precision。每个命中元素包含 `retrieval_hit_id`、`retrieved_context` 和审计用的 `parent_chunk_id`；`response` 是从最终页面 JSON 投影出的设计决定摘要。

`chunk_type=summary` 是 WeKnora 生成的文档摘要，不属于原始 chunk。运行器会在写入评分运行结果前过滤 summary，因此该结果不影响本阶段指标。

## 4. 人工标注规则

标注者先阅读三份知识库源文档，再为每个案例填写目标知识库和最小充分的 `reference_context_ids`、`reference_answer`。搜索范围固定为单个 form、list 或 js 工具；`target_knowledge_bases` 也只包含该知识库。form-js 和 list-js 的多次工具调用不在本阶段数据集中。

两个标注者独立标注全部 120 个案例；ID 集合不一致的案例由领域负责人裁决。至少抽取 12 个案例复核 `reference_answer` 是否只包含知识库事实，并确认 `unambiguous` 的判断。

知识库版本发生变化时，重新生成 manifest 并复核受影响案例；不得将不同版本的 ID 集合直接比较。manifest 最小字段为 `knowledge_base`、`document_id`、`chunk_id`、`content_hash` 和 `source_section`。

## 5. 运行流程

1. 固定 DSH revision、preset 配置、WeKnora 三个知识库 ID、查询改写模型名称和 RAGAS 版本；当前 Python 环境锁定 `ragas==0.3.9`。
2. 校验 `retrieval.v1.jsonl` 的必填字段、ID 唯一性和知识库取值。
3. 对每个案例先调用与 WeKnora `QUERY_UNDERSTAND` 阶段一致的查询改写模型，再使用改写结果对单个知识库发起一次 search 工具调用；原始问题和改写问题都写入运行结果。
4. 从 DSH Session Event 或等价的运行导出中提取 WeKnora 返回的 ID 和完整文本。无法获得完整检索文本的案例标记为不可评分，不记为 0 分。
5. 从最终页面 JSON 提取知识库驱动的设计决定摘要，保存为 `response`；只保存必要字段，避免把路径、状态等协议字段混入语义评分。
6. 先计算每个单知识库工具结果下的子 chunk 与父块 Recall/Precision，再对有完整上下文且 `unambiguous=true` 的案例运行 RAGAS `Faithfulness`。
7. 汇总宏平均、案例数、不可评分数和失败案例；同时按 `knowledge_base` 分组，任何知识库分组低于门槛都不能被总体平均掩盖。

## 6. 最小实现拆分

`evals/xingyun-rag` 首版只需要以下文件：`datasets/retrieval.v1.jsonl`、`datasets/chunks.v1.jsonl`、`datasets/kb-manifest.v1.json`、`scripts/discover_chunks.py`、`scripts/run_cases.py`、`scripts/score_retrieval.py`、`tests/` 下的相应测试和 `README.md` 的运行说明。运行器负责调用 WeKnora 并保存结果；评分器负责子 chunk/父块集合交集和报告；数据测试只检查字段与类型，不验证模型质量。

建议的执行命令为：

```text
python scripts/run_cases.py --dataset datasets/retrieval.v1.jsonl --out runs/<run-id>.jsonl
python scripts/score_retrieval.py --dataset datasets/retrieval.v1.jsonl --run runs/<run-id>.jsonl --chunk-inventory datasets/chunks.v1.jsonl --out reports/<run-id>.json
pytest tests
```

真实模型和 WeKnora 凭据只从评测环境读取，不写入数据集、运行记录或报告。为便于复现，报告记录模型、配置、知识库 manifest、运行时间和评分器版本。

## 7. 通过标准与输出报告

开发集用于比较 WeKnora 的 `embedding_top_k`、`rerank_top_k`、阈值和重排序配置；不作为最终发布验收集。运行器不再设置本地结果数量上限，完整记录服务端返回结果。MVP 通过条件将在独立冻结集建立后确定：所有确定性输入校验通过；总体子 chunk Recall ≥ 0.90；总体子 chunk Precision ≥ 0.80；`unambiguous=true` 案例的 Faithfulness ≥ 0.90；并且 `form`、`list`、`js` 三个知识库分组均达到对应子 chunk 门槛。父块指标先作为诊断基线记录，审批后再设独立门槛。

报告至少包含子 chunk 和父块指标均值、每个知识库分组值、样本数、不可评分数、每个失败案例的 `case_id`、实际 ID、参考 ID 和 Faithfulness 评语。报告不输出 API key 或未经批准的完整知识库内容。

门槛是首版暂定值。完成 120 个开发案例的第一次基线后，审批者可以调整案例数量或门槛；调整必须同时更新本文件和 `retrieval.v1.jsonl` 的版本号。

## 8. 后续扩展

策略遵从、路由/JS F1、工具调用准确率、JSON Schema、文件归属、图片理解、延迟和成本不在本 MVP 内。后续扩展应复用本方案的 `case_id`、知识库 manifest 和运行结果格式，并新增独立指标，不改变三个 RAGAS 指标的定义。
