import pytest

from tests.client import assert_download, call, one


@pytest.fixture(scope="module")
def modules() -> list[dict]:
    rows = call("scientia", "modules")
    assert rows, "no enrolled modules"
    return rows


def _first_with(op: str, modules: list[dict]) -> tuple[str, list[dict]]:
    for m in modules:
        if rows := call("scientia", op, module=m["code"]):
            return m["code"], rows
    pytest.fail(f"no module has {op}")


def test_modules_lists_enrolled_modules(modules):
    assert all(m["code"] and m["title"] for m in modules)


def test_module_returns_its_details(modules):
    assert one("scientia", "module", code=modules[0]["code"])["title"] == modules[0]["title"]


def test_exercises_lists_coursework():
    rows = call("scientia", "exercises")
    assert rows and all(e["module"] and e["deadline"] for e in rows)


def test_exercise_spec_downloads():
    spec = next((e for e in call("scientia", "exercises") if e["has_spec"]), None)
    assert spec, "no exercise has a spec"
    assert_download(one("scientia", "exercise_spec", module=spec["module"], number=int(spec["number"])))


def test_resources_and_file_download(modules):
    code, rows = _first_with("resources", modules)
    resource = next(r for r in rows if r["type"] == "file")
    assert_download(one("scientia", "resource_file", resource_id=int(resource["id"]), module=code))


def test_past_papers_and_file_download(modules):
    code, rows = _first_with("past_papers", modules)
    assert_download(one("scientia", "past_paper_file", paper_id=int(rows[0]["id"]), module=code))


def test_results_returns_the_record():
    assert isinstance(one("scientia", "results")["results"], list)


def test_choices_lists_module_choices():
    assert all(c["status"] for c in call("scientia", "choices"))


def test_tutorial_groups_responds():
    assert all(isinstance(g, dict) for g in call("scientia", "tutorial_groups"))
