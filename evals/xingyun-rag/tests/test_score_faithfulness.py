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


def test_score_uses_single_ragas_worker(monkeypatch):
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
    assert captured["max_workers"] == 1


def test_read_retry_ids_uses_only_unscored_cases(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"cases": [{"case_id": "ok"}], "unscored": [{"case_id": "retry"}]}), encoding="utf-8")
    assert scoring._read_retry_ids(report) == {"retry"}
