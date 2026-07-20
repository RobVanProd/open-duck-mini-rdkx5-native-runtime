#!/usr/bin/env python3
"""Regenerate only the reduced winner-v2 report from the frozen full result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from open_duck_x5.winner_v2_verifier import (
    RECURSIVE_PREREGISTRATION_COMMIT,
    reduce_recursive_result,
)

EXPECTED_FULL_RESULT_SHA256 = (
    "e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14"
)
EXPECTED_FULL_SCHEMA = "open_duck_x5.winner_v2_offline_verification.v2"
EXPECTED_DECISION = "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE"


def reduce_frozen_result(input_path: Path) -> dict[str, object]:
    payload = input_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_FULL_RESULT_SHA256:
        raise ValueError("formal full-result SHA-256 changed")
    result = json.loads(payload)
    if result.get("schema_version") != EXPECTED_FULL_SCHEMA:
        raise ValueError("formal full-result schema changed")
    if result.get("status") != EXPECTED_DECISION:
        raise ValueError("formal full-result decision changed")
    preregistration = result.get("recursive_preregistration", {})
    if preregistration.get("commit") != RECURSIVE_PREREGISTRATION_COMMIT:
        raise ValueError("formal preregistration identity changed")
    if preregistration.get("formal_prior_runtime_outcome_weight") is not False:
        raise ValueError("formal pre-outcome authority changed")
    return reduce_recursive_result(result, full_result_sha256=digest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reduced = reduce_frozen_result(args.full_result)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"winner-v2 reduced-result generation failed: {exc}")
        return 2
    payload = json.dumps(reduced, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
