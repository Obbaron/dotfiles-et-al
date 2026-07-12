"""Schema knowledge and validation for config.toml.

Everything in this module is derived from config-toml-spec.md. It operates on
plain Python data (dicts/lists/strings/bools); callers holding a tomlkit
document should pass ``doc.unwrap()`` (see ``as_plain``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

STEP_ORDER: tuple[str, ...] = (
    "packages",
    "directories",
    "git",
    "files",
    "fonts",
    "links",
    "services",
    "commands",
)

XDG_LABELS: tuple[str, ...] = (
    "Desktop",
    "Download",
    "Documents",
    "Music",
    "Pictures",
    "Videos",
    "Templates",
    "Publicshare",
)

# Steps whose items may be bare strings (spec section 9).
BARE_STRING_STEPS: frozenset[str] = frozenset({"packages", "directories", "fonts"})

# Canonical field order per step, used when (re)building item tables so the
# emitted TOML reads like the hand-written examples in the spec.
ITEM_FIELD_ORDER: dict[str, tuple[str, ...]] = {
    "packages": ("name", "alias"),
    "directories": ("path", "mode", "label"),
    "git": ("url", "target"),
    "files": ("path", "mode", "content", "source"),
    "fonts": (),
    "links": ("src", "dest", "copy"),
    "services": ("name", "enabled", "started", "scope"),
    "commands": ("run", "desc", "cwd", "creates", "unless", "sudo"),
}


@dataclass(frozen=True)
class Issue:
    """A single validation problem, tied to a location in the config."""

    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


def as_plain(config: Any) -> Any:
    """Return plain Python data for a config (unwraps tomlkit documents)."""
    unwrap = getattr(config, "unwrap", None)
    return unwrap() if callable(unwrap) else config


def is_octal_mode(value: object) -> bool:
    """True if value is a valid octal mode (string of octal digits, or int)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (str, int)):
        return False
    text = str(value)
    return len(text) > 0 and all(ch in "01234567" for ch in text)


def module_names(config: Mapping[str, Any], step: str) -> list[str]:
    """Module names defined under a step (empty if the step is absent)."""
    section = config.get(step)
    if isinstance(section, Mapping):
        return list(section.keys())
    return []


def ref_targets(config: Mapping[str, Any], ref: str) -> list[tuple[str, str]]:
    """Resolve a reference to (step, module) pairs; empty if it resolves to nothing."""
    if "." not in ref:
        return []
    step, module = ref.split(".", 1)
    if step == "*":
        return [(s, module) for s in STEP_ORDER if module in module_names(config, s)]
    if step in STEP_ORDER and module in module_names(config, step):
        return [(step, module)]
    return []


def ref_choices(config: Mapping[str, Any], extra: Sequence[str] = ()) -> list[str]:
    """All references worth offering in a picker.

    Specific ``step.module`` refs in pipeline order, plus ``*.name`` wildcards
    for names defined under two or more steps. Any ``extra`` refs already in
    use are included so existing selections never disappear from the UI.
    """
    specific = [
        f"{step}.{module}"
        for step in STEP_ORDER
        for module in module_names(config, step)
    ]
    counts: dict[str, int] = {}
    for step in STEP_ORDER:
        for module in module_names(config, step):
            counts[module] = counts.get(module, 0) + 1
    wildcards = [f"*.{name}" for name, n in sorted(counts.items()) if n >= 2]
    choices = wildcards + specific
    for ref in extra:
        if ref not in choices:
            choices.append(ref)
    return choices


def _validate_ref(config: Mapping[str, Any], ref: object, location: str) -> list[Issue]:
    if not isinstance(ref, str):
        return [Issue(location, f"reference must be a string, got {ref!r}")]
    if "." not in ref:
        return [Issue(location, f"invalid ref {ref!r} (want `step.module`)")]
    step, _module = ref.split(".", 1)
    if step != "*" and step not in STEP_ORDER:
        return [Issue(location, f"unknown step in ref {ref!r}")]
    if not ref_targets(config, ref):
        return [Issue(location, f"ref {ref!r} does not resolve to any defined module")]
    return []


def _require_string(item: Mapping[str, Any], key: str, location: str) -> list[Issue]:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        return [Issue(location, f"`{key}` must be a non-empty string")]
    return []


def _optional_string(item: Mapping[str, Any], key: str, location: str) -> list[Issue]:
    if key in item and not isinstance(item[key], str):
        return [Issue(location, f"`{key}` must be a string")]
    return []


def _optional_bool(item: Mapping[str, Any], key: str, location: str) -> list[Issue]:
    if key in item and not isinstance(item[key], bool):
        return [Issue(location, f"`{key}` must be true or false")]
    return []


def _optional_mode(item: Mapping[str, Any], location: str) -> list[Issue]:
    if "mode" in item and not is_octal_mode(item["mode"]):
        return [Issue(location, f"`mode` must be octal digits, got {item['mode']!r}")]
    return []


def _unknown_keys(
    item: Mapping[str, Any], allowed: Sequence[str], location: str
) -> list[Issue]:
    extras = [k for k in item if k not in allowed]
    if extras:
        return [Issue(location, f"unknown field(s): {', '.join(sorted(extras))}")]
    return []


def validate_item(step: str, item: object, location: str) -> list[Issue]:
    """Validate one item against its step's shape (spec sections 9 and 10)."""
    issues: list[Issue] = []

    if isinstance(item, str):
        if step in BARE_STRING_STEPS:
            if not item:
                issues.append(Issue(location, "bare-string item must not be empty"))
            return issues
        return [Issue(location, f"`{step}` items must be tables, not bare strings")]

    if not isinstance(item, Mapping):
        return [
            Issue(
                location, f"item must be a string or table, got {type(item).__name__}"
            )
        ]

    if step == "fonts":
        return [
            Issue(location, "`fonts` items must be strings (table form is invalid)")
        ]

    allowed = ITEM_FIELD_ORDER[step]
    issues.extend(_unknown_keys(item, allowed, location))

    if step == "packages":
        issues.extend(_require_string(item, "name", location))
        issues.extend(_optional_string(item, "alias", location))
    elif step == "directories":
        issues.extend(_require_string(item, "path", location))
        issues.extend(_optional_mode(item, location))
        issues.extend(_optional_string(item, "label", location))
    elif step == "git":
        issues.extend(_require_string(item, "url", location))
        issues.extend(_require_string(item, "target", location))
    elif step == "files":
        issues.extend(_require_string(item, "path", location))
        issues.extend(_optional_mode(item, location))
        issues.extend(_optional_string(item, "content", location))
        issues.extend(_optional_string(item, "source", location))
        if "content" in item and "source" in item:
            issues.append(
                Issue(location, "`content` and `source` are mutually exclusive")
            )
    elif step == "links":
        issues.extend(_require_string(item, "src", location))
        issues.extend(_require_string(item, "dest", location))
        issues.extend(_optional_bool(item, "copy", location))
    elif step == "services":
        issues.extend(_require_string(item, "name", location))
        issues.extend(_optional_bool(item, "enabled", location))
        issues.extend(_optional_bool(item, "started", location))
        scope = item.get("scope", "system")
        if scope not in ("system", "user"):
            issues.append(
                Issue(location, f"`scope` must be `system` or `user`, got {scope!r}")
            )
    elif step == "commands":
        issues.extend(_require_string(item, "run", location))
        for key in ("desc", "cwd", "creates", "unless"):
            issues.extend(_optional_string(item, key, location))
        issues.extend(_optional_bool(item, "sudo", location))

    return issues


def _validate_module(
    config: Mapping[str, Any], step: str, module: str, body: object
) -> list[Issue]:
    location = f"{step}.{module}"
    if not isinstance(body, Mapping):
        return [Issue(location, "module must be a table")]

    issues: list[Issue] = []
    issues.extend(_unknown_keys(body, ("requires", "items"), location))

    requires = body.get("requires")
    if requires is not None:
        if isinstance(requires, Sequence) and not isinstance(requires, str):
            for ref in requires:
                issues.extend(_validate_ref(config, ref, f"{location}.requires"))
        else:
            issues.append(Issue(location, "`requires` must be an array of refs"))

    items = body.get("items")
    if items is not None:
        if isinstance(items, Sequence) and not isinstance(items, str):
            for index, item in enumerate(items):
                issues.extend(validate_item(step, item, f"{location}.items[{index}]"))
        else:
            issues.append(Issue(location, "`items` must be an array"))

    return issues


def validate_config(config: Any) -> list[Issue]:
    """Validate a whole config against the checklist in spec section 10."""
    config = as_plain(config)
    issues: list[Issue] = []

    if not isinstance(config, Mapping):
        return [Issue("(top level)", "config must be a TOML table")]

    for key in config:
        if key != "profiles" and key not in STEP_ORDER:
            issues.append(
                Issue(key, "unknown top-level table (not `profiles` or a step)")
            )

    profiles = config.get("profiles")
    if profiles is None:
        issues.append(Issue("profiles", "no [profiles] table defined"))
    elif not isinstance(profiles, Mapping):
        issues.append(Issue("profiles", "[profiles] must be a table"))
    else:
        for name, refs in profiles.items():
            location = f"profiles.{name}"
            if isinstance(refs, Sequence) and not isinstance(refs, str):
                for ref in refs:
                    issues.extend(_validate_ref(config, ref, location))
            else:
                issues.append(Issue(location, "profile value must be an array of refs"))

    for step in STEP_ORDER:
        section = config.get(step)
        if section is None:
            continue
        if not isinstance(section, Mapping):
            issues.append(Issue(step, "step must be a table of modules"))
            continue
        for module, body in section.items():
            issues.extend(_validate_module(config, step, module, body))

    return issues


def summarize_item(step: str, item: object) -> str:
    """One-line description of an item for list views."""
    if isinstance(item, str):
        return item
    if not isinstance(item, Mapping):
        return repr(item)

    if step == "packages":
        alias = item.get("alias")
        return f"{item.get('name', '?')}" + (f"  (command: {alias})" if alias else "")
    if step == "directories":
        parts = [str(item.get("path", "?"))]
        if item.get("mode"):
            parts.append(f"mode={item['mode']}")
        if item.get("label"):
            parts.append(f"label={item['label']}")
        return "  ".join(parts)
    if step == "git":
        return f"{item.get('url', '?')}  ->  {item.get('target', '?')}"
    if step == "files":
        parts = [str(item.get("path", "?"))]
        if item.get("mode"):
            parts.append(f"mode={item['mode']}")
        if "content" in item:
            parts.append(f"content ({len(str(item['content']))} chars)")
        if "source" in item:
            parts.append(f"source={item['source']}")
        return "  ".join(parts)
    if step == "links":
        arrow = "copy of" if item.get("copy") else "->"
        return f"{item.get('dest', '?')}  {arrow}  {item.get('src', '?')}"
    if step == "services":
        parts = [str(item.get("name", "?"))]
        for key in ("enabled", "started"):
            if key in item:
                parts.append(f"{key}={str(item[key]).lower()}")
        parts.append(f"scope={item.get('scope', 'system')}")
        return "  ".join(parts)
    if step == "commands":
        label = item.get("desc") or item.get("run", "?")
        guards = [g for g in ("creates", "unless") if g in item]
        suffix = f"  [{', '.join(guards)}]" if guards else ""
        sudo = "  (sudo)" if item.get("sudo") else ""
        return f"{label}{suffix}{sudo}"
    return repr(item)
