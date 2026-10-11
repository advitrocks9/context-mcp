import pytest

from tests.client import assert_download, call, one


@pytest.fixture(scope="module")
def courses() -> list[dict]:
    rows = call("canvas", "courses")
    assert rows, "no active courses"
    return rows


@pytest.fixture(scope="module")
def page(courses) -> tuple[int, dict]:
    for c in courses:
        if rows := call("canvas", "pages", course=c["id"]):
            return c["id"], rows[0]
    pytest.fail("no course has pages")


def test_courses_lists_active_courses(courses):
    assert all(c["id"] and c["name"] for c in courses)


def test_content_lists_course_modules(courses):
    assert all("items" in m for m in call("canvas", "content", course=courses[0]["id"]))


def test_page_returns_a_listed_page(page):
    course, listed = page
    assert one("canvas", "page", course=course, url=listed["url"])["title"] == listed["title"]


def test_panopto_folders_returns_folder_ids(courses):
    assert all(isinstance(f, str) and f for f in call("canvas", "panopto_folders", course=courses[0]["id"]))


def test_deadlines_lists_assignments():
    assert all(d["title"] and d["due"] for d in call("canvas", "deadlines"))


def test_announcements_responds():
    assert all(a["title"] for a in call("canvas", "announcements"))


def test_files_lists_course_files(courses):
    assert all(f["id"] and f["name"] for f in call("canvas", "files", course=courses[0]["id"]))


def test_file_downloads_a_linked_file(courses):
    for c in courses:
        for module in call("canvas", "content", course=c["id"]):
            for item in module["items"]:
                if item["type"] == "File" and item["content_id"]:
                    assert_download(one("canvas", "file", file_id=item["content_id"], course=str(c["id"])))
                    return
    pytest.fail("no course links a file")


def test_search_finds_course_content(courses):
    assert any(call("canvas", "search", course=c["id"], query="lecture") for c in courses)
