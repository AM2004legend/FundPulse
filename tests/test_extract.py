"""Tests for the downloader. No real network: a fake session stands in for requests."""

import pytest
import requests
from fakes import FakeResponse, FakeSession

from pipeline.extract import DownloadError, download_nav_file, split_lines

OK = FakeResponse(200, "Header\r\n \r\nChildren’s Fund\r\n\r\n".encode())


def download(session):
    sleeps = []
    lines = download_nav_file(session=session, sleep=sleeps.append)
    return lines, sleeps


def test_success_first_try_decodes_utf8():
    session = FakeSession(OK)
    lines, sleeps = download(session)

    # The curly apostrophe survives because we decode bytes as UTF-8 ourselves.
    assert lines == ["Header", " ", "Children’s Fund", ""]
    assert sleeps == []
    assert session.calls[0][1]["timeout"] > 0


def test_retries_network_errors_with_backoff_then_succeeds():
    session = FakeSession(requests.ConnectionError(), requests.Timeout(), OK)
    lines, sleeps = download(session)

    assert lines[0] == "Header"
    assert sleeps == [2, 4]


def test_retries_server_errors():
    session = FakeSession(FakeResponse(503), OK)
    lines, sleeps = download(session)

    assert lines[0] == "Header"
    assert sleeps == [2]


def test_gives_up_after_three_retries():
    session = FakeSession(*[requests.ConnectionError("down")] * 4)

    with pytest.raises(DownloadError, match="4 attempts"):
        download(session)
    assert len(session.calls) == 4  # 1 attempt + 3 retries


def test_client_error_is_not_retried():
    session = FakeSession(FakeResponse(404), OK)

    with pytest.raises(DownloadError, match="404"):
        download(session)
    assert len(session.calls) == 1


def test_split_lines_keeps_space_lines_and_drops_final_newline():
    assert split_lines("a\r\n \r\nb\r\n\r\n") == ["a", " ", "b", ""]
    assert split_lines("a\nb") == ["a", "b"]
