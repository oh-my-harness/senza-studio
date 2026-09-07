import json
import io

import pytest

from senza_studio_components.tools import lookup_topic


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_response(monkeypatch, payload):
    def fake_urlopen(url, timeout=None):
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(lookup_topic.urllib.request, "urlopen", fake_urlopen)


def test_run_requires_topic():
    with pytest.raises(lookup_topic.LookupTopicError, match="topic"):
        lookup_topic.run({})


def test_run_accepts_legacy_query_alias(monkeypatch):
    _patch_response(monkeypatch, {"AbstractText": "x", "RelatedTopics": []})
    result = lookup_topic.run({"query": "France"})
    assert result["topic"] == "France"


def test_run_parses_abstract_and_related(monkeypatch):
    _patch_response(
        monkeypatch,
        {
            "AbstractText": "France is a country in Western Europe.",
            "AbstractURL": "https://duckduckgo.com/France",
            "RelatedTopics": [
                {"Text": "Paris", "FirstURL": "https://duckduckgo.com/Paris"},
                {"Name": "no text field, should be skipped"},
            ],
        },
    )

    result = lookup_topic.run({"topic": "France"})
    assert result["found"] is True
    assert result["answer"] == "France is a country in Western Europe."
    assert result["source_url"] == "https://duckduckgo.com/France"
    assert result["related"] == [{"text": "Paris", "url": "https://duckduckgo.com/Paris"}]


def test_run_reports_not_found_with_explanation_for_question_style_query(monkeypatch):
    """回归测试：实测 DuckDuckGo Instant Answer API 对 "capital of France"
    这种提问式 query 返回的响应里除了 meta 什么字段都没有。以前这会静默
    返回一串空字符串，看起来像 bug；现在要明确说明没找到、以及为什么。"""
    _patch_response(monkeypatch, {"meta": {"id": "just_metadata"}})

    result = lookup_topic.run({"topic": "capital of France"})
    assert result["found"] is False
    assert "No encyclopedia entry found" in result["answer"]
    assert "not questions" in result["answer"]


def test_run_found_is_true_when_only_related_topics(monkeypatch):
    _patch_response(
        monkeypatch,
        {"AbstractText": "", "RelatedTopics": [{"Text": "Something", "FirstURL": "http://x"}]},
    )
    result = lookup_topic.run({"topic": "ambiguous"})
    assert result["found"] is True
    assert result["answer"] == ""  # no abstract, but related topics exist


def test_run_falls_back_to_answer_field(monkeypatch):
    _patch_response(monkeypatch, {"Answer": "42", "RelatedTopics": []})
    result = lookup_topic.run({"topic": "answer to everything"})
    assert result["answer"] == "42"
    assert result["found"] is True


def test_run_wraps_network_errors(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(lookup_topic.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(lookup_topic.LookupTopicError, match="network down"):
        lookup_topic.run({"topic": "anything"})
