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
from config_tui.spec import ITEM_FIELD_ORDER, STEP_ORDER
from tomlkit.items import AoT, Array, Comment, InlineTable, Table, Whitespace


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
        body = self._module(step, module)
        value = self._make_item(step, item)

        if body.get("items") is None:
            rendered = tomlkit.item(value).as_string()
            array = tomlkit.parse(f"items = [\n  {rendered}\n]\n")["items"]
            self._set_before_banner(body, "items", array)
            self.dirty = True
            return

        self._items_array(step, module, create=False).append(value)
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
            self._set_before_banner(body, "requires", self._ref_array(refs))
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
        """Create an empty [step.name] module table next to its siblings.

        The table is spliced in after the step's *last existing module* rather
        than appended to the tomlkit container. Appending would place it after
        the comment banner that introduces the next section (see
        `_detach_next_section_banner`), shoving the banner away from the
        section it labels.
        """
        if step not in STEP_ORDER:
            raise StoreError(f"unknown step: {step}")

        existing = self._doc.get(step)
        if isinstance(existing, Mapping) and name in existing:
            raise StoreError(f"module already exists: {step}.{name}")

        chunks = self._step_chunks(step)
        if not chunks:
            # The step has no tables at all: a plain append is unambiguous.
            section = tomlkit.table(is_super_table=True)
            section[name] = tomlkit.table()
            self._doc[step] = section
            self.dirty = True
            return

        chunk = chunks[-1]
        siblings = self._child_tables(chunk)
        banner = self._detach_next_section_banner(siblings[-1]) if siblings else []

        module = tomlkit.table()
        module.trivia.indent = "\n"  # blank line between it and the sibling above
        chunk[name] = module

        module.value.body.extend(banner)
        self.dirty = True

    def remove_module(self, step: str, name: str) -> None:
        """Delete a [step.name] module table (refs to it will fail validation)."""
        table = self._module(step, name)
        banner = self._detach_next_section_banner(table)
        chunk = next(
            (c for c in self._step_chunks(step) if name in self._child_names(c)),
            None,
        )
        fallback = self._table_before(chunk) if chunk is not None else None

        del self._doc[step][name]

        if banner:
            siblings = self._child_tables(chunk) if chunk is not None else []
            anchor = siblings[-1] if siblings else fallback
            if anchor is not None:
                children = self._child_tables(anchor)
                (children[-1] if children else anchor).value.body.extend(banner)
            else:
                self._prepend_to_next_table(banner)

        if chunk is not None and not self._child_tables(chunk):
            if len(self._step_chunks(step)) == 1 and not self._doc[step]:
                del self._doc[step]

        self.dirty = True

    def _prepend_to_next_table(self, banner: list[Any]) -> None:
        """Render a rescued banner into the leading trivia of the first table.

        Used only when the banner's owner was the first table in the file, so
        there is nothing above it to re-attach to. A table's `trivia.indent` is
        emitted verbatim before its header, which is exactly where the banner
        belongs.
        """
        text = "".join(item.as_string() for _key, item in banner)
        if not text:
            return

        for _key, value in self._doc.body:
            if not isinstance(value, Table):
                continue

            children = self._child_tables(value)
            target = children[0] if children else value
            target.trivia.indent = text + target.trivia.indent
            return

    def _table_before(self, chunk: Table) -> Table | None:
        """The last top-level table appearing above `chunk` in the document."""
        previous: Table | None = None
        for _key, value in self._doc.body:
            if value is chunk:
                return previous
            if isinstance(value, Table):
                previous = value
        return None

    _RULE_CHARS = "─═-=_*~"

    @classmethod
    def _is_divider(cls, text: str) -> bool:
        stripped = text.lstrip("#").strip()
        return any(char * 4 in stripped for char in cls._RULE_CHARS)

    def _step_chunks(self, step: str) -> list[Table]:
        """Every top-level `[step.*]` run, in document order."""
        return [
            value
            for key, value in self._doc.body
            if key is not None and str(key) == step and isinstance(value, Table)
        ]

    @staticmethod
    def _child_tables(chunk: Table) -> list[Table]:
        return [
            v for k, v in chunk.value.body if k is not None and isinstance(v, Table)
        ]

    @staticmethod
    def _child_names(chunk: Table) -> list[str]:
        return [str(k) for k, v in chunk.value.body if k is not None]

    @classmethod
    def _set_before_banner(cls, table: Table, key: str, value: Any) -> None:
        """Set `key` on `table`, keeping it above any trailing banner."""
        if key in table:
            table[key] = value  # replaced in place; position is already right
            return

        banner = cls._detach_next_section_banner(table)

        table[key] = value
        table.value.body.extend(banner)

    @classmethod
    def _detach_next_section_banner(cls, table: Table) -> list[Any]:
        """Pop the trailing banner block off a table's container and return it."""
        body = table.value.body
        last_key = max(
            (i for i, (key, _value) in enumerate(body) if key is not None),
            default=-1,
        )
        trailing = body[last_key + 1 :]

        start = next(
            (
                i
                for i, (_key, value) in enumerate(trailing)
                if isinstance(value, Comment) and cls._is_divider(value.as_string())
            ),
            None,
        )
        if start is None:
            return []

        while start > 0 and isinstance(trailing[start - 1][1], Whitespace):
            start -= 1

        cut = last_key + 1 + start
        detached = body[cut:]

        del body[cut:]
        return detached

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
        """Build a tomlkit value for one item."""
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
