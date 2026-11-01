#!/usr/bin/env python3
"""
Homelab Blueprint - Configuration Schema Migrator (.env Auto-Upgrade)
Safely compares live .env files against .env.example templates across the monorepo.
Injects newly introduced configuration keys with template defaults while preserving
existing user values, secrets, and comments. Generates automated timestamped backups.
Zero external dependencies (Python 3.10+ standard library only).
"""

import os
import sys
import re
import shutil
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

# Safe UTF-8 console output for Windows cp1252 and Linux UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Terminal ANSI formatting
USE_COLOR = sys.stdout.isatty() and (os.name != "nt" or os.environ.get("ANSICON") or os.environ.get("WT_SESSION"))
GREEN = "\033[92m" if USE_COLOR else ""
YELLOW = "\033[93m" if USE_COLOR else ""
RED = "\033[91m" if USE_COLOR else ""
CYAN = "\033[96m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


def parse_env_pairs(filepath: Path) -> Dict[str, str]:
    """Parses a .env file into a dictionary of key-value pairs (excluding comments)."""
    if not filepath.exists() or not filepath.is_file():
        return {}

    kv = {}
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                kv[k.strip()] = v.strip().strip("'\"")
    return kv


def extract_template_blocks(example_path: Path) -> Dict[str, Tuple[str, str]]:
    """
    Extracts each variable definition from a template .env.example along with
    any preceding inline documentation or comments.
    Returns: {KEY: (default_value, block_text_with_comments)}
    """
    if not example_path.exists():
        return {}

    results = {}
    current_comments: List[str] = []

    with open(example_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                current_comments = []
                continue
            if stripped.startswith("#"):
                # Avoid collecting section dividers as key comments
                if not stripped.startswith("# ===") and not stripped.startswith("# ---"):
                    current_comments.append(line.rstrip())
                continue
            if "=" in stripped:
                k, v = stripped.split("=", 1)
                key = k.strip()
                val = v.strip().strip("'\"")
                # Build formatted injection block
                block_lines = []
                if current_comments:
                    block_lines.extend(current_comments)
                block_lines.append(f"{key}={val}")
                results[key] = (val, "\n".join(block_lines))
                current_comments = []

    return results


def detect_schema_diff(env_path: Path, example_path: Path) -> Dict[str, Any]:
    """
    Analyzes differences between an active .env and its reference .env.example.
    Returns details on missing keys, deprecated keys, and synced keys.
    """
    if not example_path.exists():
        return {
            "status": "error",
            "error": f"Template file '{example_path}' not found.",
            "is_up_to_date": True,
            "missing_keys": {},
            "deprecated_keys": [],
            "synced_keys": [],
        }

    example_blocks = extract_template_blocks(example_path)
    example_keys = set(example_blocks.keys())

    if not env_path.exists():
        return {
            "status": "missing_env",
            "env_path": str(env_path),
            "example_path": str(example_path),
            "is_up_to_date": False,
            "missing_keys": {k: example_blocks[k][0] for k in example_keys},
            "deprecated_keys": [],
            "synced_keys": [],
        }

    env_pairs = parse_env_pairs(env_path)
    env_keys = set(env_pairs.keys())

    missing = {k: example_blocks[k][0] for k in (example_keys - env_keys)}
    deprecated = sorted(list(env_keys - example_keys))
    synced = sorted(list(env_keys & example_keys))

    return {
        "status": "ok",
        "env_path": str(env_path),
        "example_path": str(example_path),
        "is_up_to_date": len(missing) == 0,
        "missing_keys": missing,
        "deprecated_keys": deprecated,
        "synced_keys": synced,
    }


def migrate_single_env(
    env_path: Path,
    example_path: Path,
    dry_run: bool = False,
    backup_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Safely migrates a single .env file if missing keys are detected.
    Creates an automated backup, injects template defaults, and writes atomically.
    """
    diff = detect_schema_diff(env_path, example_path)
    if diff.get("status") == "error":
        return {"success": False, "error": diff.get("error")}

    if diff["is_up_to_date"]:
        return {
            "success": True,
            "migrated": False,
            "env_path": str(env_path),
            "message": "Configuration schema is already up to date.",
            "missing_keys": [],
        }

    missing_keys = diff["missing_keys"]
    template_blocks = extract_template_blocks(example_path)

    # If active .env doesn't exist yet, seed it directly from example
    if not env_path.exists():
        if dry_run:
            return {
                "success": True,
                "migrated": True,
                "dry_run": True,
                "env_path": str(env_path),
                "injected_keys": list(missing_keys.keys()),
                "message": f"[DRY-RUN] Would create '{env_path.name}' from '{example_path.name}'.",
            }
        shutil.copy2(example_path, env_path)
        return {
            "success": True,
            "migrated": True,
            "env_path": str(env_path),
            "injected_keys": list(missing_keys.keys()),
            "message": f"Seeded '{env_path.name}' directly from template.",
        }

    # Backup active .env before modification
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_backup_dir = backup_dir or env_path.parent
    target_backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = target_backup_dir / f"{env_path.name}.backup.{timestamp}"

    if not dry_run:
        shutil.copy2(env_path, backup_path)

    # Read original content
    with open(env_path, "r", encoding="utf-8", errors="replace") as f:
        original_content = f.read()

    # Build injection block
    injection_lines = [
        "",
        f"# ==============================================================================",
        f"# Injected by Homelab Schema Migrator ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
        f"# Newly introduced configuration keys with recommended template defaults.",
        f"# ==============================================================================",
    ]

    for key in sorted(missing_keys.keys()):
        block_text = template_blocks[key][1]
        injection_lines.append(block_text)

    new_content = original_content.rstrip() + "\n" + "\n".join(injection_lines) + "\n"

    if dry_run:
        return {
            "success": True,
            "migrated": True,
            "dry_run": True,
            "env_path": str(env_path),
            "backup_path": str(backup_path),
            "injected_keys": sorted(list(missing_keys.keys())),
            "message": f"[DRY-RUN] Would inject {len(missing_keys)} missing key(s) into {env_path.name}.",
        }

    # Atomic write via temporary file
    temp_path = env_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    temp_path.replace(env_path)

    return {
        "success": True,
        "migrated": True,
        "dry_run": False,
        "env_path": str(env_path),
        "backup_path": str(backup_path),
        "injected_keys": sorted(list(missing_keys.keys())),
        "message": f"Successfully migrated {env_path.name} (backed up to {backup_path.name}).",
    }


def find_all_environment_targets(base_dir: Path) -> List[Tuple[Path, Path]]:
    """Discovers all known .env and .env.example target pairs across the monorepo."""
    targets = [
        (base_dir / ".env", base_dir / ".env.example"),
        (base_dir / "apps" / "mediaserver" / ".env", base_dir / "apps" / "mediaserver" / ".env.example"),
        (base_dir / "apps" / "noodle-gallery" / ".env", base_dir / "apps" / "noodle-gallery" / ".env.example"),
        (base_dir / "apps" / "control-hub" / ".env", base_dir / "apps" / "control-hub" / ".env.example"),
    ]
    # Filter to only targets where the reference template exists
    return [(env, ex) for (env, ex) in targets if ex.exists()]


def run_migration_suite(
    base_dir: Path,
    dry_run: bool = False,
    check_only: bool = False,
) -> int:
    """
    Executes full migration sweep across all environments.
    Returns 0 if everything is up to date, 1 if migrations are needed/failed.
    """
    targets = find_all_environment_targets(base_dir)
    print(f"\n{BOLD}{CYAN}============================================================{RESET}")
    print(f"{BOLD}{CYAN}  🔄 Homelab Blueprint - Configuration Schema Migrator{RESET}")
    print(f"{BOLD}{CYAN}============================================================{RESET}")
    print(f"Target Root: {base_dir}")
    print(f"Mode:        {'CHECK ONLY' if check_only else ('DRY-RUN' if dry_run else 'ACTIVE MIGRATION')}\n")

    overall_out_of_date = 0
    migrations_performed = 0

    for env_path, example_path in targets:
        rel_env = env_path.relative_to(base_dir) if env_path.is_relative_to(base_dir) else env_path
        diff = detect_schema_diff(env_path, example_path)

        if not env_path.exists():
            print(f"{BOLD}{YELLOW}• {rel_env}:{RESET} File does not exist yet (will seed from template on setup)")
            continue

        if diff["is_up_to_date"]:
            print(f"{BOLD}{GREEN}• {rel_env}:{RESET} {GREEN}[UP TO DATE]{RESET} ({len(diff['synced_keys'])} synced keys)")
            if diff["deprecated_keys"]:
                print(f"  {YELLOW}Notice:{RESET} {len(diff['deprecated_keys'])} custom/untracked key(s): {', '.join(diff['deprecated_keys'])}")
            continue

        overall_out_of_date += 1
        missing = diff["missing_keys"]
        print(f"{BOLD}{RED}• {rel_env}:{RESET} {RED}[OUTDATED SCHEMA]{RESET} Missing {len(missing)} key(s):")
        for k, v in missing.items():
            print(f"    - {BOLD}{k}{RESET} (default: '{v}')")

        if check_only:
            continue

        result = migrate_single_env(env_path, example_path, dry_run=dry_run)
        if result.get("success"):
            migrations_performed += 1
            if dry_run:
                print(f"    {CYAN}[SIMULATION]{RESET} Would inject keys and save backup to {result.get('backup_path')}")
            else:
                print(f"    {GREEN}[MIGRATED]{RESET} Successfully injected keys. Backup: {Path(result.get('backup_path', '')).name}")
        else:
            print(f"    {RED}[ERROR]{RESET} Migration failed: {result.get('error')}")

    print(f"\n{BOLD}{CYAN}============================================================{RESET}")
    if overall_out_of_date == 0:
        print(f"{BOLD}{GREEN}  🎉 ALL CONFIGURATION SCHEMAS ARE 100% UP TO DATE!{RESET}")
        print(f"{BOLD}{CYAN}============================================================{RESET}\n")
        return 0
    elif check_only:
        print(f"{BOLD}{YELLOW}  ⚠️ {overall_out_of_date} environment(s) have missing configuration keys.{RESET}")
        print(f"  Run './setup.sh --migrate' to automatically upgrade them safely.")
        print(f"{BOLD}{CYAN}============================================================{RESET}\n")
        return 1
    else:
        status_word = "simulated" if dry_run else "completed"
        print(f"{BOLD}{GREEN}  ✓ Migration {status_word} for {migrations_performed} environment(s).{RESET}")
        print(f"{BOLD}{CYAN}============================================================{RESET}\n")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Homelab Blueprint Configuration Schema Migrator (.env Auto-Upgrade)"
    )
    parser.add_argument(
        "--check",
        "-c",
        action="store_true",
        help="Check only; exit with code 1 if any environment is missing keys.",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Simulate migrations without modifying any files.",
    )
    parser.add_argument(
        "--path",
        "-p",
        type=str,
        default=str(Path(__file__).resolve().parent.parent.parent),
        help="Base repository directory path (default: repository root).",
    )

    args = parser.parse_args()
    base_dir = Path(args.path).resolve()
    exit_code = run_migration_suite(base_dir, dry_run=args.dry_run, check_only=args.check)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
