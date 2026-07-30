import logging
from unittest.mock import patch, MagicMock

import requests

from config import LLM_MODEL_NAME
from standardisation.generics import prepare_standardisation


def _mock_models_response(model_ids: list[str]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"data": [{"id": model_id} for model_id in model_ids]}
    return response


@patch("standardisation.generics.requests.get")
def test_returns_true_when_model_available(mock_get):
    mock_get.return_value = _mock_models_response([LLM_MODEL_NAME, "other-model"])
    assert prepare_standardisation() is True


@patch("standardisation.generics.requests.get",
       side_effect=requests.exceptions.ConnectionError("connection refused"))
def test_returns_false_and_warns_when_endpoint_unreachable(mock_get, caplog):
    with caplog.at_level(logging.WARNING):
        result = prepare_standardisation()

    assert result is False
    assert "No LLM fallback will be available" in caplog.text


@patch("standardisation.generics.requests.get")
def test_returns_false_and_warns_when_model_missing(mock_get, caplog):
    mock_get.return_value = _mock_models_response(["other-model"])

    with caplog.at_level(logging.WARNING):
        result = prepare_standardisation()

    assert result is False
    assert f"ollama pull {LLM_MODEL_NAME}" in caplog.text


@patch("standardisation.generics.requests.get")
def test_returns_false_on_invalid_json_response(mock_get):
    response = MagicMock()
    response.json.side_effect = ValueError("not json")
    mock_get.return_value = response

    assert prepare_standardisation() is False


@patch("standardisation.generics.requests.get")
def test_queries_the_models_endpoint(mock_get):
    mock_get.return_value = _mock_models_response([LLM_MODEL_NAME])
    prepare_standardisation()

    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/models")