import pytest

from tests.client import call, one, raw


@pytest.fixture(scope="module")
def exercises() -> list[dict]:
    rows = call("labts", "exercises")
    assert rows, "no LabTS exercises"
    return rows


def test_exercises_lists_lab_exercises(exercises):
    assert all(e["exercise"] and e["submission"] for e in exercises)


def test_exercises_link_their_repositories(exercises):
    assert any(e["repo"] for e in exercises), "no exercise links a repository"


def test_repository_lists_commits(exercises):
    repo = next((e["repo"] for e in exercises if e["repo"]), None)
    if repo is None:
        pytest.skip("no repository link to follow")
    assert one("labts", "repository", path=repo)["clone"]


def test_repository_refuses_action_paths():
    [reply] = raw("labts", "repository", path="/labts/lab_exercises/2627/exercises/1/submit")
    assert reply["error"] == "only repository view paths are allowed"
