"""Every entity the platforms declare must have a name, in both string files.

`_attr_has_entity_name = True` means an entity's name — and therefore its
entity_id — comes from its translation key. A key with no entry does not fail:
Home Assistant falls back to the raw key, so the entity quietly registers as
`switch.desk_pro_camera_mute` with the display name "camera_mute", or worse,
under a different id than a dashboard was written against.

There are two files to keep in step, `strings.json` and `translations/en.json`,
and nothing enforces that they agree. Adding a switch and updating only one of
them is a one-line mistake with no symptom until something looks for the
entity by name.

Parsed with `ast` rather than imported: the platform modules pull in
homeassistant, and this suite deliberately runs on `websockets` alone.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "cisco_roomos"

# The platforms whose entities take a translation key as the second argument to
# RoomOSEntity.__init__.
_PLATFORMS = ("switch", "sensor", "binary_sensor", "button", "number", "select")


def _declared_keys(platform: str) -> set[str]:
    """Translation keys passed to `super().__init__(coordinator, "<key>")`."""
    path = _ROOT / f"{platform}.py"
    tree = ast.parse(path.read_text())
    keys: set[str] = set()

    for node in ast.walk(tree):
        # super().__init__(coordinator, "microphone_mute")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__init__"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            keys.add(node.args[1].value)

        # ButtonEntityDescription(key="hang_up", ...) and friends.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id.endswith("EntityDescription"):
                for kw in node.keywords:
                    if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                        keys.add(kw.value.value)

    return keys


def _named_keys(filename: str, platform: str) -> set[str]:
    data = json.loads((_ROOT / filename).read_text())
    return set(data.get("entity", {}).get(platform, {}))


def test_every_declared_entity_has_a_name_in_both_files() -> None:
    missing: list[str] = []

    for platform in _PLATFORMS:
        declared = _declared_keys(platform)
        if not declared:
            continue
        for filename in ("strings.json", "translations/en.json"):
            named = _named_keys(filename, platform)
            for key in sorted(declared - named):
                missing.append(f"{filename}: {platform}.{key}")

    assert not missing, "Entities declared in code with no translated name:\n  " + "\n  ".join(
        missing
    )


def test_the_two_string_files_agree() -> None:
    strings = json.loads((_ROOT / "strings.json").read_text()).get("entity", {})
    english = json.loads((_ROOT / "translations/en.json").read_text()).get("entity", {})

    mismatches: list[str] = []
    for platform in sorted(set(strings) | set(english)):
        a, b = set(strings.get(platform, {})), set(english.get(platform, {}))
        if a != b:
            mismatches.append(
                f"{platform}: only in strings.json {sorted(a - b)}, "
                f"only in translations/en.json {sorted(b - a)}"
            )

    assert not mismatches, "The two string files disagree:\n  " + "\n  ".join(mismatches)
