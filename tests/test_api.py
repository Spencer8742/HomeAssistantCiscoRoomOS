"""Unit tests for the pure-Python parts of the RoomOS xAPI client.

api.py is imported directly from its file path (rather than through the
`custom_components.cisco_roomos` package) so this test only needs
`websockets` installed, not the full `homeassistant` package that the
package's __init__.py pulls in.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

_API_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "cisco_roomos" / "api.py"
_spec = importlib.util.spec_from_file_location("cisco_roomos_api", _API_PATH)
_api = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_api)

merge_status = _api.merge_status
booking_sort_key = _api.booking_sort_key
booking_summary = _api.booking_summary
booking_has_ended = _api.booking_has_ended
next_booking = _api.next_booking
next_joinable_booking = _api.next_joinable_booking
resolve_device_name = _api.resolve_device_name


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
        "DialInfo": {
            "Calls": {"Call": [{"Number": "12345@example.com", "Protocol": "Spark"}]}
        },
    }
    summary = booking_summary(booking)
    assert summary == {
        "id": "abc123",
        "title": "Weekly sync",
        "start_time": "2026-07-19T09:00:00Z",
        "end_time": "2026-07-19T09:30:00Z",
        "organizer": "Ada Lovelace",
        "number": "12345@example.com",
        "protocol": "Spark",
        "joinable": True,
    }


def test_booking_summary_falls_back_to_email_and_defaults() -> None:
    summary = booking_summary({"Organizer": {"Email": "ada@example.com"}})
    assert summary["title"] == "Meeting"
    assert summary["organizer"] == "ada@example.com"
    assert summary["start_time"] is None
    assert summary["number"] is None
    assert summary["protocol"] is None
    assert summary["joinable"] is False


def test_booking_summary_missing_dial_info_yields_no_number() -> None:
    summary = booking_summary({"Id": "abc123", "DialInfo": {"Calls": {"Call": []}}})
    assert summary["number"] is None
    assert summary["protocol"] is None
    assert summary["joinable"] is False


def test_booking_summary_non_joinable_block_still_summarized() -> None:
    # A plain calendar block with no video call is listed but not joinable.
    summary = booking_summary(
        {"Title": "Focus time", "Time": {"StartTime": "2026-07-19T13:00:00Z"}}
    )
    assert summary["title"] == "Focus time"
    assert summary["start_time"] == "2026-07-19T13:00:00Z"
    assert summary["joinable"] is False


def test_booking_summary_single_call_as_dict() -> None:
    # Some xAPI serializations return a lone Call as a dict instead of a list.
    summary = booking_summary(
        {"DialInfo": {"Calls": {"Call": {"Number": "sip:room@example.com", "Protocol": "Sip"}}}}
    )
    assert summary["number"] == "sip:room@example.com"
    assert summary["protocol"] == "Sip"


def test_booking_summary_unwraps_value_leaves() -> None:
    # Leaf values may arrive wrapped as {"Value": ...}.
    summary = booking_summary(
        {"DialInfo": {"Calls": {"Call": [{"Number": {"Value": "999"}, "Protocol": {"Value": "H323"}}]}}}
    )
    assert summary["number"] == "999"
    assert summary["protocol"] == "H323"


def test_booking_summary_skips_empty_leading_call() -> None:
    # An empty first entry must not shadow a later dialable one.
    summary = booking_summary(
        {
            "DialInfo": {
                "Calls": {
                    "Call": [
                        {"Number": "   ", "Protocol": "Sip"},
                        {"Number": "12345@example.com", "Protocol": "Spark"},
                    ]
                }
            }
        }
    )
    assert summary["number"] == "12345@example.com"
    assert summary["protocol"] == "Spark"


def test_resolve_device_name_prefers_custom_name() -> None:
    assert resolve_device_name("My Desk Pro", "192.168.1.50", "192.168.1.50") == "My Desk Pro"


def test_resolve_device_name_custom_name_wins_even_over_reported_name() -> None:
    # The whole point of resolve_device_name: a live device-reported value
    # (e.g. after connecting) must never override a name the user chose.
    assert resolve_device_name("My Desk Pro", "Some Other Name", "192.168.1.50") == "My Desk Pro"


def test_resolve_device_name_falls_back_to_reported_name() -> None:
    assert resolve_device_name(None, "Conference Room A", "192.168.1.50") == "Conference Room A"
    assert resolve_device_name("", "Conference Room A", "192.168.1.50") == "Conference Room A"
    assert resolve_device_name("   ", "Conference Room A", "192.168.1.50") == "Conference Room A"


def test_resolve_device_name_falls_back_to_host_when_nothing_else_set() -> None:
    assert resolve_device_name(None, None, "192.168.1.50") == "192.168.1.50"
    assert resolve_device_name("", "", "192.168.1.50") == "192.168.1.50"
    assert resolve_device_name(None, "  ", "192.168.1.50") == "192.168.1.50"


def test_resolve_device_name_strips_whitespace() -> None:
    assert resolve_device_name("  My Desk Pro  ", None, "192.168.1.50") == "My Desk Pro"


# ── Picking the next booking ─────────────────────────────────────────────────
#
# `Bookings List` returns a WINDOW, not only what is ahead, and the device does
# not prune what has passed. Before these functions existed, "next" meant
# `bookings[0]` and "next joinable" meant the first entry carrying a number —
# so by mid-morning both pointed at a meeting that had finished, the sensor
# reported it as upcoming, and the join button dialled into it.

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _booking(
    title: str,
    *,
    ends: datetime | None,
    number: str | None = None,
    starts: datetime | None = None,
) -> dict:
    """A summary dict shaped like booking_summary() returns."""
    return {
        "title": title,
        "start_time": starts.isoformat().replace("+00:00", "Z") if starts else None,
        "end_time": ends.isoformat().replace("+00:00", "Z") if ends else None,
        "number": number,
    }


def test_booking_has_ended_compares_against_the_given_time() -> None:
    assert booking_has_ended(_booking("done", ends=NOW - timedelta(minutes=1)), NOW)
    assert not booking_has_ended(_booking("later", ends=NOW + timedelta(minutes=1)), NOW)


def test_booking_ending_exactly_now_has_ended() -> None:
    # The boundary is inclusive: a meeting whose end time is this instant is
    # over, not still running.
    assert booking_has_ended(_booking("edge", ends=NOW), NOW)


def test_booking_with_no_end_time_is_never_treated_as_ended() -> None:
    # Organizer and time fields are best-effort — they depend on which calendar
    # service the device is paired with. Something we cannot place in time must
    # stay visible rather than silently vanish.
    assert not booking_has_ended({"title": "no times"}, NOW)
    assert not booking_has_ended({"title": "empty", "end_time": ""}, NOW)


def test_booking_with_unparseable_end_time_is_never_treated_as_ended() -> None:
    assert not booking_has_ended({"title": "junk", "end_time": "not a date"}, NOW)


def test_naive_end_time_is_read_as_utc() -> None:
    # The device sends UTC; a timestamp without an offset must not be compared
    # as though it were local, which would shift it by hours.
    assert booking_has_ended({"end_time": "2026-09-04T11:00:00"}, NOW)
    assert not booking_has_ended({"end_time": "2026-09-04T13:00:00"}, NOW)


def test_next_booking_skips_what_has_already_finished() -> None:
    bookings = [
        _booking("this morning", ends=NOW - timedelta(hours=2)),
        _booking("right now", ends=NOW + timedelta(minutes=30)),
        _booking("this afternoon", ends=NOW + timedelta(hours=3)),
    ]
    assert next_booking(bookings, NOW)["title"] == "right now"


def test_next_booking_is_none_when_everything_has_finished() -> None:
    bookings = [_booking("over", ends=NOW - timedelta(hours=1))]
    assert next_booking(bookings, NOW) is None


def test_next_joinable_booking_needs_both_a_number_and_a_future() -> None:
    bookings = [
        # Finished, but dialable — the exact entry the join button used to hit.
        _booking("this morning", ends=NOW - timedelta(hours=2), number="123"),
        # Ahead of us but not a video meeting: still not joinable.
        _booking("plain calendar block", ends=NOW + timedelta(minutes=30)),
        _booking("the one to join", ends=NOW + timedelta(hours=1), number="456"),
    ]
    assert next_joinable_booking(bookings, NOW)["title"] == "the one to join"


def test_next_joinable_booking_ignores_a_finished_meeting_entirely() -> None:
    # Nothing left to join is a real answer. Returning the finished meeting
    # instead is what made the button dial into a call nobody was in.
    bookings = [_booking("this morning", ends=NOW - timedelta(hours=2), number="123")]
    assert next_joinable_booking(bookings, NOW) is None


def test_next_joinable_booking_takes_the_earliest_of_several() -> None:
    bookings = [
        _booking("soon", ends=NOW + timedelta(minutes=30), number="111"),
        _booking("later", ends=NOW + timedelta(hours=2), number="222"),
    ]
    assert next_joinable_booking(bookings, NOW)["number"] == "111"


def _back_to_back(next_starts_in: timedelta) -> list[dict]:
    """A meeting in progress, and the next one starting `next_starts_in` from NOW."""
    return [
        _booking(
            "running",
            starts=NOW - timedelta(minutes=25),
            ends=NOW + next_starts_in,
            number="111",
        ),
        _booking(
            "next",
            starts=NOW + next_starts_in,
            ends=NOW + next_starts_in + timedelta(minutes=30),
            number="222",
        ),
    ]


def test_join_stays_on_the_running_meeting_until_three_minutes_before_the_next() -> None:
    bookings = _back_to_back(timedelta(minutes=3, seconds=1))
    assert next_joinable_booking(bookings, NOW)["title"] == "running"


def test_join_moves_to_the_next_meeting_three_minutes_ahead() -> None:
    for lead in (timedelta(minutes=3), timedelta(minutes=1), timedelta(0)):
        bookings = _back_to_back(lead)
        assert next_joinable_booking(bookings, NOW)["title"] == "next", lead


def test_join_handover_needs_a_start_time() -> None:
    # Without a start time the later booking cannot be placed, so it never
    # takes the button from the one that is running.
    bookings = _back_to_back(timedelta(minutes=1))
    bookings[1]["start_time"] = None
    assert next_joinable_booking(bookings, NOW)["title"] == "running"


def test_join_handover_skips_non_dialable_bookings() -> None:
    bookings = _back_to_back(timedelta(minutes=1))
    bookings[1]["number"] = None
    assert next_joinable_booking(bookings, NOW)["title"] == "running"


# ── Guarding against a merge silently undoing a fix ──────────────────────────
#
# A merge of main into this fix's branch resolved a conflict by keeping BOTH
# versions of `next_joinable_booking` — the time-filtered one and the original.
# Python keeps the last definition, so the class looked correct on the way past
# and behaved exactly as it had before the fix. Nothing failed; the property
# just quietly went back to dialling meetings that had ended.
#
# coordinator.py imports homeassistant, which this suite deliberately does not,
# so the check is on the source rather than the imported class.


def _class_defs(path: Path, class_name: str) -> list[str]:
    """Every method name defined directly on a class, duplicates included."""
    import ast

    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    raise AssertionError(f"{class_name} not found in {path}")


def test_coordinator_defines_each_method_exactly_once() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "cisco_roomos"
        / "coordinator.py"
    )
    names = _class_defs(path, "RoomOSCoordinator")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, (
        f"RoomOSCoordinator defines {duplicates} more than once. "
        "Python keeps the last one, so the earlier definition is dead code and "
        "the behaviour is whichever copy happens to be last in the file."
    )
