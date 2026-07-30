import json
import pytest
from standardisation.llms.section_classifier_base import SectionClassifierBase


class FakeClassifier(SectionClassifierBase):
    """Test double that returns a canned response."""

    def __init__(self, response: str):
        super().__init__(model="fake")
        self._response = response

    def _complete(self, system: str, user: str) -> str:
        return self._response


def test_valid_response():
    response = json.dumps({"5": "introduction", "20": "methods", "50": "delete"})
    classifier = FakeClassifier(response)
    headings = {5: "## Intro", 20: "### Plant stuff", 50: "## References"}
    result = classifier.classify(headings)
    assert result == {"5": "introduction", "20": "methods", "50": "delete"}


def test_invalid_action_retries():
    bad = json.dumps({"5": "invalid_action"})
    classifier = FakeClassifier(bad)
    result = classifier.classify({5: "## Heading"}, max_retries=0)
    assert result is None


def test_missing_keys_retries():
    response = json.dumps({"5": "introduction"})
    classifier = FakeClassifier(response)
    result = classifier.classify({5: "## A", 10: "## B"}, max_retries=0)
    assert result is None


def test_valid_actions_accepted():
    response = json.dumps({
        "1": "introduction",
        "2": "methods",
        "3": "results",
        "4": "discussion",
        "5": "delete",
        "6": "body",
    })
    classifier = FakeClassifier(response)
    headings = {i: f"## H{i}" for i in range(1, 7)}
    result = classifier.classify(headings)
    assert result is not None
    assert len(result) == 6