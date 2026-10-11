import pytest

from tests.client import assert_download, call, one


@pytest.fixture(scope="module")
def recordings() -> list[dict]:
    for module in call("scientia", "modules"):
        if rows := call("panopto", "recordings", module=module["code"]):
            return rows
    pytest.fail("no enrolled module has recordings")


def test_folders_lists_this_years_folders():
    folders = call("panopto", "folders")
    assert folders and all(f["id"] and f["name"] for f in folders)


def test_recordings_lists_sessions(recordings):
    assert all(r["id"] and r["viewer"] for r in recordings)


def test_transcript_downloads_captions(recordings):
    captioned = next((r for r in recordings if r["captions"]), None)
    assert captioned, "no recording has captions"
    assert_download(one("panopto", "transcript", session_id=captioned["id"]))


def test_search_finds_sessions():
    assert all(s["id"] for s in call("panopto", "search", query="lecture"))
