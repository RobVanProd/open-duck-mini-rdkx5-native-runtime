from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
MANIFEST = ARTIFACTS / "manifest.sha256"
RAW_SUFFIXES = {".jsonl", ".log", ".csv"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reviewed_artifact_files() -> list[Path]:
    return sorted(
        path
        for path in ARTIFACTS.rglob("*")
        if path.is_file()
        and path != MANIFEST
        and path.name != ".gitkeep"
        and path.suffix.lower() not in RAW_SUFFIXES
    )


def write_manifest() -> int:
    files = reviewed_artifact_files()
    lines = [f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}" for path in files]
    content = "\n".join(lines) + ("\n" if lines else "")
    MANIFEST.write_bytes(content.encode("utf-8"))
    print(f"wrote {MANIFEST.relative_to(ROOT)} with {len(lines)} entries")
    return 0


def check_manifest() -> int:
    failures = 0
    listed: set[str] = set()
    for line_number, line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
        try:
            expected, relative = line.split("  ", 1)
        except ValueError:
            print(f"FAIL line {line_number}: malformed manifest entry")
            failures += 1
            continue
        listed.add(relative)
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            print(f"FAIL {relative}: missing or outside repository")
            failures += 1
            continue
        actual = sha256(path)
        if actual != expected:
            print(f"FAIL {relative}: expected {expected}, got {actual}")
            failures += 1
        else:
            print(f"OK   {relative}")
    expected = {path.relative_to(ROOT).as_posix() for path in reviewed_artifact_files()}
    for relative in sorted(expected - listed):
        print(f"FAIL {relative}: reviewed artifact is absent from manifest")
        failures += 1
    for relative in sorted(listed - expected):
        print(f"FAIL {relative}: manifest entry is not a reviewed artifact")
        failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify reviewed artifact hashes")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check_manifest() if args.check else write_manifest()


if __name__ == "__main__":
    raise SystemExit(main())
