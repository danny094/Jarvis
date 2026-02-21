#!/usr/bin/env python3
"""
tools/validate_test_dataset.py — Commit C
==========================================
Validates all YAML test-case files in tests/datasets/cases/
against the JSON Schema in tests/datasets/schema/test_case.schema.json.

Usage:
    python tools/validate_test_dataset.py           # validate all
    python tools/validate_test_dataset.py --verbose # verbose output
    python tools/validate_test_dataset.py --tag smoke  # filter by tag

Exit codes:
    0  — all cases valid
    1  — schema violations or parse errors found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    import jsonschema
    from jsonschema import validate as _validate, ValidationError
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent  # tools/ is one level below root
_SCHEMA_PATH = _REPO_ROOT / "tests" / "datasets" / "schema" / "test_case.schema.json"
_CASES_DIR = _REPO_ROOT / "tests" / "datasets" / "cases"


# ─────────────────────────────────────────────────────────────────────────────
# Load helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_schema() -> Dict:
    if not _SCHEMA_PATH.exists():
        print(f"ERROR: Schema not found at {_SCHEMA_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(_SCHEMA_PATH) as f:
        return json.load(f)


def load_yaml_file(path: Path) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """Load a YAML dataset file. Returns (cases_list, error_string)."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return None, f"Top-level must be a mapping, got {type(data).__name__}"
        cases = data.get("cases")
        if not isinstance(cases, list):
            return None, "'cases' key must be a list"
        return cases, None
    except yaml.YAMLError as e:
        return None, f"YAML parse error: {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_case(case: Dict, schema: Dict) -> Optional[str]:
    """Validate a single case dict against the schema. Returns error string or None."""
    try:
        _validate(instance=case, schema=schema)
        return None
    except ValidationError as e:
        return f"{e.message} (path: {'.'.join(str(p) for p in e.absolute_path) or 'root'})"


def validate_all(
    cases_dir: Path,
    schema: Dict,
    tag_filter: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[int, int, int]:
    """
    Validate all YAML files in cases_dir.

    Returns (total_cases, passed, failed).
    Prints errors to stderr.
    """
    yaml_files = sorted(cases_dir.glob("*.yaml")) + sorted(cases_dir.glob("*.yml"))
    if not yaml_files:
        print(f"WARNING: No YAML files found in {cases_dir}", file=sys.stderr)
        return 0, 0, 0

    total = passed = failed = 0
    seen_ids = {}  # id → file path for duplicate detection

    for path in yaml_files:
        if verbose:
            print(f"\n[{path.name}]")

        cases, err = load_yaml_file(path)
        if err:
            print(f"  ERROR loading {path.name}: {err}", file=sys.stderr)
            failed += 1
            continue

        for case in cases:
            case_id = case.get("id", "(no-id)")
            tags = case.get("tags", [])

            # Tag filter
            if tag_filter and tag_filter not in tags:
                continue

            total += 1

            # Duplicate ID check
            if case_id in seen_ids:
                print(
                    f"  ERROR [{path.name}] id={case_id!r} already defined in {seen_ids[case_id]}",
                    file=sys.stderr,
                )
                failed += 1
                continue
            seen_ids[case_id] = path.name

            # Schema validation
            schema_err = validate_case(case, schema)
            if schema_err:
                print(
                    f"  FAIL [{path.name}] id={case_id!r}: {schema_err}",
                    file=sys.stderr,
                )
                failed += 1
            else:
                passed += 1
                if verbose:
                    print(f"  OK   {case_id} ({case.get('title', '')[:60]})")

    return total, passed, failed


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate TRION test dataset files against JSON Schema."
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--tag", help="Only validate cases with this tag")
    parser.add_argument(
        "--cases-dir",
        default=str(_CASES_DIR),
        help=f"Cases directory (default: {_CASES_DIR})",
    )
    args = parser.parse_args()

    cases_dir = Path(args.cases_dir)
    if not cases_dir.exists():
        print(f"ERROR: Cases dir not found: {cases_dir}", file=sys.stderr)
        return 1

    schema = load_schema()
    total, passed, failed = validate_all(
        cases_dir, schema, tag_filter=args.tag, verbose=args.verbose
    )

    # Summary
    tag_note = f" (tag={args.tag!r})" if args.tag else ""
    if failed:
        print(
            f"\nDataset validation FAILED{tag_note}: "
            f"{failed}/{total} case(s) invalid, {passed} passed.",
            file=sys.stderr,
        )
        return 1

    if total == 0:
        print(f"WARNING: No cases found{tag_note}.", file=sys.stderr)
        return 0

    print(f"Dataset OK{tag_note}: {passed}/{total} case(s) valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
