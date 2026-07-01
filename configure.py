#!/usr/bin/env python3
"""configure.py - invoked by bootstrap.sh

  1. derive its own home (REPO_HOME) from its location on disk
  2. ensure the infra dirs it needs before it can read config
  3. seed the per-machine config if absent
  4. resolve the chosen profile to an ordered list of modules
  5. apply them
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

STEP_ORDER = (
    "packages", "directories", "git", "files",
    "fonts", "links", "services", "commands",
)


def repo_home() -> Path:
    return Path(__file__).resolve().parent


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))


CONFIG_DIR = xdg_config_home() / "dotfiles-et-al"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOCAL_BIN = Path.home() / ".local" / "bin"


def ensure_infra_dirs() -> None:
    for d in (CONFIG_DIR, LOCAL_BIN):
        d.mkdir(parents=True, exist_ok=True)


def seed_config(template: Path) -> None:
    """Copy the repo template to CONFIG_PATH only when no usable config exists.
      - missing or empty   -> seed 
      - present & valid    -> leave it untouched
      - present but broken -> refuse, rather than clobber what may be a user edit
    """
    if CONFIG_PATH.exists() and CONFIG_PATH.stat().st_size > 0:
        try:
            with CONFIG_PATH.open("rb") as fh:
                tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            sys.exit(
                f"existing config is not valid TOML: {CONFIG_PATH}\n  {exc}\n"
                "fix or remove it, then re-run"
            )
        return
    if not template.is_file():
        sys.exit(f"config template missing from repo: {template}")
    shutil.copyfile(template, CONFIG_PATH)
    print(f"[configure] seeded config -> {CONFIG_PATH}")


def load_config(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        sys.exit(f"cannot read config {path}: {exc}")


def modules_in_step(config: dict, step: str) -> list[str]:
    section = config.get(step)
    return list(section.keys()) if isinstance(section, dict) else []


def expand_ref(config: dict, ref: str) -> list[tuple[str, str]]:
    """Expand one profile/requires ref ("step.module") to concrete (step, module)
    pairs. The step may be "*", meaning that module under every step defining it
    (e.g. "*.minimal")."""
    if "." not in ref:
        sys.exit(f"invalid ref (want step.module): {ref!r}")
    step, module = ref.split(".", 1)
    if step == "*":
        pairs = [(s, module) for s in STEP_ORDER if module in modules_in_step(config, s)]
        if not pairs:
            sys.exit(f"ref {ref!r} matched no modules")
        return pairs
    if step not in STEP_ORDER:
        sys.exit(f"unknown step in ref {ref!r}: {step!r}")
    if module not in modules_in_step(config, step):
        sys.exit(f"unknown module in ref {ref!r}: {step}.{module}")
    return [(step, module)]


def resolve_profile(config: dict, profile: str) -> list[tuple[str, str]]:
    """Resolve a profile to its (step, module) pairs in pipeline order, pulling
    `requires` in transitively."""
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or profile not in profiles:
        available = ", ".join(sorted((profiles or {}).keys())) or "(none)"
        sys.exit(f"unknown profile: {profile!r} (available: {available})")

    seen: set[tuple[str, str]] = set()
    stack: list[tuple[str, str]] = []
    for ref in profiles[profile]:
        stack.extend(expand_ref(config, ref))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        step, module = node
        section = config.get(step, {}).get(module, {})
        for req in section.get("requires", []):
            stack.extend(expand_ref(config, req))

    ordered: list[tuple[str, str]] = []
    for step in STEP_ORDER:
        for module in modules_in_step(config, step):
            if (step, module) in seen:
                ordered.append((step, module))
    return ordered


def collect_packages(config: dict, modules: list[tuple[str, str]]) -> list[str]:
    """Canonical package names from the resolved packages..

    A bare-string item is its own name; a table item's name is `name` (its
    `alias`, the command, is not what gets installed; install-pkg.sh checks
    presence by package name).
    """
    names: list[str] = []
    seen: set[str] = set()
    for step, module in modules:
        if step != "packages":
            continue
        for item in config[step][module].get("items", []):
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict) and item.get("name"):
                name = item["name"]
            else:
                sys.exit(f"packages.{module}: item missing a usable name: {item!r}")
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def install_packages(repo_home: Path, names: list[str], dry_run: bool) -> None:
    """Write the names to a transient manifest and hand it to install-pkg.sh -f.
    The manifest is the dumb flat .txt files of package names."""
    if not names:
        print("[configure] packages: none to install")
        return
    installer = repo_home / "install-pkg.sh"
    if not installer.is_file():
        sys.exit(f"install-pkg.sh not found in repo: {installer}")

    if dry_run:
        print(f"[configure] packages: would install {len(names)} via install-pkg.sh -f:")
        for name in names:
            print(f"    {name}")
        return

    fd, manifest = tempfile.mkstemp(prefix="dotfiles-manifest-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(names) + "\n")
        print(f"[configure] packages: installing {len(names)} via {installer.name}")
        try:
            subprocess.run(["sh", str(installer), "-f", manifest], check=True)
        except subprocess.CalledProcessError as exc:
            sys.exit(f"package install failed (install-pkg.sh exited {exc.returncode})")
    finally:
        os.unlink(manifest)


def _parse_dir_item(module: str, item: object) -> tuple[str, str | None, str | None]:
    """Return (path, mode, label) for a directories item. Bare string -> path
    only; table -> path plus optional mode and/or label."""
    if isinstance(item, str):
        return item, None, None
    if isinstance(item, dict) and item.get("path"):
        return item["path"], item.get("mode"), item.get("label")
    sys.exit(f"directories.{module}: item missing a usable path: {item!r}")


def _parse_mode(module: str, mode: str) -> int:
    try:
        return int(str(mode), 8)
    except ValueError:
        sys.exit(f"directories.{module}: invalid octal mode: {mode!r}")


def _xdg_value(path: Path) -> str:
    """Format a path for user-dirs.dirs: "$HOME/rest" when under home (matching
    xdg-user-dirs' own style), else an absolute quoted path."""
    try:
        rel = path.relative_to(Path.home())
    except ValueError:
        return f'"{path}"'
    return '"$HOME"' if str(rel) == "." else f'"$HOME/{rel}"'


def register_xdg_user_dir(label: str, path: Path, dry_run: bool) -> None:
    """Register path as the XDG user dir named by label. Prefer the official
    xdg-user-dirs-update tool when present.."""
    if shutil.which("xdg-user-dirs-update") and _register_xdg_via_tool(label, path, dry_run):
        return
    _register_xdg_via_file(label, path, dry_run)


def _register_xdg_via_tool(label: str, path: Path, dry_run: bool) -> bool:
    """Use `xdg-user-dirs-update --set TYPE PATH`. Returns True on success,
    False if the tool rejected the request so the caller can fall back E.G.
    a non-standard label the tool does not recognize."""
    xtype = label.upper()
    cmd = ["xdg-user-dirs-update", "--set", xtype, str(path)]
    if dry_run:
        print(f"[configure]   xdg: would run {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[configure]   xdg: xdg-user-dirs-update failed for {xtype} "
              f"(exit {exc.returncode}); falling back to user-dirs.dirs")
        return False
    print(f"[configure]   xdg: {xtype} -> {path} (via xdg-user-dirs-update)")
    return True


def _register_xdg_via_file(label: str, path: Path, dry_run: bool) -> None:
    """Upsert XDG_<LABEL>_DIR in ~/.config/user-dirs.dirs, replacing any existing
    line for that key so re-runs don't duplicate entries."""
    key = f"XDG_{label.upper()}_DIR"
    entry = f"{key}={_xdg_value(path)}"
    dirs_file = xdg_config_home() / "user-dirs.dirs"

    if dry_run:
        print(f"[configure]   xdg: would set {entry} in {dirs_file}")
        return

    lines = dirs_file.read_text().splitlines() if dirs_file.exists() else []
    for i, line in enumerate(lines):
        if line.lstrip().startswith(f"{key}="):
            lines[i] = entry
            break
    else:
        lines.append(entry)

    dirs_file.parent.mkdir(parents=True, exist_ok=True)
    dirs_file.write_text("\n".join(lines) + "\n")
    print(f"[configure]   xdg: {key} -> {_xdg_value(path)} (via user-dirs.dirs)")


def _apply_one_directory(module: str, item: object, dry_run: bool) -> None:
    raw, mode, label = _parse_dir_item(module, item)
    path = expand_path(raw)

    if mode is not None:
        bits = _parse_mode(module, mode)

    if dry_run:
        print(f"[configure]   mkdir -p {path}" + (f" (mode {mode})" if mode else ""))
    else:
        path.mkdir(parents=True, exist_ok=True)
        if mode is not None:
            path.chmod(bits)
        print(f"[configure]   dir {path}" + (f" (mode {mode})" if mode else ""))

    if label:
        register_xdg_user_dir(label, path, dry_run)


def apply_directories(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Create every directory declared by the resolved directories modules, in
    pipeline order, applying explicit modes and XDG registrations."""
    dir_modules = [(step, module) for step, module in modules if step == "directories"]
    if not dir_modules:
        return
    total = sum(len(config[s][m].get("items", [])) for s, m in dir_modules)
    print(f"[configure] directories: {total} item(s) across {len(dir_modules)} module(s)")
    for step, module in dir_modules:
        for item in config[step][module].get("items", []):
            _apply_one_directory(module, item, dry_run)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="configure.py",
        description="Apply a dotfiles profile (invoked by bootstrap.sh).",
    )
    parser.add_argument("profile", help="profile name defined in config.toml [profiles]")
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="show what each step would do without changing anything",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    home = repo_home()
    os.environ["REPO_HOME"] = str(home)  # expands $REPO_HOME
    ensure_infra_dirs()
    seed_config(home / "config.toml")
    config = load_config(CONFIG_PATH)

    modules = resolve_profile(config, args.profile)
    print(f"[configure] profile {args.profile!r}: resolved {len(modules)} module(s)")

    # Step 1
    install_packages(home, collect_packages(config, modules), args.dry_run)

    # Step 2
    apply_directories(config, modules, args.dry_run)

    # Step X
    done = ("packages", "directories")
    later = [f"{step}.{module}" for step, module in modules if step not in done]
    if later:
        print(f"[configure] {len(later)} later module(s) not yet applied: {', '.join(later)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
