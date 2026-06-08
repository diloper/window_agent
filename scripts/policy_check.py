#!/usr/bin/env python3
"""Repository policy checks used by local hooks and CI."""

from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
from pathlib import Path

ALLOWED_BRANCH_PREFIXES = ("feature/", "hotfix/", "bugfix/")
BLOCKED_BRANCHES = {"main", "master"}


def run_git_command(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def current_branch() -> str:
    return run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])


def check_branch(stage: str, allow_main: bool) -> list[str]:
    branch = current_branch()
    errors: list[str] = []

    if branch == "HEAD":
        errors.append(
            f"[{stage}] detached HEAD is not allowed for this workflow; switch to a feature branch first."
        )
        return errors

    if branch in BLOCKED_BRANCHES and not allow_main:
        errors.append(
            f"[{stage}] direct work on '{branch}' is blocked. Use feature/YYYYMMDD-description."
        )
        return errors

    if not allow_main and not branch.startswith(ALLOWED_BRANCH_PREFIXES):
        errors.append(
            f"[{stage}] branch '{branch}' is not allowed. Allowed prefixes: {', '.join(ALLOWED_BRANCH_PREFIXES)}"
        )

    return errors


def check_py_compile(target_file: Path, stage: str) -> list[str]:
    if not target_file.exists():
        return [f"[{stage}] required file not found: {target_file}"]

    try:
        py_compile.compile(str(target_file), doraise=True)
    except py_compile.PyCompileError as exc:
        return [f"[{stage}] py_compile failed for {target_file}: {exc.msg}"]

    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repository policy checks")
    parser.add_argument(
        "--stage",
        choices=["pre-commit", "pre-push", "ci"],
        default="pre-commit",
        help="Execution stage to validate",
    )
    parser.add_argument(
        "--allow-main",
        action="store_true",
        help="Allow running checks on main/master (for special CI contexts)",
    )
    parser.add_argument(
        "--skip-branch-check",
        action="store_true",
        help="Skip branch naming policy check",
    )
    parser.add_argument(
        "--skip-compile-check",
        action="store_true",
        help="Skip baseline python compile validation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []

    if not args.skip_branch_check:
        try:
            errors.extend(check_branch(args.stage, args.allow_main))
        except subprocess.CalledProcessError as exc:
            errors.append(f"[{args.stage}] failed to query git branch: {exc.stderr.strip()}")

    if args.stage in {"pre-push", "ci"} and not args.skip_compile_check:
        target = repo_root / "screen_event_recorder.py"
        errors.extend(check_py_compile(target, args.stage))

    if errors:
        print("Policy check failed:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    print(f"Policy check passed for stage: {args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
