import pytest

from tests.client import one


def _ok(op: str, **params) -> dict:
    page = one("linkedin", op, **params)
    assert page["status"] == "ok", f"linkedin.{op} status {page['status']}"
    return page


def _assert_profile(profile: dict) -> None:
    assert profile["overview"] and profile["sections"] and all(profile["sections"].values())


def test_my_profile_reads_own_profile():
    _assert_profile(_ok("my_profile"))


def test_get_profile_reads_a_public_profile():
    _assert_profile(_ok("get_profile", username="williamhgates"))


def test_search_people_returns_people():
    assert all(p["username"] for p in _ok("search_people", keywords="Imperial College London")["items"])


def test_search_jobs_returns_jobs():
    jobs = _ok("search_jobs", keywords="software engineer", location="London")["items"]
    assert jobs and all(j["title"] for j in jobs)


@pytest.mark.parametrize("op", ["feed", "notifications"])
def test_page_reads_return_text(op):
    assert _ok(op)["text"]


def test_conversations_lists_threads():
    assert all(c["name"] for c in _ok("conversations")["items"])
