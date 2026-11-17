import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "tools" / "convert-profiles.py"
_spec = importlib.util.spec_from_file_location("convert_profiles", SCRIPT)
assert _spec is not None and _spec.loader is not None
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)


def test_converts_text_and_drops_the_derived_list() -> None:
    payload = {
        "name": "x",
        "filter_text": "# comment\n*.tmp\n",
        "filters": [{"rule": "*.tmp", "rule_type": "exclude"}],
    }
    converted, changed = module.convert_payload(payload)
    assert changed
    assert "filters" not in converted
    assert "filter_text" not in converted
    assert converted["filter_lines"] == ["# comment", "*.tmp", ""]


def test_converts_a_hand_written_structured_list() -> None:
    payload = {
        "name": "x",
        "filters": [
            {"rule": "*.log", "rule_type": "exclude", "comment": "logs"},
            {"rule": "keep.txt", "rule_type": "include", "enabled": False},
        ],
    }
    converted, changed = module.convert_payload(payload)
    assert changed
    assert converted["filter_lines"] == ["# logs", "*.log", "# + keep.txt"]


def test_already_converted_profile_is_unchanged() -> None:
    payload = {"name": "x", "filter_lines": ["*.tmp"]}
    converted, changed = module.convert_payload(payload)
    assert not changed
    assert converted == payload
