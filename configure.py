#!/usr/bin/env python3
"""configure.py - invoked by bootstrap.sh

  1. derive its own home (REPO_HOME) from its location on disk
  2. ensure the infra dirs it needs before it can read config
  3. seed the per-machine config if absent
  4. resolve the chosen profile to an ordered list of modules
  5. apply them, in pipeline order
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

CONFIG_DIR = xdg_config_home() / "dotfiles-et-al"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LOCAL_BIN = Path.home() / ".local" / "bin"


def repo_home() -> Path:
    return Path(__file__).resolve().parent


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def ensure_infra_dirs() -> None:
    for dir in (CONFIG_DIR, LOCAL_BIN):
        dir.mkdir(parents=True, exist_ok=True)


def seed_config(template: Path) -> None:
    """Copy the repo template to CONFIG_PATH only when no usable config exists.

    config.toml is per-machine (never overwrites)
      - missing or empty   -> seed 
      - present & valid    -> leave untouched
      - present but broken -> refuse
    """
    if CONFIG_PATH.exists() and CONFIG_PATH.stat().st_size > 0:
        try:
            with CONFIG_PATH.open("rb") as fh:
                tomllib.load(fh)
       
        except tomllib.TOMLDecodeError as exc:
            sys.exit(
                f"existing config is not valid TOML: {CONFIG_PATH}\n  {exc}\n"
                "fix or remove it, then re-run (it is never overwritten automatically)"
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
    """Canonical package names from the resolved packages.* modules, in pipeline
    order, de-duplicated (first occurrence wins).
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
    """Write the names to a transient manifest and hand it to install-pkg.sh -f."""
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
  
    ensure_infra_dirs()
    seed_config(home / "config.toml")
  
    config = load_config(CONFIG_PATH)
    modules = resolve_profile(config, args.profile)
  
    print(f"[configure] profile {args.profile!r}: resolved {len(modules)} module(s)")

    install_packages(home, collect_packages(config, modules), args.dry_run)

    # TODO
    later = [f"{step}.{module}" for step, module in modules if step != "packages"]
    if later:
        print(f"[configure] {len(later)} later module(s) not yet applied: {', '.join(later)}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
