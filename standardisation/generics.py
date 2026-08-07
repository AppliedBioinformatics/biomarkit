"""General-purpose helpers for the standardisation module."""
import logging

import requests

from config import LLM_BASE_URL, LLM_MODEL_NAME


def prepare_standardisation() -> bool:
    """
    Pre-flight check for the LLM fallback classifier.

    Verifies that the OpenAI-compatible endpoint (Ollama by default) is reachable and
    that the configured model is installed.

    Returns
    -------
    bool - True if the endpoint is reachable and the model is available, else False.
    """
    models_url = f"{LLM_BASE_URL.rstrip('/')}/models"

    try:
        response = requests.get(models_url, timeout=10)
        response.raise_for_status()
        model_ids = {model["id"] for model in response.json().get("data", [])}
    except (requests.exceptions.RequestException, ValueError, KeyError, TypeError) as e:
        logging.error(
            f"SETUP - LLM endpoint not reachable at {LLM_BASE_URL} ({e}). "
            f"No LLM fallback will be available — headings that regex cannot classify "
            f"will be kept as body text. To enable the fallback, install Ollama "
            f"(https://ollama.com/download) and make sure it is running."
        )
        return False

    if LLM_MODEL_NAME not in model_ids:
        logging.error(
            f"SETUP - LLM endpoint at {LLM_BASE_URL} is reachable, but model "
            f"'{LLM_MODEL_NAME}' is not installed. "
            f"headings that regex cannot classify will be kept as body text. "
            f"To enable the fallback, run: ollama pull {LLM_MODEL_NAME}"
        )
        return False

    logging.debug(f"SETUP - LLM classifier ready: '{LLM_MODEL_NAME}' available at {LLM_BASE_URL}.")
    return True