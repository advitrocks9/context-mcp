import pytest

from tests.client import call, one

pytestmark = pytest.mark.parametrize("provider", ["gmail", "outlook"])


def _upcoming(provider: str) -> dict:
    events = call("calendar", "list_events", provider=provider, days=30)
    if not events:
        pytest.skip(f"no {provider} events in the next 30 days")
    return events[0]


def test_list_events_returns_upcoming_events(provider):
    events = call("calendar", "list_events", provider=provider, days=30)
    assert all(e["provider"] == provider and e["id"] and e["start"] <= e["end"] for e in events)


def test_search_finds_an_upcoming_event(provider):
    event = _upcoming(provider)
    found = call("calendar", "search", provider=provider, query=event["subject"])
    assert event["id"] in {e["id"] for e in found}


def test_get_event_returns_the_listed_event(provider):
    event = _upcoming(provider)
    got = one("calendar", "get_event", provider=provider, id=event["id"])
    assert got["id"] == event["id"] and got["subject"] == event["subject"]
