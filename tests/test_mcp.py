import pytest

from tests.client import one, raw, tools

GROUPS = {"mail", "calendar", "whatsapp", "linkedin", "scientia", "canvas", "panopto", "ed", "labts", "imperial"}
WITH_DELETES = {"mail", "calendar"}
FORBIDDEN = ("send", "post", "publish", "invite", "reply", "permanent", "empty_trash")
RESERVED = {"help", "ops", "schema"}


def _ops(group: str) -> set[str]:
    return set(one(group, "help")["ops"])


def test_every_group_is_registered():
    assert set(tools()) == GROUPS


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_schema_covers_every_operation(group):
    ops = _ops(group)
    assert ops and set(one(group, "schema")) == ops


@pytest.mark.parametrize("group", sorted(GROUPS))
def test_no_operation_is_shadowed_by_a_reserved_op(group):
    assert not _ops(group) & RESERVED


def test_unknown_operation_lists_the_valid_ones():
    [reply] = raw("scientia", "nope")
    assert reply["error"] == "unknown op 'nope'" and "modules" in reply["ops"]


def test_no_operation_sends_posts_or_permanently_deletes():
    leaked = [f"{g}.{op}" for g in GROUPS for op in _ops(g) if any(word in op for word in FORBIDDEN)]
    assert not leaked


@pytest.mark.parametrize("group", sorted(GROUPS - WITH_DELETES))
def test_read_only_groups_are_annotated_read_only(group):
    assert tools()[group].annotations.readOnlyHint


@pytest.mark.parametrize("group", sorted(WITH_DELETES))
def test_groups_that_delete_are_annotated_destructive(group):
    assert tools()[group].annotations.destructiveHint
