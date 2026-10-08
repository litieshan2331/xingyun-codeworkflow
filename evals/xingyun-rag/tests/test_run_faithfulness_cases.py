from types import SimpleNamespace

from scripts.run_faithfulness_cases import _answer, run


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="模型回答"))])


def test_run_reuses_final_hits_and_writes_response():
    client = FakeCompletions()
    rows = [{"case_id": "c1", "query": "问题", "status": "completed", "final_retrieval_hits": [{"retrieved_context": "证据"}]}]
    output = run(rows, client, "model")
    assert output[0]["response"] == "模型回答"
    assert output[0]["generation_status"] == "completed"
    assert client.calls[0]["model"] == "model"
    assert client.calls[0]["temperature"] == 0
    assert "证据" in client.calls[0]["messages"][1]["content"]


def test_failed_retrieval_is_skipped():
    output = run([{"case_id": "c1", "status": "failed"}], FakeCompletions(), "model")
    assert output[0]["generation_status"] == "skipped"
    assert output[0]["response"] is None


def test_truncated_context_does_not_call_model():
    client = FakeCompletions()
    output = run([{"case_id": "c1", "query": "问题", "status": "completed", "final_retrieval_hits": [{"retrieved_context": "截断文本", "context_truncated": True}]}], client, "model")
    assert output[0]["generation_status"] == "failed"
    assert output[0]["response"] is None
    assert client.calls == []
