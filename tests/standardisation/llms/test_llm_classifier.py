import json
from unittest.mock import MagicMock, patch
from standardisation.llms.llm_classifier import LlamaClassifier


BLOCKS = {0: "[heading] Abstract", 1: "[paragraph] Some intro text.", 2: "[heading] Methods", 3: "[heading] Results"}


def _make_classifier():
    with patch("standardisation.llms.llm_classifier.OpenAI"):
        clf = LlamaClassifier()
    return clf


def _mock_response(content: str):
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = "stop"
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# _build_response_schema
# ---------------------------------------------------------------------------

def test_build_response_schema_keys():
    clf = _make_classifier()
    schema = clf._build_response_schema({0: "a", 2: "b"}, "introduction_index")
    assert schema["name"] == "introduction_index"
    assert schema["strict"] is True
    enum_vals = schema["schema"]["properties"]["introduction_index"]["enum"]
    assert set(enum_vals) == {"0", "2"}


def test_build_response_schema_required():
    clf = _make_classifier()
    schema = clf._build_response_schema({1: "x"}, "methods_index")
    assert "methods_index" in schema["schema"]["required"]
    assert schema["schema"]["additionalProperties"] is False


# ---------------------------------------------------------------------------
# _complete — markdown fence stripping
# ---------------------------------------------------------------------------

def test_complete_strips_markdown_fences():
    clf = _make_classifier()
    raw = '```json\n{"introduction_index": "1"}\n```'
    clf.client.chat.completions.create.return_value = _mock_response(raw)
    result = clf._complete(system="sys", user="usr")
    assert not result.startswith("```")
    assert '"introduction_index"' in result


def test_complete_passes_schema_when_given():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response('{"k": "1"}')
    schema = {"name": "k", "strict": True, "schema": {}}
    clf._complete(system="s", user="u", response_schema=schema)
    call_kwargs = clf.client.chat.completions.create.call_args[1]
    assert "response_format" in call_kwargs


def test_complete_omits_response_format_when_no_schema():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response('{"k": "1"}')
    clf._complete(system="s", user="u")
    call_kwargs = clf.client.chat.completions.create.call_args[1]
    assert "response_format" not in call_kwargs


# ---------------------------------------------------------------------------
# _classify_block — success and retry logic
# ---------------------------------------------------------------------------

def test_classify_block_returns_int_on_success():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"introduction_index": "1"})
    )
    result = clf._classify_block(BLOCKS, "prompt", "introduction_index")
    assert result == 1


def test_classify_block_returns_none_after_all_retries_fail():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response("not json at all")
    result = clf._classify_block(BLOCKS, "prompt", "introduction_index", max_retries=1)
    assert result is None


def test_classify_block_retries_on_invalid_key():
    clf = _make_classifier()
    bad = _mock_response(json.dumps({"introduction_index": "99"}))  # 99 not in BLOCKS
    good = _mock_response(json.dumps({"introduction_index": "2"}))
    clf.client.chat.completions.create.side_effect = [bad, good]
    result = clf._classify_block(BLOCKS, "prompt", "introduction_index", max_retries=1)
    assert result == 2


def test_classify_block_succeeds_on_first_retry():
    clf = _make_classifier()
    clf.client.chat.completions.create.side_effect = [
        _mock_response("bad json"),
        _mock_response(json.dumps({"methods_index": "2"})),
    ]
    result = clf._classify_block(BLOCKS, "prompt", "methods_index", max_retries=2)
    assert result == 2


# ---------------------------------------------------------------------------
# Public classify_* methods
# ---------------------------------------------------------------------------

def test_classify_intro_returns_index():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"introduction_index": "1"})
    )
    assert clf.classify_intro(BLOCKS) == 1


def test_classify_end_returns_index():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"end_index": "3"})
    )
    assert clf.classify_end(BLOCKS) == 3


def test_classify_methods_returns_index():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"methods_index": "2"})
    )
    assert clf.classify_methods(BLOCKS) == 2


def test_classify_results_returns_index():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"results_index": "3"})
    )
    assert clf.classify_results(BLOCKS) == 3


# ---------------------------------------------------------------------------
# classify_discussion — distinct path (no schema, nullable result)
# ---------------------------------------------------------------------------

def test_classify_discussion_returns_index_when_present():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"discussion_index": 3})
    )
    assert clf.classify_discussion(BLOCKS) == 3


def test_classify_discussion_returns_none_when_null():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"discussion_index": None})
    )
    assert clf.classify_discussion(BLOCKS) is None


def test_classify_discussion_returns_none_after_all_retries_fail():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response("not json")
    result = clf.classify_discussion(BLOCKS, max_retries=1)
    assert result is None


def test_classify_discussion_does_not_use_schema():
    clf = _make_classifier()
    clf.client.chat.completions.create.return_value = _mock_response(
        json.dumps({"discussion_index": 2})
    )
    clf.classify_discussion(BLOCKS)
    call_kwargs = clf.client.chat.completions.create.call_args[1]
    assert "response_format" not in call_kwargs
