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
