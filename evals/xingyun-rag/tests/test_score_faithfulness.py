"""Faithfulness 输入使用实际回答和完整最终上下文。"""

import json

import pytest

from scripts import score_faithfulness as scoring


def test_samples_use_final_context_and_actual_answer():
    case = {"case_id": "c1", "query": "问题", "knowledge_base": "form", "unambiguous": True}
    run = {
        "status": "completed",
        "response": "实际回答",
        "candidate_retrieval_hits": [{"retrieved_context": "候选文本"}],
        "final_retrieval_hits": [{"retrieved_context": "最终文本"}],
    }
    samples, skipped = scoring._build_samples([case], {"c1": run})
    assert samples[0]["retrieved_contexts"] == ["最终文本"]
    assert samples[0]["response"] == "实际回答"
    assert skipped == []


@pytest.mark.parametrize("hits", [[], [{"retrieved_context": "文本", "context_truncated": True}], [{"retrieved_context": "有效"}, {}]])
def test_incomplete_context_is_unscored(hits):
    case = {"case_id": "c1", "query": "问题", "unambiguous": True}
    run = {"status": "completed", "response": "回答", "final_retrieval_hits": hits}
    samples, skipped = scoring._build_samples([case], {"c1": run})
    assert samples == []
    assert skipped[0]["reason"] == "最终检索文本缺失、不完整或被截断"


def test_reference_answer_does_not_replace_missing_response():
    case = {"case_id": "c1", "query": "问题", "unambiguous": True, "reference_answer": "参考答案"}
    samples, skipped = scoring._build_samples([case], {"c1": {"status": "completed"}})
    assert samples == []
    assert skipped[0]["reason"] == "运行结果缺少 response"


def test_invalid_scores_are_excluded_from_report(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.jsonl"
    run = tmp_path / "run.jsonl"
    out = tmp_path / "report.json"
    dataset.write_text(json.dumps({"case_id": "c1", "query": "问题", "unambiguous": True}) + "\n", encoding="utf-8")
    run.write_text(json.dumps({"case_id": "c1", "status": "completed", "response": "回答", "final_retrieval_hits": [{"retrieved_context": "证据"}]}) + "\n", encoding="utf-8")
    monkeypatch.setattr(scoring, "_score", lambda samples: [float("nan")])
    monkeypatch.setattr("sys.argv", ["score", "--dataset", str(dataset), "--run", str(run), "--out", str(out)])
    assert scoring.main() == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["macro_score"] is None
    assert report["scored_count"] == 0
    assert report["unscored_count"] == 1


def test_judge_uses_vllm_environment(monkeypatch):
    monkeypatch.delenv("XINGYUN_EVAL_MODEL", raising=False)
    monkeypatch.setenv("VLLM_MODEL", "deployed-model")
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VLLM_API_KEY", "test-key")
    config = scoring._judge_config()
    assert config == {"model": "deployed-model", "base_url": "http://localhost:8000/v1", "api_key": "test-key", "temperature": 0}
    monkeypatch.setenv("XINGYUN_EVAL_MODEL", "evaluation-model")
    assert scoring._judge_config()["model"] == "evaluation-model"


def test_missing_model_fails_without_defaulting_to_openai(monkeypatch):
    monkeypatch.delenv("XINGYUN_EVAL_MODEL", raising=False)
    monkeypatch.delenv("VLLM_MODEL", raising=False)
    with pytest.raises(scoring.InputError, match="XINGYUN_EVAL_MODEL 或 VLLM_MODEL"):
        scoring._judge_config()


def test_score_uses_eight_ragas_workers(monkeypatch):
    captured = {}

    class FakeResult:
        scores = [{"faithfulness": 1.0}]

    def fake_evaluate(dataset, *, metrics, llm, run_config):
        captured["max_workers"] = run_config.max_workers
        return FakeResult()

    monkeypatch.setattr("ragas.evaluate", fake_evaluate)
    monkeypatch.setattr("langchain_openai.ChatOpenAI", lambda **kwargs: object())
    monkeypatch.setattr("ragas.llms.LangchainLLMWrapper", lambda *args, **kwargs: object())
    monkeypatch.setattr("ragas.metrics.Faithfulness", lambda: object())
    monkeypatch.setenv("XINGYUN_EVAL_MODEL", "model")
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost/v1")
    monkeypatch.setenv("VLLM_API_KEY", "key")
    assert scoring._score([
        {"user_input": "问题", "response": "回答", "retrieved_contexts": ["证据"]}
    ]) == [1.0]
    assert captured["max_workers"] == 8


def retry_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("XINGYUN_EVAL_MODEL", "test-judge")
    dataset = tmp_path / "dataset.jsonl"
    run = tmp_path / "run.jsonl"
    cases = [
        {"case_id": case_id, "query": "问题", "knowledge_base": "js"}
        for case_id in ("ok", "retry", "still-failed", "no-answer")
    ]
    runs = [
        {"case_id": case["case_id"], "status": "completed", "response": "已保存回答", "final_retrieval_hits": [{"retrieved_context": "已保存证据"}]}
        for case in cases
    ]
    runs[-1]["response"] = None
    dataset.write_text("\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8")
    run.write_text("\n".join(json.dumps(row) for row in runs) + "\n", encoding="utf-8")
    report = tmp_path / "first.json"
    monkeypatch.setattr(scoring, "_score", lambda samples: [1.0, float("nan"), float("nan")])
    monkeypatch.setattr("sys.argv", ["score", "--dataset", str(dataset), "--run", str(run), "--out", str(report)])
    assert scoring.main() == 1
    return dataset, run, report, cases


def test_retry_only_scores_failed_cases_and_merges_previous_scores(tmp_path, monkeypatch):
    dataset, run, previous, cases = retry_inputs(tmp_path, monkeypatch)
    original_report = previous.read_bytes()
    original_run = run.read_bytes()
    out = tmp_path / "retry.json"
    requested = []

    def fake_score(samples):
        requested.extend(samples)
        return [0.5, float("nan")]

    monkeypatch.setattr(scoring, "_score", fake_score)
    monkeypatch.setattr("sys.argv", ["score", "--dataset", str(dataset), "--run", str(run), "--retry-report", str(previous), "--out", str(out)])
    assert scoring.main() == 1
    assert [sample["case_id"] for sample in requested] == ["retry", "still-failed"]
    assert all(sample["response"] == "已保存回答" for sample in requested)
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["cases"] == [
        {"case_id": "ok", "knowledge_base": "js", "faithfulness": 1.0},
        {"case_id": "retry", "knowledge_base": "js", "faithfulness": 0.5},
    ]
    assert report["macro_score"] == 0.75
    assert report["by_knowledge_base"]["js"] == {"count": 2, "score": 0.75}
    assert report["retried_count"] == 2
    assert report["unscored_count"] == 2
    assert [item["case_id"] for item in report["unscored"]] == ["still-failed", "no-answer"]
    assert previous.read_bytes() == original_report
    assert run.read_bytes() == original_run


@pytest.mark.parametrize("invalid", ["model", "duplicate", "score", "missing", "input_changed"])
def test_retry_rejects_inconsistent_report(tmp_path, monkeypatch, invalid):
    dataset, run, previous, cases = retry_inputs(tmp_path, monkeypatch)
    report = json.loads(previous.read_text(encoding="utf-8"))
    if invalid == "model":
        report["model"] = "other-model"
    elif invalid == "duplicate":
        report["unscored"].append({"case_id": "ok"})
    elif invalid == "score":
        report["cases"][0]["faithfulness"] = 2
    elif invalid == "missing":
        report["unscored"].pop()
    else:
        run.write_text(run.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    previous.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(scoring.InputError):
        scoring._read_retry_report(previous, dataset, run, cases)


def test_retry_accepts_legacy_report_without_hashes(tmp_path, monkeypatch):
    dataset, run, previous, cases = retry_inputs(tmp_path, monkeypatch)
    report = json.loads(previous.read_text(encoding="utf-8"))
    del report["dataset_sha256"]
    del report["run_sha256"]
    previous.write_text(json.dumps(report), encoding="utf-8")
    scored, ids = scoring._read_retry_report(previous, dataset, run, cases)
    assert [item["case_id"] for item in scored] == ["ok"]
    assert ids == {"retry", "still-failed", "no-answer"}


def test_retry_with_only_missing_answers_does_not_call_llm(tmp_path, monkeypatch):
    dataset, run, previous, cases = retry_inputs(tmp_path, monkeypatch)
    report = json.loads(previous.read_text(encoding="utf-8"))
    report["cases"].extend({"case_id": case_id, "knowledge_base": "js", "faithfulness": 0.5} for case_id in ("retry", "still-failed"))
    report["unscored"] = [{"case_id": "no-answer", "reason": "运行结果缺少 response"}]
    previous.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(scoring, "_score", lambda samples: pytest.fail("没有可重试样本时不应调用模型"))
    out = tmp_path / "retry.json"
    monkeypatch.setattr("sys.argv", ["score", "--dataset", str(dataset), "--run", str(run), "--retry-report", str(previous), "--out", str(out)])
    assert scoring.main() == 1
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["scored_count"] == 3
    assert result["retried_count"] == 0
