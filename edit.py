#!/usr/bin/env python3
"""edit.py - invoked by `bootstrap.sh edit`"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

try:
    import configure

except ModuleNotFoundError:
    sys.exit("[edit] cannot import configure.py")

TUI_SUBDIR = "tui"
TUI_COMMAND = "tui"


def repo_home() -> Path:
    """REPO_HOME is the directory this file lives in, so $REPO_HOME expands
    correctly for any previews."""
    return Path(__file__).resolve().parent


def _cache_root() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return root / "dotfiles-et-al"


def ensure_tui_present(home: Path, dry_run: bool) -> Path:
    tui = home / TUI_SUBDIR

    if tui.is_dir() and any(tui.iterdir()):
        return tui

    listed = subprocess.run(
        ["git", "-C", str(home), "sparse-checkout", "list"],
        capture_output=True,
        text=True,
        check=False,
    )

    existing = listed.stdout.splitlines() if listed.returncode == 0 else []
    dirs = sorted({*existing, TUI_SUBDIR})
    cmd = ["git", "-C", str(home), "sparse-checkout", "set", *dirs]

    if dry_run:
        print(f"[edit] would run: {' '.join(cmd)}")
        return tui

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"[edit] sparse-checkout widen failed (git exited {exc.returncode})")

    if not (tui.is_dir() and any(tui.iterdir())):
        ref = os.environ.get("REF", "?")
        sys.exit(f"[edit] {TUI_SUBDIR}/ absent after widen — does REF {ref!r} ship it?")

    return tui


def _tui_tree_sha(home: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(home), "rev-parse", f"HEAD:{TUI_SUBDIR}"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return None

    return result.stdout.strip() or None


def _provision_venv(tui_dir: Path, home: Path) -> Path:
    """Create / reuse a cached venv with the TUI package installed."""
    sha = _tui_tree_sha(home) or "unpinned"
    venv = _cache_root() / f"tui-venv-{sha[:12]}"

    tui_exe = venv / "bin" / TUI_COMMAND

    if tui_exe.exists():
        return tui_exe

    print(f"[edit] provisioning TUI env at {venv}")

    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run(
            [str(venv / "bin" / "pip"), "install", "--quiet", str(tui_dir)],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"[edit] failed to provision TUI env (exit {exc.returncode})")

    if not tui_exe.exists():
        sys.exit(
            f"[edit] TUI install provided no '{TUI_COMMAND}' command in {venv} "
            "(check [project.scripts] in tui/pyproject.toml)"
        )

    return tui_exe


def launch_editor(home: Path, config_path: Path, dry_run: bool) -> int:
    """Provision the TUI and run it against config_path, preferring uv's ephemeral
    tool runner and falling back to a cached stdlib venv."""
    tui_dir = home / TUI_SUBDIR

    tui_args = [str(config_path)]
    have_uv = shutil.which("uv") is not None

    if dry_run:
        if have_uv:
            print(
                f"[edit] would run: uv tool run --from {tui_dir} "
                f"{TUI_COMMAND} {' '.join(tui_args)}"
            )
        else:
            print(
                f"[edit] would provision a venv from {tui_dir} and run: "
                f"{TUI_COMMAND} {' '.join(tui_args)}"
            )
        return 0

    if have_uv:
        cmd = [
            "uv",
            "tool",
            "run",
            "--python",
            sys.executable,
            "--from",
            str(tui_dir),
            TUI_COMMAND,
            *tui_args,
        ]
    else:
        cmd = [str(_provision_venv(tui_dir, home)), *tui_args]

    print(f"[edit] launching editor via {'uv' if have_uv else 'venv'}")

    return subprocess.run(cmd, check=False).returncode


def _validate_config(config_path: Path) -> None:
    """Never trust the editor left valid TOML on disk."""
    try:
        with config_path.open("rb") as fh:
            tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        sys.exit(
            f"[edit] config is not valid TOML after editing: {config_path}\n  {exc}"
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="edit.py",
        description="Edit the per-machine config.toml in an isolated TUI "
        "(invoked by `bootstrap.sh edit`).",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="show what would happen (fetch/provision/launch) without executing",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    home = repo_home()
    os.environ["REPO_HOME"] = str(home)

    configure.ensure_infra_dirs()
    configure.seed_config(home / "config.toml")

    config_path = configure.CONFIG_PATH

    ensure_tui_present(home, args.dry_run)

    rc = launch_editor(home, config_path, args.dry_run)
    if rc != 0:
        return rc

    if not args.dry_run:
        _validate_config(config_path)
        print(f"[edit] saved {config_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
