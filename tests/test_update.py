"""Newer-version check: version parsing, comparison, and a mocked GitHub reply.
No test here touches the network."""

import io
import json

from actuisense import __version__
from actuisense import update as up


def test_parse_version():
    assert up.parse_version("v0.6.2") == (0, 6, 2)
    assert up.parse_version("0.6.2") == (0, 6, 2)
    assert up.parse_version("V1.10.0") == (1, 10, 0)
    assert up.parse_version("v0.7.0-rc1") == (0, 7, 0)   # suffix truncates cleanly
    assert up.parse_version("garbage") == ()
    assert up.parse_version("") == ()


def test_update_available_compares_against_running_version(monkeypatch):
    monkeypatch.setattr(up, "latest_release", lambda timeout=3.0: "v99.0.0")
    assert up.update_available() == "v99.0.0"
    monkeypatch.setattr(up, "latest_release", lambda timeout=3.0: "v" + __version__)
    assert up.update_available() is None                 # same version -> no update
    monkeypatch.setattr(up, "latest_release", lambda timeout=3.0: "v0.0.1")
    assert up.update_available() is None                 # older -> no update
    monkeypatch.setattr(up, "latest_release", lambda timeout=3.0: None)
    assert up.update_available() is None                 # offline/failed -> no update


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_latest_release_parses_github_json(monkeypatch):
    body = json.dumps({"tag_name": "v9.9.9"}).encode()
    monkeypatch.setattr(up.urllib.request, "urlopen",
                        lambda req, timeout=3.0: _FakeResponse(body))
    assert up.latest_release() == "v9.9.9"


def test_latest_release_fail_silent(monkeypatch):
    def boom(req, timeout=3.0):
        raise OSError("no network")
    monkeypatch.setattr(up.urllib.request, "urlopen", boom)
    assert up.latest_release() is None                   # never raises
    # malformed body -> None, not an exception
    monkeypatch.setattr(up.urllib.request, "urlopen",
                        lambda req, timeout=3.0: _FakeResponse(b"not json"))
    assert up.latest_release() is None
