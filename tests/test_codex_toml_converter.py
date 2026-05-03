# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2025 Open Computer Use Contributors
"""Regression test for Dockerfile codex JSON→TOML converter (WR-01).

Verifies that the _to_toml_value helper embedded in the Dockerfile entrypoint
produces valid TOML for nested dict values (provider config blocks), not the
invalid JSON-format inline tables that json.dumps() would produce.

Run: python -m pytest tests/test_codex_toml_converter.py -v
"""

import tomllib
import unittest


def _to_toml_value(v):
    """TOML-aware value serializer — mirrors the helper embedded in Dockerfile entrypoint.

    This is the canonical reference implementation. The Dockerfile inline Python
    must stay in sync with this function.

    TOML has no null literal, so None is rejected explicitly rather than
    serialized as "null" (invalid TOML) or "" (silently swallowed).
    """
    import json
    if v is None:
        raise ValueError("TOML does not support null values; provider config must omit empty fields rather than set them to null")
    if isinstance(v, dict):
        inner = ", ".join(k + " = " + _to_toml_value(val) for k, val in v.items())
        return "{" + inner + "}"
    return json.dumps(v)


def _build_toml_from_codex_json(d: dict) -> str:
    """Replicate the Dockerfile entrypoint codex JSON→TOML conversion logic."""
    # Strip _spdx/_copyright/_doc keys
    d = {k: v for k, v in d.items() if not k.startswith("_")}
    providers = d.get("model_providers", {}) or {}
    default_model = d.get("default_model")
    lines = []
    if default_model:
        lines.append('model = "' + default_model + '"')
    if providers:
        first = next(iter(providers))
        lines.append('model_provider = "' + first + '"')
        lines.append("")
        for name, cfg in providers.items():
            lines.append("[model_providers." + name + "]")
            for ck, cv in cfg.items():
                lines.append(ck + " = " + _to_toml_value(cv))
            lines.append("")
    return "\n".join(lines)


class TestToTomlValue(unittest.TestCase):
    """Unit tests for the _to_toml_value helper."""

    def test_string_value(self):
        assert _to_toml_value("hello") == '"hello"'

    def test_int_value(self):
        assert _to_toml_value(42) == "42"

    def test_float_value(self):
        assert _to_toml_value(3.14) == "3.14"

    def test_bool_true(self):
        assert _to_toml_value(True) == "true"

    def test_bool_false(self):
        assert _to_toml_value(False) == "false"

    def test_none_raises_valueerror(self):
        # TOML has no null literal; serializing None as "null" would produce
        # invalid TOML. Reject explicitly to surface schema bugs at config-load
        # time, not later when codex tries to parse the file.
        import pytest
        with pytest.raises(ValueError, match="TOML does not support null"):
            _to_toml_value(None)

    def test_list_value(self):
        assert _to_toml_value([1, 2, 3]) == "[1, 2, 3]"

    def test_dict_empty(self):
        result = _to_toml_value({})
        assert result == "{}"
        # Must be parseable as a TOML inline table in context
        toml_str = f"[s]\nx = {result}"
        parsed = tomllib.loads(toml_str)
        assert parsed["s"]["x"] == {}

    def test_dict_flat(self):
        """Flat dict → TOML inline table, not JSON object notation."""
        result = _to_toml_value({"key": "value", "count": 5})
        # Must NOT contain JSON-style colon notation
        assert ":" not in result, f"Result contains JSON colon: {result!r}"
        # Must be parseable as TOML
        toml_str = f"[s]\noptions = {result}"
        parsed = tomllib.loads(toml_str)
        assert parsed["s"]["options"] == {"key": "value", "count": 5}

    def test_dict_nested(self):
        """Nested dict → nested TOML inline tables."""
        result = _to_toml_value({"outer": {"inner": 99}})
        toml_str = f"[s]\nval = {result}"
        parsed = tomllib.loads(toml_str)
        assert parsed["s"]["val"] == {"outer": {"inner": 99}}

    def test_json_dumps_would_produce_invalid_toml(self):
        """Confirm the bug: json.dumps on a dict is rejected by tomllib."""
        import json
        bad_value = json.dumps({"a": 1})  # produces {"a": 1} — JSON, not TOML
        toml_str = f"[s]\nval = {bad_value}"
        with self.assertRaises(tomllib.TOMLDecodeError):
            tomllib.loads(toml_str)


class TestBuildTomlFromCodexJson(unittest.TestCase):
    """Integration tests for the full codex JSON→TOML conversion pipeline."""

    def _parse(self, d: dict) -> dict:
        toml_str = _build_toml_from_codex_json(d)
        return tomllib.loads(toml_str)

    def test_empty_providers_produces_empty_toml(self):
        """Canonical codex.json with empty model_providers → empty TOML (no error)."""
        result = _build_toml_from_codex_json({
            "_spdx": "BUSL-1.1",
            "_copyright": "...",
            "model_providers": {},
            "default_model": None,
        })
        assert result.strip() == ""

    def test_spdx_keys_stripped(self):
        """_spdx/_copyright/_doc keys are stripped before conversion."""
        parsed = self._parse({
            "_spdx": "BUSL-1.1",
            "_copyright": "test",
            "_doc": "docs",
            "model_providers": {},
            "default_model": None,
        })
        assert "_spdx" not in parsed
        assert "_copyright" not in parsed

    def test_default_model_written(self):
        parsed = self._parse({
            "model_providers": {},
            "default_model": "gpt-4o",
        })
        assert parsed["model"] == "gpt-4o"

    def test_provider_with_scalar_values(self):
        """Provider config with scalar values only — existing working case."""
        parsed = self._parse({
            "model_providers": {
                "myprovider": {
                    "name": "My Provider",
                    "base_url": "https://api.example.com",
                    "env_key": "MY_API_KEY",
                    "requires_openai_auth": True,
                }
            },
            "default_model": None,
        })
        assert parsed["model_provider"] == "myprovider"
        prov = parsed["model_providers"]["myprovider"]
        assert prov["base_url"] == "https://api.example.com"
        assert prov["requires_openai_auth"] is True

    def test_provider_with_nested_dict_value(self):
        """Provider config with nested dict value — the WR-01 bug case.

        json.dumps would produce {"key": "value"} (invalid TOML).
        _to_toml_value produces {key = "value"} (valid TOML inline table).
        """
        parsed = self._parse({
            "model_providers": {
                "custom": {
                    "name": "custom-gateway",
                    "options": {"timeout": 30, "retry": True},
                }
            },
            "default_model": None,
        })
        prov = parsed["model_providers"]["custom"]
        assert prov["options"] == {"timeout": 30, "retry": True}

    def test_multiple_providers(self):
        """Multiple provider sections all convert correctly."""
        parsed = self._parse({
            "model_providers": {
                "alpha": {"url": "https://alpha.example.com", "count": 1},
                "beta": {"url": "https://beta.example.com", "count": 2},
            },
            "default_model": None,
        })
        assert parsed["model_providers"]["alpha"]["count"] == 1
        assert parsed["model_providers"]["beta"]["url"] == "https://beta.example.com"


if __name__ == "__main__":
    unittest.main()
