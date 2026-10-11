import re

import pytest

from tests.client import call, one


@pytest.fixture(scope="module")
def courses() -> list[dict]:
    rows = call("ed", "courses")
    assert rows, "no Ed courses"
    return rows


@pytest.fixture(scope="module")
def thread(courses) -> tuple[int, dict]:
    for c in courses:
        if rows := call("ed", "threads", course=c["id"], limit=5):
            return c["id"], rows[0]
    pytest.fail("no course has threads")


def test_courses_lists_enrolled_courses(courses):
    assert all(c["id"] and c["name"] for c in courses)


def test_threads_lists_course_threads(thread):
    _, listed = thread
    assert listed["id"] and listed["title"]


def test_thread_returns_a_listed_thread(thread):
    _, listed = thread
    assert one("ed", "thread", thread_id=listed["id"])["title"] == listed["title"]


def test_announcements_are_announcements(courses):
    assert all(a["type"] == "announcement" for a in call("ed", "announcements", course=courses[0]["id"]))


def test_search_finds_a_listed_thread(thread):
    course, listed = thread
    words = re.findall(r"[A-Za-z]{4,}", listed["title"])
    assert words, f"thread title has no searchable word: {listed['title']!r}"
    found = call("ed", "search", course=course, query=max(words, key=len), limit=50)
    assert listed["id"] in {t["id"] for t in found}
