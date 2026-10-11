from context_mcp.imperial import http, util
from tests.client import call, one


def test_status_reports_every_provider():
    assert set(one("imperial", "status")) == {"scientia", "labts", "canvas", "panopto", "ed"}


def test_files_lists_downloaded_files():
    path = util.FILES_DIR / "50004" / "notes.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF")
    assert {"path": "50004/notes.pdf", "bytes": 4} in call("imperial", "files")


def test_clear_cache_drops_matching_entries():
    http._cache_put("probe:a", b"1", "text/plain")
    assert one("imperial", "clear_cache", prefix="probe:")["deleted"] == 1
