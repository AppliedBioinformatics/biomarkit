# Developer Documentation for Customisation.
This document contains documentation for developers to help with common customisations for the tool.

## Mapping SCOPUS export 'publisher' column variations to existing API's.
SCOPUS 'publisher' names are not always consistent across DOI's. For example, DOI's all accessible through the Elsevier
API may have one of the following values as their respective SCOPUS export 'publisher' column:

```python
["Elsevier B.V.", "Elsevier Ltd", "Elsevier GmbH", "Elsevier Masson s.r.l.", "Elsevier Inc.", "Elsevier Ireland Ltd"]
```

We solve this problem by mapping common variations for each publisher to a standard string that infers the correct 
API to call when download is requested for each DOI. For example:

```python
{"elsevier": ["Elsevier", "Elsevier B.V.", "Elsevier Ltd", "Elsevier GmbH", "Elsevier Masson s.r.l.", "Elsevier Inc.",
             "Elsevier Ireland Ltd"]}
```

This publisher mapping dictionary is stored in [publisher_map.py](/text_download/filter/publisher_map.py). If you find 
some variation of a 'publisher' value in your SCOPUS query export that is not covered and should be added to the
dictionary, please raise an issue or merge request. By doing this we can improve the mapping file collectively and allow
for more successful downloads.

## Building a new API using the PublisherApi base class.

All publisher-specific download clients inherit from `PublisherApi` (defined in
`text_download/apis/abc/publisher_api.py`). The base class handles logging, URL
health-checking, file path generation, download helpers, and the main iteration
loop. You only need to wire up config entries and implement one abstract method.

### Step 1 — Add config entries

Every client requires a name key in both maps inside `config.py`:

```python
# config.py

API_URL_TO_NAME = {
    ...
    "my_publisher": "https://api.mypublisher.com/v1/",
}

API_KEY_TO_NAME = {
    ...
    "my_publisher": getenv("MY_PUBLISHER_API_KEY"),   # or "" if no API key needed
}
```

If an API key is required, add the corresponding variable to your `secrets.env`:

```
MY_PUBLISHER_API_KEY=your_key_here
```

### Step 2 — Create the client class

Create a new file under `text_download/apis/clients/`, e.g.
`text_download/apis/clients/my_publisher.py`.

Subclass `PublisherApi` and pass your config name to `super().__init__()`.
The only method you **must** implement is `download_paper()` — it receives a DOI
string and must return either a `Path` to the downloaded file on success, or
`None` on failure.

```python
# text_download/apis/clients/my_publisher.py

from pathlib import Path
from text_download.apis.abc.publisher_api import PublisherApi


class MyPublisherClient(PublisherApi):

    def __init__(self, publication_list: list):
        super().__init__(name="my_publisher", publication_list=publication_list)
        # Override headers or timeout here if needed, e.g.:
        # self.request_headers = {"Authorization": f"Bearer {self.api_key}"}

    def download_paper(self, doi: str) -> Path | None:
        url = f"{self.api_url}articles/{doi}"
        filepath = self._build_download_filepath(filetype="pdf")

        if not self._attempt_download(doi=doi, url=url, filepath=filepath):
            self.logger.info(f"Download failed for {doi}")
            return None

        self.logger.info(f"Downloaded {doi} to {filepath}")
        return filepath
```

Key inherited helpers available inside `download_paper()`:

| Helper | What it does |
|---|---|
| `self._build_download_filepath(filetype)` | Returns a unique `Path` under `DOWNLOAD_DIR` prefixed with `self.name` |
| `self._attempt_download(doi, url, filepath)` | GET request with standard error handling; returns `bool` |
| `self._download_pdf_if_valid(url, filepath)` | Like `_attempt_download` but also checks the response starts with `%PDF`; returns `bool` |
| `self._download_paper_from_url(url, filepath)` | Raw GET + write, raises on failure — use when you handle errors yourself |
| `self.logger` | Instance logger writing to `LOG_DIR/my_publisher_client.log` |
| `self.api_url`, `self.api_key` | Populated from `config.py` via `self.name` |
| `self.email` | `USER_EMAIL` from `secrets.env`, used by APIs that require polite-pool registration |

`download_all_papers()` is already implemented in the base class — it iterates
`self.publication_list`, calls `download_paper()` for each DOI, caches successes,
and shows a `tqdm` progress bar. You do not need to override it unless you need
 a special setup /teardown around the loop (see Playwright note below).

### Step 3 — Register the client

Add the new client to the router map in `text_download/apis/map.py`:

```python
# text_download/apis/map.py
from text_download.apis.clients.my_publisher import MyPublisherClient

api_clients = {
    ...
    "my_publisher": MyPublisherClient,
}
```

### Step 4 — Map publisher name variants

Add an entry to `publisher_map` in `text_download/filter/publisher_map.py` so
that SCOPUS publisher strings route to your new key:

```python
publisher_map = {
    ...
    "my_publisher": [
        "My Publisher Ltd.",
        "My Publisher Inc.",
    ],
}
```
For more information on mapping publisher values to thier respective API's see [here](customisation.md#mapping-publisher-column-value-variations-to-specific-apis)