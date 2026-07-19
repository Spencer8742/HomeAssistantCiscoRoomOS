"""Unit tests for the pure-Python parts of the RoomOS xAPI client.

api.py is imported directly from its file path (rather than through the
`custom_components.cisco_roomos` package) so this test only needs
`websockets` installed, not the full `homeassistant` package that the
package's __init__.py pulls in.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_API_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "cisco_roomos" / "api.py"
_spec = importlib.util.spec_from_file_location("cisco_roomos_api", _API_PATH)
_api = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_api)

merge_status = _api.merge_status
booking_sort_key = _api.booking_sort_key
booking_summary = _api.booking_summary


def test_merge_scalar_and_nested_dict() -> None:
    target: dict = {}
    merge_status(target, {"Audio": {"Volume": 50}})
    assert target == {"Audio": {"Volume": 50}}

    merge_status(target, {"Audio": {"Microphones": {"Mute": "On"}}})
    assert target == {"Audio": {"Volume": 50, "Microphones": {"Mute": "On"}}}


def test_merge_overwrites_scalar() -> None:
    target = {"Audio": {"Volume": 50}}
    merge_status(target, {"Audio": {"Volume": 75}})
    assert target["Audio"]["Volume"] == 75


def test_merge_keyed_list_updates_single_item() -> None:
    target: dict = {}
    merge_status(
        target,
        {"Call": [{"id": 1, "Status": "Ringing", "RemoteNumber": "alice"}]},
    )
    merge_status(target, {"Call": [{"id": 1, "Status": "Connected"}]})

    assert target["Call"] == [{"id": 1, "Status": "Connected", "RemoteNumber": "alice"}]


def test_merge_keyed_list_adds_new_item_and_sorts_by_id() -> None:
    target: dict = {}
    merge_status(target, {"Call": [{"id": 2, "Status": "Connected"}]})
    merge_status(target, {"Call": [{"id": 1, "Status": "Ringing"}]})

    assert [call["id"] for call in target["Call"]] == [1, 2]


def test_merge_unkeyed_list_replaces_wholesale() -> None:
    target = {"Foo": ["a", "b"]}
    merge_status(target, {"Foo": ["c"]})
    assert target["Foo"] == ["c"]


def test_booking_sort_key_handles_dict_and_list_time() -> None:
    assert booking_sort_key({"Time": {"StartTime": "2026-07-19T10:00:00Z"}}) == "2026-07-19T10:00:00Z"
    assert (
        booking_sort_key({"Time": [{"StartTime": "2026-07-19T11:00:00Z"}]})
        == "2026-07-19T11:00:00Z"
    )
    assert booking_sort_key({}) == ""


def test_booking_sort_orders_earliest_first() -> None:
    bookings = [
        {"Id": "b2", "Time": {"StartTime": "2026-07-19T14:00:00Z"}},
        {"Id": "b1", "Time": {"StartTime": "2026-07-19T09:00:00Z"}},
    ]
    bookings.sort(key=booking_sort_key)
    assert [b["Id"] for b in bookings] == ["b1", "b2"]


def test_booking_summary_extracts_fields() -> None:
    booking = {
        "Id": "abc123",
        "Title": "Weekly sync",
        "Time": {"StartTime": "2026-07-19T09:00:00Z", "EndTime": "2026-07-19T09:30:00Z"},
        "Organizer": {"FirstName": "Ada", "LastName": "Lovelace"},
    }
    summary = booking_summary(booking)
    assert summary == {
        "id": "abc123",
        "title": "Weekly sync",
        "start_time": "2026-07-19T09:00:00Z",
        "end_time": "2026-07-19T09:30:00Z",
        "organizer": "Ada Lovelace",
    }


def test_booking_summary_falls_back_to_email_and_defaults() -> None:
    summary = booking_summary({"Organizer": {"Email": "ada@example.com"}})
    assert summary["title"] == "Meeting"
    assert summary["organizer"] == "ada@example.com"
    assert summary["start_time"] is None
