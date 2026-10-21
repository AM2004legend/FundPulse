"""Download AMFI's daily NAV file politely: timeout, limited retries, backoff."""

import logging
import time

import requests

from pipeline.config import NAV_URL

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_RETRIES = 3  # so at most 1 + 3 = 4 attempts
BACKOFF_SECONDS = 2  # waits 2, 4, 8 seconds between attempts
HEADERS = {"User-Agent": "FundPulse/0.1 (learning project; one request per day)"}


class DownloadError(Exception):
    """The file could not be downloaded."""


class _ServerError(Exception):
    """A 5xx response: the server's fault, so worth retrying."""


def split_lines(text: str) -> list[str]:
    """Split on line breaks (CRLF or LF), keeping lines exactly as they are otherwise.

    The trailing "" that split() produces after the file's final newline is dropped.
    """
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def download_nav_file(url=NAV_URL, session=None, sleep=time.sleep) -> list[str]:
    """Return the file's lines. `session` and `sleep` can be swapped out in tests."""
    session = session or requests.Session()
    attempts = MAX_RETRIES + 1
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=TIMEOUT_SECONDS, headers=HEADERS)
            if response.status_code >= 500:
                raise _ServerError(f"HTTP {response.status_code}")
            response.raise_for_status()  # 4xx: our request is wrong, retrying won't help
            # Decode ourselves: AMFI sends no charset, and requests would guess
            # ISO-8859-1, turning the UTF-8 apostrophe ’ into garbage.
            return split_lines(response.content.decode("utf-8"))
        except requests.HTTPError as exc:
            raise DownloadError(f"{url} failed and will not be retried: {exc}") from exc
        except (requests.ConnectionError, requests.Timeout, _ServerError) as exc:
            last_error = exc
            if attempt < attempts:
                wait = BACKOFF_SECONDS * 2 ** (attempt - 1)
                logger.warning(
                    "Attempt %d/%d failed (%s); retrying in %ds", attempt, attempts, exc, wait
                )
                sleep(wait)

    raise DownloadError(f"{url} failed after {attempts} attempts: {last_error}") from last_error
