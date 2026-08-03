from pathlib import Path
from dotenv import load_dotenv
from os import getenv

# Don't touch this.
BASE_DIR = Path(__file__).resolve().parent

# Filepath for secrets.env
SECRETS_FILE = BASE_DIR / "secrets.env"

# Load secrets before reading any values.
load_dotenv(dotenv_path=SECRETS_FILE)

# Corpus selection — set CORPUS_NAME in secrets.env to choose the active corpus.
CORPUS_NAME = getenv("CORPUS_NAME", "default")

# Corpus folder layout.
CORPORA_DIR = BASE_DIR / "corpora"
CORPUS_DIR = CORPORA_DIR / CORPUS_NAME
SCOPUS_INPUT_CSV_NAME = CORPUS_DIR / "scopus.csv"
DB_CACHE_FILE_NAME = CORPUS_DIR / "sqlite.db"
DOWNLOAD_DIR = CORPUS_DIR / "manuscripts"
JSON_STRUCT_DIR = CORPUS_DIR / "intermediates"
FINAL_MARKDOWN_DIR = CORPUS_DIR / "results"
REPORT_DIR = CORPUS_DIR / "reports"
LOG_DIR = CORPUS_DIR / "logs"

# Shared scratch space (not corpus-specific).
TMP_DIR = BASE_DIR / "tmp"

# Client Parameters.
USER_EMAIL = getenv("USER_EMAIL")
WILEY_TDM_TOKEN = getenv("WILEY_TDM_TOKEN")
SPRINGER_API_KEY = getenv("SPRINGER_API_KEY")
ELSEVIER_API_KEY = getenv("ELSEVIER_API_KEY")

# LLM Settings - fallback section classifier, served by a local Ollama instance by default.
# Any OpenAI-compatible endpoint can be substituted via secrets.env.
LLM_BASE_URL = getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL_NAME = getenv("LLM_MODEL_NAME", "gemma3:12b")

# MinerU settings (optional). Integer GB of GPU VRAM MinerU is allowed to budget for;
# overrides its auto-detection and raises inference batch sizes on larger GPUs.
# Set via secrets.env only if you know what you are doing; unset means auto-detect.
MINERU_VIRTUAL_VRAM_SIZE = getenv("MINERU_VIRTUAL_VRAM_SIZE")

# MinerU remote inference (optional). Both must be set in secrets.env when
# transform_text(mineru_endpoint="vllm") is used: the URL of a vLLM server hosting
# the MinerU VLM model, and the API key the server was started with.
MINERU_VLLM_ENDPOINT = getenv("MINERU_VLLM_ENDPOINT")
MINERU_API_KEY = getenv("MINERU_API_KEY")

# Program settings (don't touch these unless you know what you are doing).
MAX_THREADS = 10
PLOTLY_THEME = "plotly_white"

# MAPS.
API_URL_TO_NAME = {
    # "opensource" is the open-source download client (preprint routes + Unpaywall fallback); its api_url is
    # the Unpaywall endpoint. The "unpaywall" key is kept for clients that do their own Unpaywall lookups.
    "opensource": "https://api.unpaywall.org/v2/",
    "unpaywall": "https://api.unpaywall.org/v2/",
    "wiley": "https://api.wiley.com/onlinelibrary/tdm/v1/",
    "springer": "https://link.springer.com",
    "elsevier": "https://api.elsevier.com/",
    "mdpi": "https://www.mdpi.com",
    "frontiers": "https://www.frontiersin.org/journals",
    "american_phytopathological_society": "https://apsjournals.apsnet.org",
    "taylor_and_francis": "https://www.tandfonline.com",
    "copernicus": "https://www.copernicus.org"
}

API_KEY_TO_NAME = {
    "opensource": "",
    "unpaywall": "",
    "wiley": WILEY_TDM_TOKEN,
    "springer": SPRINGER_API_KEY,
    "elsevier": ELSEVIER_API_KEY,
    "mdpi": "",
    "frontiers": "",
    "american_phytopathological_society": "",
    "taylor_and_francis": "",
    "copernicus": ""
}