from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigError, DuckConfig
from .constants import (
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTRACT_ID,
    CONTROL_FREQUENCY_HZ,
    ENVELOPE_MONITOR_RAD_S,
    HOME_RAD,
    JOINT_NAMES,
    LEGACY_TARGET_RATE_LIMIT_RAD_S,
    OBSERVATION_DIM,
    PHASE_PERIOD_TICKS,
    SERVO_IDS,
)
from .contract_snapshot import OBSERVATION_FIELD_LABELS, verify_contract_snapshot
from .hardware_guard import (
    HardwareAuthorizationError,
    add_hardware_ack_arguments,
    require_hardware_authorization,
)
from .legacy_contract import extract_contract_snapshot
from .policy import ONNX_SESSION_CONTRACT

SCHEMA_VERSION = "open_duck_x5.duck_evidence_bundle.v1"
COLLECTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_HASH_BYTES = 512 * 1024 * 1024
MAX_INCLUDED_TELEMETRY_BYTES = 32 * 1024 * 1024
MAX_LEGACY_SOURCE_FILES = 2_000
MAX_LEGACY_SOURCE_BYTES = 24 * 1024 * 1024
LEGACY_SOURCE_SUFFIXES = {".py", ".pyi", ".sh", ".toml", ".yaml", ".yml", ".md"}
SKIPPED_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "logs",
    "models",
    "node_modules",
    "venv",
}
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    rb"(?im)^\s*(?:export\s+)?[A-Za-z0-9_]*(?:api[_-]?key|password|secret|token)"
    rb"[A-Za-z0-9_]*\s*[:=]"
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    argv: tuple[str, ...]
    timeout_s: float = 10.0


@dataclass(frozen=True, slots=True)
class CommandResult:
    name: str
    argv: tuple[str, ...]
    return_code: int | None
    timed_out: bool
    error: str | None
    output_file: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect a local, hashed X5/runtime evidence bundle without moving the robot"
        )
    )
    parser.add_argument("--output-dir", type=Path, default=Path.home() / "duck-evidence")
    parser.add_argument("--collection-id")
    parser.add_argument("--legacy-root", type=Path, default=Path("/home/sunrise/project"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--include-telemetry", type=Path, action="append", default=[])
    parser.add_argument("--telemetry-scan-lines", type=int, default=100_000)
    parser.add_argument("--max-telemetry-files", type=int, default=200)
    parser.add_argument("--serial-device", default="/dev/ttyS1")
    parser.add_argument("--baudrate", type=int, default=1_000_000)
    parser.add_argument("--timeout-ms", type=float, default=4.0)
    parser.add_argument("--servo-id", type=int, choices=SERVO_IDS, default=SERVO_IDS[0])
    parser.add_argument("--gate1-ticks", type=int, default=10_000)
    parser.add_argument("--include-gate1", action="store_true")
    parser.add_argument("--notes")
    add_hardware_ack_arguments(parser)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def run_command(spec: CommandSpec, output_root: Path) -> CommandResult:
    output_file = output_root / "commands" / f"{spec.name}.txt"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    return_code: int | None = None
    timed_out = False
    error = None
    stdout = ""
    stderr = ""
    try:
        environment = dict(os.environ)
        environment.update({"LC_ALL": "C", "LANG": "C"})
        completed = subprocess.run(
            spec.argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_s,
            check=False,
            env=environment,
        )
        return_code = int(completed.returncode)
        stdout = completed.stdout
        stderr = completed.stderr
    except FileNotFoundError as exc:
        error = f"command not installed: {exc.filename}"
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        error = f"command exceeded {spec.timeout_s:.1f} seconds"
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    except OSError as exc:
        error = f"command failed to start: {type(exc).__name__}: {exc}"

    rendered = [
        f"argv_json={json.dumps(spec.argv)}",
        f"return_code={return_code}",
        f"timed_out={str(timed_out).lower()}",
        f"error={error or ''}",
        "[stdout]",
        stdout,
        "[stderr]",
        stderr,
    ]
    output_file.write_text("\n".join(rendered), encoding="utf-8", newline="\n")
    return CommandResult(
        name=spec.name,
        argv=spec.argv,
        return_code=return_code,
        timed_out=timed_out,
        error=error,
        output_file=_relative(output_file, output_root),
    )


def _command_specs(legacy_root: Path, serial_device: str) -> list[CommandSpec]:
    runtime_root = Path(__file__).resolve().parents[2]
    specs = [
        CommandSpec("uname", ("uname", "-a")),
        CommandSpec("lscpu", ("lscpu",)),
        CommandSpec("usb_devices", ("lsusb",)),
        CommandSpec("usb_tree", ("lsusb", "-t")),
        # List adapters only. Deliberately never run an active `i2cdetect -y` scan.
        CommandSpec("i2c_adapters", ("i2cdetect", "-l")),
        CommandSpec("gpio_inventory", ("gpioinfo",)),
        CommandSpec("identity", ("id",)),
        CommandSpec("process_schedulers", ("ps", "-eo", "pid,cls,rtprio,psr,comm")),
        CommandSpec("mount_root", ("findmnt", "-no", "SOURCE,FSTYPE,OPTIONS", "/")),
        CommandSpec("python_version", (sys.executable, "--version")),
        # Package names and versions only. `pip freeze` can echo credential-bearing URLs.
        CommandSpec(
            "python_packages",
            (sys.executable, "-m", "pip", "list", "--format=json"),
            30.0,
        ),
        CommandSpec("python_capabilities", ("getcap", sys.executable)),
        CommandSpec("serial_in_use", ("fuser", serial_device)),
        CommandSpec(
            "serial_udev",
            ("udevadm", "info", "--query=all", f"--name={serial_device}"),
        ),
    ]
    if (runtime_root / ".git").exists():
        specs.extend(
            [
                CommandSpec(
                    "collector_git_head",
                    ("git", "-C", str(runtime_root), "rev-parse", "HEAD"),
                ),
                CommandSpec(
                    "collector_git_status",
                    ("git", "-C", str(runtime_root), "status", "--short", "--branch"),
                ),
            ]
        )
    if (legacy_root / ".git").exists():
        specs.extend(
            [
                CommandSpec(
                    "legacy_git_head", ("git", "-C", str(legacy_root), "rev-parse", "HEAD")
                ),
                CommandSpec(
                    "legacy_git_status",
                    ("git", "-C", str(legacy_root), "status", "--short", "--branch"),
                ),
                CommandSpec(
                    "legacy_git_diff_stat",
                    ("git", "-C", str(legacy_root), "diff", "--stat"),
                ),
            ]
        )
    return specs


def _capture_file(source: Path, destination: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "source": str(source),
        "output_file": _relative(destination, destination.parents[1]),
        "captured": False,
        "truncated": False,
        "error": None,
    }
    try:
        with source.open("rb") as handle:
            data = handle.read(MAX_CAPTURE_BYTES + 1)
        if len(data) > MAX_CAPTURE_BYTES:
            data = data[:MAX_CAPTURE_BYTES]
            result["truncated"] = True
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        result["captured"] = True
        result["bytes"] = len(data)
        result["sha256"] = hashlib.sha256(data).hexdigest()
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _system_file_specs() -> tuple[tuple[Path, str], ...]:
    return (
        (Path("/etc/os-release"), "system/os-release.txt"),
        (Path("/etc/board-release"), "system/board-release.txt"),
        (Path("/etc/hobot-release"), "system/hobot-release.txt"),
        (Path("/proc/version"), "system/proc-version.txt"),
        (Path("/proc/device-tree/model"), "hardware/device-tree-model.txt"),
        (Path("/proc/device-tree/compatible"), "hardware/device-tree-compatible.bin"),
        (Path("/proc/cmdline"), "realtime/kernel-cmdline.txt"),
        (Path("/proc/interrupts"), "realtime/interrupts.txt"),
        (Path("/proc/tty/driver/serial"), "hardware/proc-serial.txt"),
        (Path("/sys/devices/system/cpu/present"), "realtime/cpu-present.txt"),
        (Path("/sys/devices/system/cpu/online"), "realtime/cpu-online.txt"),
        (Path("/sys/devices/system/cpu/isolated"), "realtime/cpu-isolated.txt"),
        (Path("/sys/devices/system/cpu/nohz_full"), "realtime/cpu-nohz-full.txt"),
        (Path("/sys/devices/system/cpu/rcu_nocbs"), "realtime/cpu-rcu-nocbs.txt"),
        (Path("/sys/kernel/realtime"), "realtime/preempt-rt.txt"),
        (
            Path("/proc/sys/kernel/sched_rt_runtime_us"),
            "realtime/sched-rt-runtime-us.txt",
        ),
        (
            Path("/proc/sys/kernel/sched_rt_period_us"),
            "realtime/sched-rt-period-us.txt",
        ),
    )


def _clock_and_bus_inventory() -> dict[str, object]:
    cpu_frequencies: list[dict[str, object]] = []
    for cpu_path in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
        frequency_path = cpu_path / "cpufreq"
        entry: dict[str, object] = {"cpu": cpu_path.name, "cpufreq_exists": frequency_path.exists()}
        for name in (
            "scaling_driver",
            "scaling_governor",
            "scaling_available_governors",
            "scaling_cur_freq",
            "scaling_min_freq",
            "scaling_max_freq",
            "cpuinfo_min_freq",
            "cpuinfo_max_freq",
        ):
            path = frequency_path / name
            if not path.is_file():
                continue
            try:
                entry[name] = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:
                entry[f"{name}_error"] = f"{type(exc).__name__}: {exc}"
        cpu_frequencies.append(entry)

    i2c_adapters: list[dict[str, object]] = []
    seen_adapters: set[str] = set()
    # Mainline systems commonly expose /sys/class/i2c-adapter. The RDK-X5
    # 6.1 image instead exposes the same adapters through i2c-dev and the bus
    # device tree, even though `i2cdetect -l` reports them normally.
    for root in (
        Path("/sys/class/i2c-adapter"),
        Path("/sys/class/i2c-dev"),
        Path("/sys/bus/i2c/devices"),
    ):
        for adapter in sorted(root.glob("i2c-*")):
            if adapter.name in seen_adapters:
                continue
            seen_adapters.add(adapter.name)
            entry: dict[str, object] = {"path": str(adapter)}
            try:
                entry["realpath"] = str(adapter.resolve())
                name_path = adapter / "name"
                if not name_path.is_file():
                    name_path = adapter / "device" / "name"
                if name_path.is_file():
                    entry["name"] = name_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
            except OSError as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            i2c_adapters.append(entry)
    return {"cpu_frequency": cpu_frequencies, "i2c_adapters": i2c_adapters}


def _host_metadata() -> dict[str, object]:
    scheduler: dict[str, object] = {}
    if hasattr(os, "sched_getaffinity"):
        try:
            scheduler["affinity"] = sorted(os.sched_getaffinity(0))
            scheduler["policy"] = int(os.sched_getscheduler(0))
            scheduler["priority"] = int(os.sched_getparam(0).sched_priority)
        except OSError as exc:
            scheduler["error"] = f"{type(exc).__name__}: {exc}"
    limits: dict[str, object] = {}
    try:
        import resource

        for name in ("RLIMIT_RTPRIO", "RLIMIT_MEMLOCK"):
            limit_id = getattr(resource, name, None)
            if limit_id is not None:
                limits[name] = list(resource.getrlimit(limit_id))
    except (ImportError, OSError, ValueError) as exc:
        limits["error"] = f"{type(exc).__name__}: {exc}"
    monotonic = time.get_clock_info("monotonic")
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "python_executable": sys.executable,
        "cpu_count": os.cpu_count(),
        "scheduler": scheduler,
        "resource_limits": limits,
        "monotonic_clock": {
            "implementation": monotonic.implementation,
            "resolution_s": monotonic.resolution,
            "monotonic": monotonic.monotonic,
            "adjustable": monotonic.adjustable,
        },
    }


def _collector_identity() -> dict[str, object]:
    source_file = Path(__file__).resolve()
    runtime_root = source_file.parents[2]
    return {
        "runtime_root": str(runtime_root),
        "source_file": str(source_file),
        "source_sha256": _sha256(source_file),
        "schema_version": SCHEMA_VERSION,
    }


def _python_environment() -> dict[str, object]:
    packages = {
        "numpy": "numpy",
        "pyserial": "serial",
        "onnxruntime": "onnxruntime",
        "rustypot": "rustypot",
        "pypot": "pypot",
        "smbus2": "smbus2",
        "pygame": "pygame",
    }
    versions: dict[str, str | None] = {}
    locations: dict[str, dict[str, object]] = {}
    for package, module_name in packages.items():
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError) as exc:
            locations[package] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        if spec is None:
            locations[package] = {"found": False}
            continue
        origin = None if spec.origin in (None, "built-in", "frozen") else Path(spec.origin)
        entry: dict[str, object] = {
            "found": True,
            "origin": str(origin) if origin else spec.origin,
            "search_locations": list(spec.submodule_search_locations or ()),
        }
        if origin is not None and origin.is_file():
            try:
                size = origin.stat().st_size
                entry["origin_size"] = size
                entry["origin_sha256"] = _sha256(origin) if size <= MAX_HASH_BYTES else None
            except OSError as exc:
                entry["origin_error"] = f"{type(exc).__name__}: {exc}"
        locations[package] = entry
    return {
        "versions": versions,
        "module_locations": locations,
        "sys_path": list(sys.path),
    }


def _serial_inventory(device: str) -> dict[str, object]:
    device_path = Path(device)
    entries: list[dict[str, object]] = []
    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        for path in sorted(Path("/dev").glob(Path(pattern).name)):
            try:
                details = path.stat()
                entries.append(
                    {
                        "path": str(path),
                        "realpath": str(path.resolve()),
                        "mode": stat.filemode(details.st_mode),
                        "uid": details.st_uid,
                        "gid": details.st_gid,
                    }
                )
            except OSError as exc:
                entries.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    by_id: list[dict[str, str]] = []
    by_id_root = Path("/dev/serial/by-id")
    if by_id_root.exists():
        for path in sorted(by_id_root.iterdir()):
            try:
                by_id.append({"path": str(path), "target": str(path.resolve())})
            except OSError as exc:
                by_id.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})

    tty_name = device_path.name
    tty_class = Path("/sys/class/tty") / tty_name
    sysfs: dict[str, object] = {"tty_class": str(tty_class), "exists": tty_class.exists()}
    if tty_class.exists():
        try:
            resolved_device = (tty_class / "device").resolve()
            sysfs["resolved_device"] = str(resolved_device)
            driver = resolved_device / "driver"
            sysfs["driver"] = str(driver.resolve()) if driver.exists() else None
            attributes: dict[str, str] = {}
            names = (
                "latency_timer",
                "uevent",
                "manufacturer",
                "product",
                "serial",
                "idVendor",
                "idProduct",
                "bInterfaceClass",
                "power/control",
            )
            locations = [resolved_device, *list(resolved_device.parents)[:4]]
            for location in locations:
                for name in names:
                    candidate = location / name
                    if candidate.is_file():
                        try:
                            attributes[str(candidate)] = candidate.read_text(
                                encoding="utf-8", errors="replace"
                            ).strip()
                        except OSError as exc:
                            attributes[str(candidate)] = f"ERROR: {type(exc).__name__}: {exc}"
            sysfs["attributes"] = attributes
        except OSError as exc:
            sysfs["error"] = f"{type(exc).__name__}: {exc}"
    return {
        "requested_device": device,
        "requested_exists": device_path.exists(),
        "tty_devices": entries,
        "serial_by_id": by_id,
        "sysfs": sysfs,
    }


def _find_contract_configs(root: Path, limit: int = 300) -> list[Path]:
    if not root.is_dir():
        return []
    matches: list[Path] = []
    for index, path in enumerate(sorted(root.rglob("*.json"))):
        if index >= limit:
            break
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("joints_offsets"), dict):
                matches.append(path)
        except (OSError, json.JSONDecodeError, UnicodeError):
            continue
    return matches


def _is_legacy_source(relative: Path) -> bool:
    if any(
        part in SKIPPED_DIRECTORY_NAMES or part.startswith("duck-evidence")
        for part in relative.parts[:-1]
    ):
        return False
    if relative.name in {
        "AGENTS.md",
        "Dockerfile",
        "Makefile",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
    }:
        return True
    return relative.suffix.lower() in LEGACY_SOURCE_SUFFIXES


def _legacy_source_evidence(legacy_root: Path, output_root: Path) -> dict[str, object]:
    """Copy bounded, reviewable legacy source while refusing likely credential files."""

    if not legacy_root.is_dir():
        return {
            "available": False,
            "copied_files": 0,
            "copied_bytes": 0,
            "entries": [],
            "truncated": False,
        }
    entries: list[dict[str, object]] = []
    copied_files = 0
    copied_bytes = 0
    truncated = False
    for path in sorted(legacy_root.rglob("*")):
        try:
            relative = path.relative_to(legacy_root)
            if path.is_symlink() or not path.is_file() or not _is_legacy_source(relative):
                continue
            if path.resolve().is_relative_to(output_root.resolve()):
                continue
            size = path.stat().st_size
            if size > MAX_CAPTURE_BYTES:
                entries.append(
                    {
                        "source": str(path),
                        "relative_path": relative.as_posix(),
                        "size": size,
                        "copied": False,
                        "reason": "file exceeds per-file capture limit",
                    }
                )
                continue
            if copied_files >= MAX_LEGACY_SOURCE_FILES or (
                copied_bytes + size > MAX_LEGACY_SOURCE_BYTES
            ):
                truncated = True
                break
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if SENSITIVE_ASSIGNMENT_PATTERN.search(data):
                entries.append(
                    {
                        "source": str(path),
                        "relative_path": relative.as_posix(),
                        "size": size,
                        "sha256": digest,
                        "copied": False,
                        "reason": "possible credential assignment; review on the duck",
                    }
                )
                continue
            destination = output_root / "legacy" / "source" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            copied_files += 1
            copied_bytes += size
            entries.append(
                {
                    "source": str(path),
                    "relative_path": relative.as_posix(),
                    "output_file": _relative(destination, output_root),
                    "size": size,
                    "sha256": digest,
                    "copied": True,
                }
            )
        except (OSError, ValueError) as exc:
            entries.append(
                {
                    "source": str(path),
                    "copied": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return {
        "available": True,
        "copied_files": copied_files,
        "copied_bytes": copied_bytes,
        "file_limit": MAX_LEGACY_SOURCE_FILES,
        "byte_limit": MAX_LEGACY_SOURCE_BYTES,
        "entries": entries,
        "truncated": truncated,
    }


def _config_evidence(
    legacy_root: Path,
    requested: Path | None,
    output_root: Path,
) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    candidates = _find_contract_configs(legacy_root)
    home_candidate = Path.home() / "duck_config.json"
    if home_candidate.is_file() and home_candidate not in candidates:
        candidates.append(home_candidate)
    if requested is not None:
        if not requested.is_file():
            raise ValueError(f"requested duck config does not exist: {requested}")
        selected = requested
        if selected not in candidates:
            candidates.append(selected)
    elif len(candidates) == 1:
        selected = candidates[0]
    else:
        selected = None
        if not candidates:
            warnings.append("no duck_config candidate was found; rerun with --config")
        else:
            warnings.append("multiple duck_config candidates found; rerun with --config")

    evidence: dict[str, object] = {
        "requested": str(requested) if requested else None,
        "selected": str(selected) if selected else None,
        "candidates": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in sorted(candidates)
        ],
        "validated": False,
        "validation_error": None,
    }
    if selected is not None:
        copied = output_root / "legacy" / "duck_config.json"
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(selected, copied)
        evidence["copied_to"] = _relative(copied, output_root)
        try:
            config = DuckConfig.load(selected)
            evidence["validated"] = True
            evidence["semantics"] = {
                "start_paused": config.start_paused,
                "imu_upside_down": config.imu_upside_down,
                "phase_frequency_factor_offset": config.phase_frequency_factor_offset,
                "joints_offsets": config.joints_offsets,
            }
        except ConfigError as exc:
            evidence["validation_error"] = str(exc)
            warnings.append(f"selected duck config failed frozen validation: {exc}")
    return evidence, warnings


def _policy_metadata(path: Path) -> dict[str, object]:
    evidence: dict[str, object] = {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "onnxruntime_loaded": False,
        "interface": None,
        "interface_compatible": False,
        "interface_status": "UNVERIFIED",
        "interface_issues": [],
        "load_error": None,
    }
    try:
        import onnxruntime as ort

        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        evidence["onnxruntime_loaded"] = True
        interface = {
            "inputs": [
                {"name": value.name, "shape": list(value.shape), "type": value.type}
                for value in session.get_inputs()
            ],
            "outputs": [
                {"name": value.name, "shape": list(value.shape), "type": value.type}
                for value in session.get_outputs()
            ],
        }
        issues: list[str] = []
        expected_input = {"name": "obs", "shape": [1, OBSERVATION_DIM], "type": "tensor(float)"}
        expected_output = {
            "name": "continuous_actions",
            "shape": [1, ACTION_DIM],
            "type": "tensor(float)",
        }
        if interface["inputs"] != [expected_input]:
            issues.append(
                f"expected exactly {expected_input!r}, got {interface['inputs']!r}"
            )
        if interface["outputs"] != [expected_output]:
            issues.append(
                f"expected exactly {expected_output!r}, got {interface['outputs']!r}"
            )
        evidence["interface"] = interface
        evidence["interface_issues"] = issues
        evidence["interface_compatible"] = not issues
        evidence["interface_status"] = "PASS" if not issues else "FAIL"
    except Exception as exc:
        evidence["load_error"] = f"{type(exc).__name__}: {exc}"
    return evidence


def _policy_evidence(
    legacy_root: Path, requested: Path | None
) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    candidates = sorted(legacy_root.rglob("*.onnx"))[:100] if legacy_root.is_dir() else []
    if requested is not None:
        if not requested.is_file():
            raise ValueError(f"requested policy does not exist: {requested}")
        selected = requested
        if selected not in candidates:
            candidates.append(selected)
    elif len(candidates) == 1:
        selected = candidates[0]
    else:
        selected = None
        if not candidates:
            warnings.append("no ONNX policy was found; rerun with --policy if stored elsewhere")
        else:
            warnings.append("multiple ONNX policies found; rerun with --policy for exact metadata")
    summaries: list[dict[str, object]] = []
    for path in sorted(candidates):
        size = path.stat().st_size
        summaries.append(
            {
                "path": str(path),
                "size": size,
                "sha256": _sha256(path) if size <= MAX_HASH_BYTES else None,
                "hash_skipped": size > MAX_HASH_BYTES,
            }
        )
    evidence: dict[str, object] = {
        "requested": str(requested) if requested else None,
        "selected": str(selected) if selected else None,
        "candidates": summaries,
        "selected_metadata": _policy_metadata(selected) if selected else None,
        "policy_binary_copied": False,
    }
    selected_metadata = evidence["selected_metadata"]
    if isinstance(selected_metadata, dict):
        status = selected_metadata.get("interface_status")
        if status == "FAIL":
            warnings.append(
                "selected ONNX interface is incompatible with the frozen 101/14 runtime contract"
            )
        elif status == "UNVERIFIED":
            warnings.append("selected ONNX interface could not be verified with ONNX Runtime")
    return evidence, warnings


def _contract_handoff(
    config: dict[str, object], policy: dict[str, object]
) -> dict[str, object]:
    selected_metadata = policy.get("selected_metadata")
    if not isinstance(selected_metadata, dict):
        policy_status = "NOT_CHECKED"
        policy_issues = ["no single ONNX policy was selected"]
    elif selected_metadata.get("interface_compatible") is True:
        policy_status = "PASS"
        policy_issues = []
    elif selected_metadata.get("interface_status") == "FAIL":
        policy_status = "BLOCKED"
        policy_issues = list(selected_metadata.get("interface_issues", []))
    else:
        policy_status = "UNVERIFIED"
        policy_issues = [str(selected_metadata.get("load_error") or "interface not verified")]

    return {
        "schema_version": "open_duck_x5.policy_handoff.v1",
        "contract_id": CONTRACT_ID,
        "deployment_clearance_granted": False,
        "runtime_contract": {
            "control_frequency_hz": CONTROL_FREQUENCY_HZ,
            "tick_period_ms": 1000.0 / CONTROL_FREQUENCY_HZ,
            "onnx_input": {
                "name": "obs",
                "shape": [1, OBSERVATION_DIM],
                "type": "tensor(float)",
            },
            "onnx_output": {
                "name": "continuous_actions",
                "shape": [1, ACTION_DIM],
                "type": "tensor(float)",
            },
            "onnx_session": dict(ONNX_SESSION_CONTRACT),
            "normalization_location": "inside ONNX graph",
            "action_scale_rad": ACTION_SCALE_RAD,
            "target_rate_limit_rad_s": LEGACY_TARGET_RATE_LIMIT_RAD_S,
            "telemetry_envelope_rad_s": ENVELOPE_MONITOR_RAD_S,
            "phase_period_ticks": PHASE_PERIOD_TICKS,
            "observation_fields": [
                {"index": index, "label": label}
                for index, label in enumerate(OBSERVATION_FIELD_LABELS)
            ],
            "observation_slot_83_97": {
                "slice": [83, 97],
                "meaning": (
                    "previous absolute logical motor target after inherited slew limit "
                    "and head overlay"
                ),
                "quantity_class": "post-slew commanded target",
            },
            "target_quantity_map": [
                {
                    "quantity": 1,
                    "name": "unlimited logical target",
                    "formula": "HOME_RAD + action * 0.25",
                    "observation_slot": None,
                },
                {
                    "quantity": 2,
                    "name": "post-slew post-head commanded logical target",
                    "formula": "slew(unlimited, 5.24 rad/s) + head overlay",
                    "observation_slot": [83, 97],
                },
                {
                    "quantity": 3,
                    "name": "measured present logical position",
                    "formula": "physical servo read - soft offset",
                    "observation_slot": [13, 27],
                    "slot_transform": "minus HOME_RAD",
                },
            ],
            "actions": [
                {
                    "index": index,
                    "joint": JOINT_NAMES[index],
                    "servo_id": SERVO_IDS[index],
                    "home_rad": float(HOME_RAD[index]),
                }
                for index in range(ACTION_DIM)
            ],
        },
        "duck_config": {
            "selected": config.get("selected"),
            "validated": config.get("validated"),
            "copied_to": config.get("copied_to"),
        },
        "candidate_policy": {
            "selected": policy.get("selected"),
            "binary_copied": policy.get("policy_binary_copied"),
            "interface_status": policy_status,
            "issues": policy_issues,
            "metadata": selected_metadata,
        },
        "semantic_compatibility": {
            "status": "PENDING_EVIDENCE",
            "blocks_policy_hardware_gate": True,
            "questions": [
                {
                    "id": "winning_policy_applied_target_definition",
                    "question": (
                        "Does training obs[83:97] mean the post-slew/post-bridge commanded "
                        "target, or a bridge-realized/measured actuator state?"
                    ),
                    "runtime_definition": (
                        "target quantity 2 in runtime_contract.target_quantity_map"
                    ),
                },
                {
                    "id": "phase_sample_order",
                    "question": (
                        "Does training construct the observation before or after advancing the "
                        "27-tick phase clock?"
                    ),
                    "runtime_definition": "build observation, then advance phase for the next tick",
                },
                {
                    "id": "slew_limit_training_parity",
                    "question": (
                        "Was the candidate trained and exported with the frozen 5.24 rad/s "
                        "target slew semantics?"
                    ),
                    "runtime_definition_rad_s": LEGACY_TARGET_RATE_LIMIT_RAD_S,
                },
            ],
            "required_resolution": (
                "compare the winning policy training observation construction and an adjacent "
                "board golden-vector capture field by field"
            ),
        },
    }


def _inspect_telemetry(
    path: Path,
    *,
    scan_lines: int,
) -> tuple[dict[str, object], dict[str, object] | None]:
    size = path.stat().st_size
    schemas: Counter[str] = Counter()
    sampled_lines = 0
    invalid_json_lines = 0
    minimum_tick: int | None = None
    maximum_tick: int | None = None
    previous_legacy: dict[str, Any] | None = None
    snapshot: dict[str, object] | None = None
    contract_errors: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if sampled_lines >= scan_lines:
                break
            if not line.strip():
                continue
            sampled_lines += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json_lines += 1
                continue
            if not isinstance(record, dict):
                continue
            schema = str(record.get("schema_version", "missing"))
            schemas[schema] += 1
            tick = record.get("tick")
            if isinstance(tick, int):
                minimum_tick = tick if minimum_tick is None else min(minimum_tick, tick)
                maximum_tick = tick if maximum_tick is None else max(maximum_tick, tick)
            if schema != "sim2real.telemetry.v1" or snapshot is not None:
                continue
            if previous_legacy is not None:
                try:
                    snapshot = extract_contract_snapshot(
                        previous_legacy,
                        record,
                        source=str(path),
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    if len(contract_errors) < 5:
                        contract_errors.append(str(exc))
            previous_legacy = record
    return (
        {
            "path": str(path),
            "size": size,
            "sha256": _sha256(path) if size <= MAX_HASH_BYTES else None,
            "hash_skipped": size > MAX_HASH_BYTES,
            "sampled_lines": sampled_lines,
            "scan_truncated": sampled_lines >= scan_lines,
            "invalid_json_lines": invalid_json_lines,
            "schema_counts": dict(sorted(schemas.items())),
            "minimum_tick": minimum_tick,
            "maximum_tick": maximum_tick,
            "contract_snapshot_extracted": snapshot is not None,
            "contract_errors": contract_errors,
        },
        snapshot,
    )


def _telemetry_evidence(
    legacy_root: Path,
    included: list[Path],
    output_root: Path,
    *,
    scan_lines: int,
    max_files: int,
) -> tuple[dict[str, object], list[str]]:
    warnings: list[str] = []
    candidates = sorted(legacy_root.rglob("*.jsonl"))[:max_files] if legacy_root.is_dir() else []
    for path in included:
        if not path.is_file():
            raise ValueError(f"included telemetry does not exist: {path}")
        if path not in candidates:
            candidates.append(path)
    summaries: list[dict[str, object]] = []
    first_snapshot: dict[str, object] | None = None
    for path in sorted(candidates):
        try:
            summary, snapshot = _inspect_telemetry(path, scan_lines=scan_lines)
            summaries.append(summary)
            if first_snapshot is None and snapshot is not None:
                first_snapshot = snapshot
        except (OSError, UnicodeError) as exc:
            summaries.append(
                {"path": str(path), "error": f"{type(exc).__name__}: {exc}"}
            )
    copied: list[dict[str, object]] = []
    for index, path in enumerate(included):
        source_size = path.stat().st_size
        if source_size > MAX_INCLUDED_TELEMETRY_BYTES:
            copied.append(
                {
                    "source": str(path),
                    "copied": False,
                    "size": source_size,
                    "reason": "file exceeds bounded telemetry copy limit",
                }
            )
            warnings.append(
                f"explicit telemetry was summarized but not copied because it exceeds "
                f"{MAX_INCLUDED_TELEMETRY_BYTES} bytes: {path}"
            )
            continue
        destination = output_root / "legacy" / "included_telemetry" / f"{index:03d}-{path.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied.append(
            {
                "source": str(path),
                "copied": True,
                "output_file": _relative(destination, output_root),
                "size": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )
    snapshot_file = None
    report_file = None
    report_passed = None
    if first_snapshot is not None:
        destination = output_root / "legacy" / "contract_snapshot.json"
        _write_json(destination, first_snapshot)
        snapshot_file = _relative(destination, output_root)
        try:
            report = verify_contract_snapshot(first_snapshot)
            report["snapshot_sha256"] = _sha256(destination)
            report_destination = output_root / "legacy" / "contract_report.json"
            _write_json(report_destination, report)
            report_file = _relative(report_destination, output_root)
            report_passed = bool(report["passed"])
            if not report_passed:
                warnings.append(
                    "extracted legacy contract snapshot failed field-by-field verification"
                )
        except ValueError as exc:
            warnings.append(f"extracted legacy contract snapshot could not be verified: {exc}")
    elif candidates:
        warnings.append(
            "no valid adjacent sim2real.telemetry.v1 pair was found; "
            "golden contract evidence remains pending"
        )
    else:
        warnings.append("no JSONL telemetry was found under the legacy root")
    return (
        {
            "candidate_count": len(candidates),
            "candidate_limit_reached": len(candidates) >= max_files,
            "candidates": summaries,
            "explicitly_included": copied,
            "contract_snapshot_file": snapshot_file,
            "contract_report_file": report_file,
            "contract_report_passed": report_passed,
        },
        warnings,
    )


def _run_gate1(args: argparse.Namespace, output_root: Path) -> dict[str, object]:
    from argparse import Namespace

    from .single_servo_probe import run_probe

    gate_root = output_root / "gate1"
    probe_args = Namespace(
        bus="serial",
        device=args.serial_device,
        baudrate=args.baudrate,
        timeout_ms=args.timeout_ms,
        servo_id=args.servo_id,
        ticks=args.gate1_ticks,
        frequency_hz=50.0,
        watchdog_failures=2,
        output=gate_root / "single_servo_ticks.jsonl",
        summary=gate_root / "single_servo_summary.json",
        hardware_authorized=args.hardware_authorized,
        suspended_or_benched=args.suspended_or_benched,
    )
    return run_probe(probe_args)


def _manifest(output_root: Path) -> Path:
    manifest = output_root / "manifest.sha256"
    lines: list[str] = []
    for path in sorted(value for value in output_root.rglob("*") if value.is_file()):
        if path == manifest:
            continue
        lines.append(f"{_sha256(path)}  {path.relative_to(output_root).as_posix()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return manifest


def _archive(output_root: Path) -> tuple[Path, Path, str]:
    archive = output_root.parent / f"{output_root.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(output_root, arcname=output_root.name, recursive=True)
    digest = _sha256(archive)
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    return archive, sidecar, digest


def _validate_args(args: argparse.Namespace) -> None:
    if args.collection_id is not None and not COLLECTION_ID_PATTERN.fullmatch(
        args.collection_id
    ):
        raise ValueError("--collection-id may contain only letters, numbers, dot, dash, underscore")
    if args.collection_id in {".", ".."}:
        raise ValueError("--collection-id must name a new child directory")
    if args.telemetry_scan_lines < 2:
        raise ValueError("--telemetry-scan-lines must be at least 2")
    if args.max_telemetry_files < 1:
        raise ValueError("--max-telemetry-files must be positive")
    if args.baudrate <= 0 or args.timeout_ms <= 0:
        raise ValueError("baudrate and timeout must be positive")
    if args.servo_id not in SERVO_IDS:
        raise ValueError(f"--servo-id must be one of {SERVO_IDS}")
    if args.gate1_ticks < 2:
        raise ValueError("--gate1-ticks must be at least 2")
    for label, path in (("--config", args.config), ("--policy", args.policy)):
        if path is not None and not path.expanduser().is_file():
            raise ValueError(f"{label} file does not exist: {path}")
    for path in args.include_telemetry:
        if not path.expanduser().is_file():
            raise ValueError(f"--include-telemetry file does not exist: {path}")
    if args.include_gate1:
        require_hardware_authorization(
            hardware_authorized=args.hardware_authorized,
            suspended_or_benched=args.suspended_or_benched,
            operation="torque-off single-servo Gate 1 evidence collection",
        )


def collect_evidence(args: argparse.Namespace) -> dict[str, object]:
    _validate_args(args)
    collected_at = datetime.now(timezone.utc)
    collection_id = args.collection_id or collected_at.strftime("duck-evidence-%Y%m%dT%H%M%SZ")
    output_parent = args.output_dir.expanduser().resolve()
    output_root = output_parent / collection_id
    archive_path = output_parent / f"{collection_id}.tar.gz"
    sidecar_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    existing_outputs = [path for path in (output_root, archive_path, sidecar_path) if path.exists()]
    if existing_outputs:
        raise ValueError(f"evidence output already exists: {existing_outputs[0]}")
    output_root.mkdir(parents=True)

    warnings: list[str] = []
    legacy_root = args.legacy_root.expanduser().resolve()
    config_requested = args.config.expanduser().resolve() if args.config else None
    policy_requested = args.policy.expanduser().resolve() if args.policy else None
    included_telemetry = [path.expanduser().resolve() for path in args.include_telemetry]
    if not legacy_root.is_dir():
        warnings.append(f"legacy root does not exist: {legacy_root}")

    command_results = [
        run_command(spec, output_root)
        for spec in _command_specs(legacy_root, args.serial_device)
    ]
    captured_files = [
        _capture_file(source, output_root / relative)
        for source, relative in _system_file_specs()
    ]
    serial_inventory = _serial_inventory(args.serial_device)
    _write_json(output_root / "hardware" / "serial_inventory.json", serial_inventory)
    clock_and_bus_inventory = _clock_and_bus_inventory()
    _write_json(
        output_root / "hardware" / "clock_and_bus_inventory.json",
        clock_and_bus_inventory,
    )
    python_environment = _python_environment()
    _write_json(output_root / "system" / "python_environment.json", python_environment)

    config, config_warnings = _config_evidence(legacy_root, config_requested, output_root)
    policy, policy_warnings = _policy_evidence(legacy_root, policy_requested)
    legacy_source = _legacy_source_evidence(legacy_root, output_root)
    telemetry, telemetry_warnings = _telemetry_evidence(
        legacy_root,
        included_telemetry,
        output_root,
        scan_lines=args.telemetry_scan_lines,
        max_files=args.max_telemetry_files,
    )
    warnings.extend(config_warnings)
    warnings.extend(policy_warnings)
    warnings.extend(telemetry_warnings)
    if legacy_source.get("truncated") is True:
        warnings.append("legacy source capture reached its bounded size or file limit")
    skipped_sensitive = sum(
        1
        for entry in legacy_source.get("entries", [])
        if isinstance(entry, dict) and "possible credential" in str(entry.get("reason", ""))
    )
    if skipped_sensitive:
        warnings.append(
            f"{skipped_sensitive} possible credential-bearing legacy source file(s) were not copied"
        )

    policy_handoff = _contract_handoff(config, policy)
    policy_handoff_path = output_root / "policy_handoff.json"
    _write_json(policy_handoff_path, policy_handoff)

    gate1: dict[str, object] = {
        "requested": args.include_gate1,
        "status": "NOT_REQUESTED",
        "error": None,
        "summary": None,
    }
    exit_code = 0
    if args.include_gate1:
        try:
            summary = _run_gate1(args, output_root)
            gate1["summary"] = summary
            gate1["status"] = summary.get("run_status", "UNKNOWN")
            if gate1["status"] != "COMPLETE":
                exit_code = 2
        except Exception as exc:
            gate1["status"] = "FAILED"
            gate1["error"] = f"{type(exc).__name__}: {exc}"
            _write_json(output_root / "gate1" / "ERROR.json", gate1)
            exit_code = 2

    metadata: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "collection_id": collection_id,
        "collected_at_utc": collected_at.isoformat(),
        "notes": args.notes,
        "safety": {
            "local_only": True,
            "network_upload_performed": False,
            "policy_inference_performed": False,
            "goal_position_writes_performed": False,
            "torque_enable_performed": False,
            "gate1_requested": args.include_gate1,
            "gate1_torque_off_before_reads": True if args.include_gate1 else None,
        },
        "paths": {
            "legacy_root": str(legacy_root),
            "config_requested": str(config_requested) if config_requested else None,
            "policy_requested": str(policy_requested) if policy_requested else None,
            "serial_device": args.serial_device,
        },
        "collector": _collector_identity(),
        "host": _host_metadata(),
        "clock_and_bus_inventory": clock_and_bus_inventory,
        "python_environment": python_environment,
        "command_results": [asdict(value) for value in command_results],
        "captured_system_files": captured_files,
        "legacy": {
            "config": config,
            "policy": policy,
            "source": legacy_source,
            "telemetry": telemetry,
        },
        "policy_handoff_file": _relative(policy_handoff_path, output_root),
        "gate1": gate1,
        "warnings": warnings,
        "exit_code": exit_code,
    }
    metadata_path = output_root / "metadata.json"
    _write_json(metadata_path, metadata)
    manifest = _manifest(output_root)
    archive, sidecar, digest = _archive(output_root)
    return {
        "exit_code": exit_code,
        "collection_id": collection_id,
        "output_root": str(output_root),
        "metadata": str(metadata_path),
        "manifest": str(manifest),
        "archive": str(archive),
        "archive_sha256": digest,
        "archive_sha256_file": str(sidecar),
        "warnings": warnings,
        "gate1_status": gate1["status"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = collect_evidence(args)
    except (HardwareAuthorizationError, ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
