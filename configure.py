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
import urllib.request
import zipfile
from pathlib import Path


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


CONFIG_DIR = xdg_config_home() / "dotfiles-et-al"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOCAL_BIN = Path.home() / ".local" / "bin"

STEP_ORDER = (
    "packages", "directories", "git", "files",
    "fonts", "links", "services", "commands",
)

NERD_FONTS_REPO = "https://github.com/ryanoasis/nerd-fonts"
NERD_FONTS_VERSION = os.environ.get("NERD_FONTS_VERSION", "v3.4.0")
FONTS_DIR = "~/.local/share/fonts"


def repo_home() -> Path:
    return Path(__file__).resolve().parent


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))


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


def _parse_mode(context: str, mode: str) -> int:
    try:
        return int(str(mode), 8)
    except ValueError:
        sys.exit(f"{context}: invalid octal mode: {mode!r}")


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
        bits = _parse_mode(f"directories.{module}", mode)

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


def _parse_git_item(module: str, item: object) -> tuple[str, str]:
    """Return (url, target) for a git item. target is the parent directory the
    repo is cloned into."""
    if isinstance(item, dict) and item.get("url") and item.get("target"):
        return item["url"], item["target"]
    sys.exit(f"git.{module}: item needs both url and target: {item!r}")


def _repo_dir_name(url: str) -> str:
    """Directory name a clone of url lands in: the last path segment minus a
    trailing .git (handles scp-style git@host:owner/repo.git too)."""
    tail = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def _clone_one(module: str, item: object, dry_run: bool) -> None:
    url, target = _parse_git_item(module, item)
    dest = expand_path(target) / _repo_dir_name(url)

    if dest.exists():
        print(f"[configure] present: {dest} (skip)")
        return
    if dry_run:
        print(f"[configure] git clone {url} -> {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[configure] cloning {url} -> {dest}")
    try:
        subprocess.run(["git", "clone", url, str(dest)], check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"git.{module}: clone failed for {url} (git exited {exc.returncode})")


def apply_git(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Clone every repo declared by the resolved git modules, in pipeline order,
    skipping any whose destination already exists."""
    git_modules = [(step, module) for step, module in modules if step == "git"]
    if not git_modules:
        return
    total = sum(len(config[s][m].get("items", [])) for s, m in git_modules)
    print(f"[configure] git: {total} repo(s) across {len(git_modules)} module(s)")
    for step, module in git_modules:
        for item in config[step][module].get("items", []):
            _clone_one(module, item, dry_run)


def _parse_file_item(module: str, item: object) -> tuple[str, str | None, str | None, str | None]:
    """Return (path, mode, content, source) for a files item. path is required;
    mode is optional; content and source are optional and mutually exclusive."""
    if not (isinstance(item, dict) and item.get("path")):
        sys.exit(f"files.{module}: item needs at least a path: {item!r}")
    content = item.get("content")
    source = item.get("source")
    if content is not None and source is not None:
        sys.exit(f"files.{module}: item has both content and source (choose one): {item!r}")
    return item["path"], item.get("mode"), content, source


def _ensure_file(module: str, path: Path) -> None:
    """Create an empty file if absent; leave an existing file's content intact."""
    if path.exists():
        return
    try:
        path.touch()
    except OSError as exc:
        sys.exit(f"files.{module}: cannot create {path}: {exc} "
                 "(does its parent dir exist? add a directories module to requires)")


def _write_file(module: str, path: Path, content: str) -> None:
    try:
        path.write_text(content)
    except OSError as exc:
        sys.exit(f"files.{module}: cannot write {path}: {exc} "
                 "(does its parent dir exist? add a directories module to requires)")


def _copy_file(module: str, src: Path, path: Path) -> None:
    if not src.exists():
        sys.exit(f"files.{module}: source not found: {src} "
                 "(from a cloned repo? add that git module to requires)")
    try:
        shutil.copyfile(src, path)
    except OSError as exc:
        sys.exit(f"files.{module}: cannot copy {src} -> {path}: {exc}")


def _apply_one_file(module: str, item: object, dry_run: bool) -> None:
    raw, mode, content, source = _parse_file_item(module, item)
    path = expand_path(raw)
    bits = _parse_mode(f"files.{module}", mode) if mode is not None else None

    if content is not None:
        action = f"write {path} ({len(content)} char(s))"
    elif source is not None:
        src = expand_path(source)
        action = f"copy {src} -> {path}"
    else:
        action = f"ensure {path}"
    suffix = f" (mode {mode})" if mode else ""

    if dry_run:
        print(f"[configure]   {action}{suffix}")
        return

    if content is not None:
        _write_file(module, path, content)
    elif source is not None:
        _copy_file(module, src, path)
    else:
        _ensure_file(module, path)
    if bits is not None:
        path.chmod(bits)
    print(f"[configure]   {action}{suffix}")


def apply_files(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Materialize every file declared by the resolved files modules, in pipeline
    order: ensure-exists, inline content, or copy-from-source, each then chmod'd."""
    file_modules = [(step, module) for step, module in modules if step == "files"]
    if not file_modules:
        return
    total = sum(len(config[s][m].get("items", [])) for s, m in file_modules)
    print(f"[configure] files: {total} item(s) across {len(file_modules)} module(s)")
    for step, module in file_modules:
        for item in config[step][module].get("items", []):
            _apply_one_file(module, item, dry_run)


def _nerd_font_url(name: str) -> str:
    if NERD_FONTS_VERSION == "latest":
        return f"{NERD_FONTS_REPO}/releases/latest/download/{name}.zip"
    return f"{NERD_FONTS_REPO}/releases/download/{NERD_FONTS_VERSION}/{name}.zip"


def _install_font(module: str, name: str, dry_run: bool) -> None:
    """Download the named Nerd Font's release zip and extract it into its own
    subdir under ~/.local/share/fonts. Skips if subdir already has files."""
    dest = expand_path(FONTS_DIR) / name
    url = _nerd_font_url(name)

    if dest.is_dir() and any(dest.iterdir()):
        print(f"[configure]   present: {dest} (skip)")
        return
    if dry_run:
        print(f"[configure]   fetch {url} -> {dest}/")
        return

    print(f"[configure]   fetching {name} ({NERD_FONTS_VERSION})")
    fd, tmpzip = tempfile.mkstemp(prefix=f"nf-{name}-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as out:
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https host)
                    shutil.copyfileobj(resp, out)
            except OSError as exc:
                sys.exit(f"fonts.{module}: download failed for {url}: {exc}")
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(tmpzip) as zf:
                zf.extractall(dest)
        except zipfile.BadZipFile as exc:
            sys.exit(f"fonts.{module}: not a valid zip for {name}: {exc}")
    finally:
        os.unlink(tmpzip)
    print(f"[configure]   installed {name} -> {dest}")


def apply_fonts(config: dict, modules: list[tuple[str, str]], dry_run: bool) -> None:
    """Install every Nerd Font declared by the resolved fonts modules. The font
    cache rebuild (fc-cache) is a separate commands."""
    font_modules = [(step, module) for step, module in modules if step == "fonts"]
    if not font_modules:
        return
    total = sum(len(config[s][m].get("items", [])) for s, m in font_modules)
    print(f"[configure] fonts: {total} font(s) across {len(font_modules)} module(s)")
    for step, module in font_modules:
        for item in config[step][module].get("items", []):
            if not isinstance(item, str):
                sys.exit(f"fonts.{module}: item must be a font name string: {item!r}")
            _install_font(module, item, dry_run)


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

    # Step 3
    apply_git(config, modules, args.dry_run)

    # Step 4
    apply_files(config, modules, args.dry_run)

    # Step 5
    apply_fonts(config, modules, args.dry_run)

    # Step X
    done = ("packages", "directories", "git", "files", "fonts")
    later = [f"{step}.{module}" for step, module in modules if step not in done]
    if later:
        print(f"[configure] {len(later)} later module(s) not yet applied: {', '.join(later)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
