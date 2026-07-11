"""Comment-preserving persistence layer around config.toml.

Wraps a tomlkit document so the TUI can read plain Python values and apply
targeted edits (items, requires, profiles) without disturbing the comments,
ASCII-art header, and layout of everything else in the file.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT, Array, InlineTable, Table

from config_tui.spec import ITEM_FIELD_ORDER, STEP_ORDER


class StoreError(Exception):
    """Raised for structural problems while reading or editing the config."""


class ConfigStore:
    """Load, edit, and save a config.toml, preserving comments and layout."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.dirty = False
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StoreError(f"cannot read {path}: {exc}") from exc
        try:
            self._doc = tomlkit.parse(text)
        except tomlkit.exceptions.ParseError as exc:
            raise StoreError(f"{path} is not valid TOML: {exc}") from exc

    def plain(self) -> dict[str, Any]:
        """The whole config as plain Python data (for validation/inspection)."""
        return self._doc.unwrap()

    def profiles(self) -> dict[str, list[str]]:
        section = self._doc.get("profiles")
        if not isinstance(section, Mapping):
            return {}
        return {name: list(refs) for name, refs in section.unwrap().items()}

    def module_names(self, step: str) -> list[str]:
        section = self._doc.get(step)
        if not isinstance(section, Mapping):
            return []
        return list(section.keys())

    def items(self, step: str, module: str) -> list[Any]:
        body = self._module(step, module)
        raw = body.get("items")
        return list(raw.unwrap()) if raw is not None else []

    def requires(self, step: str, module: str) -> list[str]:
        body = self._module(step, module)
        raw = body.get("requires")
        return list(raw.unwrap()) if raw is not None else []

    def add_item(self, step: str, module: str, item: str | Mapping[str, Any]) -> None:
        array = self._items_array(step, module, create=True)
        array.append(self._make_item(step, item))
        self.dirty = True

    def update_item(
        self, step: str, module: str, index: int, item: str | Mapping[str, Any]
    ) -> None:
        array = self._items_array(step, module, create=False)
        self._check_index(step, module, array, index)
        array[index] = self._make_item(step, item)
        self.dirty = True

    def remove_item(self, step: str, module: str, index: int) -> None:
        array = self._items_array(step, module, create=False)
        self._check_index(step, module, array, index)
        del array[index]
        self.dirty = True

    def set_requires(self, step: str, module: str, refs: list[str]) -> None:
        body = self._module(step, module)
        if refs:
            body["requires"] = self._ref_array(refs)
        elif "requires" in body:
            del body["requires"]
        self.dirty = True

    def set_profile(self, name: str, refs: list[str]) -> None:
        profiles = self._doc.get("profiles")
        if not isinstance(profiles, Mapping):
            profiles = tomlkit.table()
            self._doc["profiles"] = profiles
        profiles[name] = self._ref_array(refs)
        self.dirty = True

    def rename_profile(self, old: str, new: str) -> None:
        """Rename a profile, keeping its refs. The entry moves to the end of
        [profiles] (tomlkit has no in-place key rename); order there is
        cosmetic and not significant to the spec."""
        profiles = self._doc.get("profiles")
        if not isinstance(profiles, Mapping) or old not in profiles:
            raise StoreError(f"no such profile: {old}")
        if new in profiles:
            raise StoreError(f"profile already exists: {new}")
        value = profiles[old]
        del profiles[old]
        profiles[new] = value
        self.dirty = True

    def add_module(self, step: str, name: str) -> None:
        """Create an empty [step.name] module table."""
        if step not in STEP_ORDER:
            raise StoreError(f"unknown step: {step}")
        section = self._doc.get(step)
        if section is None:
            section = tomlkit.table(is_super_table=True)
            self._doc[step] = section
        if not isinstance(section, Mapping):
            raise StoreError(f"[{step}] is not a table")
        if name in section:
            raise StoreError(f"module already exists: {step}.{name}")
        section[name] = tomlkit.table()
        self.dirty = True

    def remove_module(self, step: str, name: str) -> None:
        """Delete a [step.name] module table (refs to it will fail validation)."""
        self._module(step, name)  # raises if absent
        del self._doc[step][name]
        self.dirty = True

    def remove_profile(self, name: str) -> None:
        profiles = self._doc.get("profiles")
        if not isinstance(profiles, Mapping) or name not in profiles:
            raise StoreError(f"no such profile: {name}")
        del profiles[name]
        self.dirty = True

    def save(self) -> None:
        """Write the document back atomically (temp file + rename)."""
        text = tomlkit.dumps(self._doc)
        directory = self.path.parent
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise StoreError(f"cannot write {self.path}: {exc}") from exc
        self.dirty = False

    def _module(self, step: str, module: str) -> Table:
        if step not in STEP_ORDER:
            raise StoreError(f"unknown step: {step}")
        section = self._doc.get(step)
        if not isinstance(section, Mapping) or module not in section:
            raise StoreError(f"no such module: {step}.{module}")
        body = section[module]
        if isinstance(body, AoT):
            raise StoreError(
                f"{step}.{module} is an array of tables, not a module table"
            )
        return body

    def _items_array(self, step: str, module: str, create: bool) -> Array:
        body = self._module(step, module)
        raw = body.get("items")
        if raw is None:
            if not create:
                raise StoreError(f"{step}.{module} has no items")
            raw = tomlkit.array()
            raw.multiline(True)
            body["items"] = raw
        if not isinstance(raw, Array):
            raise StoreError(f"{step}.{module}.items is not an array")
        return raw

    @staticmethod
    def _check_index(step: str, module: str, array: Array, index: int) -> None:
        if not 0 <= index < len(array):
            raise StoreError(f"{step}.{module}: item index {index} out of range")

    @staticmethod
    def _make_item(step: str, item: str | Mapping[str, Any]) -> Any:
        """Build a tomlkit value for one item.

        Table items are rendered in canonical field order with the padded
        `{ key = value }` style the hand-written config uses. tomlkit's
        inline_table() emits `{key = value}`, so the item is built as a TOML
        snippet (values serialized/escaped by tomlkit) and parsed back.
        """
        if isinstance(item, str):
            return item
        order = ITEM_FIELD_ORDER.get(step, ())
        ordered = [k for k in order if k in item] + [k for k in item if k not in order]
        body = ", ".join(
            f"{key} = {tomlkit.item(item[key]).as_string()}" for key in ordered
        )
        table = tomlkit.parse(f"x = {{ {body} }}")["x"]
        if not isinstance(table, InlineTable):  # pragma: no cover - defensive
            raise StoreError(f"failed to build inline table for item: {item!r}")
        return table

    @staticmethod
    def _ref_array(refs: list[str]) -> Array:
        array = tomlkit.array()
        for ref in refs:
            array.append(ref)
        if len(refs) > 3:
            array.multiline(True)
        return array
