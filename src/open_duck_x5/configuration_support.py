from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .constants import CONTROL_FREQUENCY_HZ, JOINT_NAMES, SERVO_IDS

PROFILE_SCHEMA_VERSION = "open_duck_x5.automatic_configuration_profile.v4"
ENVELOPE_SCHEMA_VERSION = "open_duck_x5.supported_configuration_envelope.v1"
RESULT_SCHEMA_VERSION = "open_duck_x5.configuration_support_result.v3"
AUTOMATIC_METHOD = "automatic_supported_excitation"
MINIMUM_TORSO_X_COM_M = (-0.05, 0.05)

JOINT_METRICS = (
    "delay_ticks",
    "gain_ratio",
    "time_constant_s",
    "tracking_p95_rad",
    "current_p95_a",
)
BODY_METRICS = (
    "pitch_rate_p95_rad_s",
    "roll_rate_p95_rad_s",
    "acceleration_norm_p95_m_s2",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ConfigurationSupportError(ValueError):
    """Raised when automatic profile or policy-envelope evidence is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationSupportError(f"could not read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationSupportError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ConfigurationSupportError(f"{label} keys differ: missing={missing}, extra={extra}")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationSupportError(f"{label} must be an object")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationSupportError(f"{label} must be boolean")
    return value


def _finite(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationSupportError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ConfigurationSupportError(f"{label} must be finite")
    if nonnegative and result < 0.0:
        raise ConfigurationSupportError(f"{label} must be nonnegative")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationSupportError(f"{label} must be an integer >= {minimum}")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationSupportError(f"{label} must be a nonempty string")
    return value


def _sha256_string(value: Any, label: str) -> str:
    result = _string(value, label)
    if not _SHA256_RE.fullmatch(result):
        raise ConfigurationSupportError(f"{label} must be a lowercase SHA-256")
    return result


def _commit_string(value: Any, label: str) -> str:
    result = _string(value, label)
    if not _COMMIT_RE.fullmatch(result):
        raise ConfigurationSupportError(f"{label} must be a full Git commit identity")
    return result


def _relative_artifact_path(value: Any, label: str) -> str:
    result = _string(value, label)
    path = Path(result)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigurationSupportError(f"{label} must be a repository-relative path")
    return result


def _range(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigurationSupportError(f"{label} must contain [minimum, maximum]")
    low = _finite(value[0], f"{label}[0]")
    high = _finite(value[1], f"{label}[1]")
    if low > high:
        raise ConfigurationSupportError(f"{label} minimum exceeds maximum")
    return low, high


def _validate_profile(profile: dict[str, Any]) -> tuple[list[str], dict[str, float]]:
    _exact_keys(
        profile,
        {
            "schema_version",
            "source",
            "inventory",
            "sample_contract",
            "joint_response",
            "body_response",
        },
        "profile",
    )
    if profile["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ConfigurationSupportError("profile schema_version is unsupported")

    source = _object(profile["source"], "profile.source")
    _exact_keys(
        source,
        {
            "method",
            "backend",
            "device",
            "informational_only",
            "trace_sha256",
            "metadata_sha256",
            "configuration_sha256",
            "policy_envelope_sha256",
            "manual_measurements_used",
            "hardware_authorized",
            "motion_authorized",
            "configuration_calibration_authorized",
            "suspended_or_benched",
            "torque_off_confirmed",
        },
        "profile.source",
    )
    if source["method"] != AUTOMATIC_METHOD:
        raise ConfigurationSupportError(f"profile.source.method must be {AUTOMATIC_METHOD!r}")
    backend = _string(source["backend"], "profile.source.backend")
    if backend not in {"mock", "serial"}:
        raise ConfigurationSupportError("profile.source.backend must be 'mock' or 'serial'")
    _string(source["device"], "profile.source.device")
    informational_only = _boolean(source["informational_only"], "profile.source.informational_only")
    _sha256_string(source["trace_sha256"], "profile.source.trace_sha256")
    _sha256_string(source["metadata_sha256"], "profile.source.metadata_sha256")
    _sha256_string(source["configuration_sha256"], "profile.source.configuration_sha256")
    policy_envelope_sha256 = source["policy_envelope_sha256"]
    if _boolean(
        source["manual_measurements_used"],
        "profile.source.manual_measurements_used",
    ):
        raise ConfigurationSupportError("manual physical measurements are not accepted")
    hardware_authorized = _boolean(
        source["hardware_authorized"], "profile.source.hardware_authorized"
    )
    motion_authorized = _boolean(source["motion_authorized"], "profile.source.motion_authorized")
    calibration_authorized = _boolean(
        source["configuration_calibration_authorized"],
        "profile.source.configuration_calibration_authorized",
    )
    supported = _boolean(source["suspended_or_benched"], "profile.source.suspended_or_benched")
    if not _boolean(source["torque_off_confirmed"], "profile.source.torque_off_confirmed"):
        raise ConfigurationSupportError("profile lacks final torque-off confirmation")

    issues: list[str] = []
    if backend == "mock":
        if policy_envelope_sha256 is not None:
            raise ConfigurationSupportError(
                "mock profile cannot claim a preregistered policy envelope"
            )
        if (
            not informational_only
            or hardware_authorized
            or motion_authorized
            or calibration_authorized
            or supported
        ):
            raise ConfigurationSupportError(
                "mock profile must be informational_only without physical authority"
            )
        issues.append("source.informational_only_mock")
    else:
        _sha256_string(
            policy_envelope_sha256,
            "profile.source.policy_envelope_sha256",
        )
        if informational_only:
            raise ConfigurationSupportError("serial profile cannot be informational_only")
        if not hardware_authorized:
            raise ConfigurationSupportError("profile lacks explicit hardware authority")
        if not motion_authorized or not calibration_authorized:
            raise ConfigurationSupportError("profile lacks exact calibration-motion authority")
        if not supported:
            raise ConfigurationSupportError("profile was not collected with the robot supported")
    inventory = _object(profile["inventory"], "profile.inventory")
    _exact_keys(
        inventory,
        {
            "required_servo_ids",
            "responding_servo_ids",
            "imu_present",
            "contacts_present",
        },
        "profile.inventory",
    )
    required_ids = inventory["required_servo_ids"]
    responding_ids = inventory["responding_servo_ids"]
    if required_ids != list(SERVO_IDS):
        raise ConfigurationSupportError("profile required_servo_ids changes the frozen contract")
    if not isinstance(responding_ids, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in responding_ids
    ):
        raise ConfigurationSupportError("profile responding_servo_ids must be integer IDs")
    if len(set(responding_ids)) != len(responding_ids):
        raise ConfigurationSupportError("profile responding_servo_ids contains duplicates")
    unexpected_ids = sorted(set(responding_ids) - set(SERVO_IDS))
    missing_ids = [servo_id for servo_id in SERVO_IDS if servo_id not in responding_ids]
    if unexpected_ids:
        issues.append("inventory.unexpected_servo_ids=" + ",".join(map(str, unexpected_ids)))
    if missing_ids:
        issues.append("inventory.missing_servo_ids=" + ",".join(map(str, missing_ids)))
    if not _boolean(inventory["imu_present"], "profile.inventory.imu_present"):
        issues.append("inventory.imu_missing")
    if not _boolean(inventory["contacts_present"], "profile.inventory.contacts_present"):
        issues.append("inventory.contacts_missing")

    samples = _object(profile["sample_contract"], "profile.sample_contract")
    _exact_keys(
        samples,
        {
            "frequency_hz",
            "tick_count",
            "complete",
            "stale_sample_count",
            "transaction_failure_count",
            "telemetry_drop_count",
            "tick_period_p99_ms",
            "tick_period_p99_9_ms",
            "bus_total_max_ms",
        },
        "profile.sample_contract",
    )
    frequency_hz = _finite(samples["frequency_hz"], "profile.sample_contract.frequency_hz")
    if frequency_hz != CONTROL_FREQUENCY_HZ:
        issues.append(f"sample_contract.frequency_hz={frequency_hz}")
    if _integer(samples["tick_count"], "profile.sample_contract.tick_count", minimum=1) < 1:
        raise AssertionError("unreachable")
    if not _boolean(samples["complete"], "profile.sample_contract.complete"):
        issues.append("sample_contract.incomplete")
    for key in (
        "stale_sample_count",
        "transaction_failure_count",
        "telemetry_drop_count",
    ):
        value = _integer(samples[key], f"profile.sample_contract.{key}")
        if value:
            issues.append(f"sample_contract.{key}={value}")
    tick_p99 = _finite(
        samples["tick_period_p99_ms"],
        "profile.sample_contract.tick_period_p99_ms",
        nonnegative=True,
    )
    tick_p99_9 = _finite(
        samples["tick_period_p99_9_ms"],
        "profile.sample_contract.tick_period_p99_9_ms",
        nonnegative=True,
    )
    bus_max = _finite(
        samples["bus_total_max_ms"],
        "profile.sample_contract.bus_total_max_ms",
        nonnegative=True,
    )
    if tick_p99 > 21.0:
        issues.append(f"sample_contract.tick_period_p99_ms={tick_p99}")
    if tick_p99_9 > 22.0:
        issues.append(f"sample_contract.tick_period_p99_9_ms={tick_p99_9}")
    if bus_max >= 5.0:
        issues.append(f"sample_contract.bus_total_max_ms={bus_max}")

    flattened: dict[str, float] = {}
    joint_response = _object(profile["joint_response"], "profile.joint_response")
    extra_joints = sorted(set(joint_response) - set(JOINT_NAMES))
    if extra_joints:
        raise ConfigurationSupportError(f"profile has unknown joints: {extra_joints}")
    for joint_name in JOINT_NAMES:
        if joint_name not in joint_response:
            issues.append(f"joint_response.{joint_name}.missing")
            continue
        metrics = _object(joint_response[joint_name], f"joint_response.{joint_name}")
        _exact_keys(metrics, set(JOINT_METRICS), f"joint_response.{joint_name}")
        for metric in JOINT_METRICS:
            flattened[f"joint_response.{joint_name}.{metric}"] = _finite(
                metrics[metric],
                f"joint_response.{joint_name}.{metric}",
                nonnegative=True,
            )

    body_response = _object(profile["body_response"], "profile.body_response")
    _exact_keys(body_response, set(BODY_METRICS), "profile.body_response")
    for metric in BODY_METRICS:
        flattened[f"body_response.{metric}"] = _finite(
            body_response[metric], f"body_response.{metric}", nonnegative=True
        )
    return issues, flattened


def validate_automatic_profile_data(profile: dict[str, Any]) -> list[str]:
    """Validate an automatic profile and return its fail-closed hold issues."""
    issues, _metrics = _validate_profile(profile)
    return issues


def _validate_bounds(
    raw: dict[str, Any], metrics: tuple[str, ...], label: str
) -> dict[str, tuple[float, float]]:
    _exact_keys(raw, set(metrics), label)
    result = {metric: _range(raw[metric], f"{label}.{metric}") for metric in metrics}
    for metric, (low, _high) in result.items():
        if low < 0.0:
            raise ConfigurationSupportError(f"{label}.{metric} minimum must be nonnegative")
    return result


def _validate_envelope(envelope: dict[str, Any]) -> dict[str, tuple[float, float]]:
    _exact_keys(
        envelope,
        {
            "schema_version",
            "policy",
            "preregistration",
            "per_unit_physical_measurement_required",
            "policy_robustness_gate_passed",
            "configuration_domain",
            "profile_metric_bounds",
        },
        "envelope",
    )
    if envelope["schema_version"] != ENVELOPE_SCHEMA_VERSION:
        raise ConfigurationSupportError("envelope schema_version is unsupported")
    if _boolean(
        envelope["per_unit_physical_measurement_required"],
        "envelope.per_unit_physical_measurement_required",
    ):
        raise ConfigurationSupportError("policy envelope requires a per-unit measurement")
    if not _boolean(
        envelope["policy_robustness_gate_passed"],
        "envelope.policy_robustness_gate_passed",
    ):
        raise ConfigurationSupportError("policy robustness gate is not passed")

    policy = _object(envelope["policy"], "envelope.policy")
    _exact_keys(policy, {"repository", "commit", "onnx_sha256", "contract_id"}, "policy")
    _string(policy["repository"], "policy.repository")
    _commit_string(policy["commit"], "policy.commit")
    _sha256_string(policy["onnx_sha256"], "policy.onnx_sha256")
    _string(policy["contract_id"], "policy.contract_id")

    prereg = _object(envelope["preregistration"], "envelope.preregistration")
    _exact_keys(prereg, {"commit", "artifact_path", "artifact_sha256"}, "preregistration")
    _commit_string(prereg["commit"], "preregistration.commit")
    _relative_artifact_path(prereg["artifact_path"], "preregistration.artifact_path")
    _sha256_string(prereg["artifact_sha256"], "preregistration.artifact_sha256")

    domain = _object(envelope["configuration_domain"], "configuration_domain")
    _exact_keys(
        domain,
        {
            "torso_mass_scale",
            "torso_com_x_m",
            "torso_com_y_m",
            "torso_com_z_m",
            "torso_inertia_scale",
            "coupled_sample_count",
            "held_out_sample_count",
            "supported_optional_component_configurations",
        },
        "configuration_domain",
    )
    mass_low, mass_high = _range(domain["torso_mass_scale"], "torso_mass_scale")
    if not mass_low < 1.0 < mass_high:
        raise ConfigurationSupportError("torso_mass_scale must span nominal 1.0")
    x_low, x_high = _range(domain["torso_com_x_m"], "torso_com_x_m")
    if x_low > MINIMUM_TORSO_X_COM_M[0] or x_high < MINIMUM_TORSO_X_COM_M[1]:
        raise ConfigurationSupportError("torso_com_x_m does not cover [-0.05, 0.05]")
    for axis in ("y", "z"):
        low, high = _range(domain[f"torso_com_{axis}_m"], f"torso_com_{axis}_m")
        if not low < 0.0 < high:
            raise ConfigurationSupportError(f"torso_com_{axis}_m must span zero")
    inertia = _object(domain["torso_inertia_scale"], "torso_inertia_scale")
    _exact_keys(inertia, {"xx", "yy", "zz"}, "torso_inertia_scale")
    for axis in ("xx", "yy", "zz"):
        low, high = _range(inertia[axis], f"torso_inertia_scale.{axis}")
        if not low < 1.0 < high:
            raise ConfigurationSupportError(f"torso_inertia_scale.{axis} must span nominal 1.0")
    _integer(domain["coupled_sample_count"], "coupled_sample_count", minimum=1)
    _integer(domain["held_out_sample_count"], "held_out_sample_count", minimum=1)
    configurations = domain["supported_optional_component_configurations"]
    if not isinstance(configurations, list) or len(configurations) < 2:
        raise ConfigurationSupportError(
            "supported_optional_component_configurations needs at least two configurations"
        )
    names = [_string(item, "optional component configuration") for item in configurations]
    if len(set(names)) != len(names):
        raise ConfigurationSupportError("optional component configurations contain duplicates")

    metric_bounds = _object(envelope["profile_metric_bounds"], "profile_metric_bounds")
    _exact_keys(metric_bounds, {"joints", "body"}, "profile_metric_bounds")
    joints = _object(metric_bounds["joints"], "profile_metric_bounds.joints")
    _exact_keys(joints, set(JOINT_NAMES), "profile_metric_bounds.joints")
    flattened: dict[str, tuple[float, float]] = {}
    for joint_name in JOINT_NAMES:
        raw_bounds = _object(joints[joint_name], f"profile_metric_bounds.joints.{joint_name}")
        parsed = _validate_bounds(
            raw_bounds, JOINT_METRICS, f"profile_metric_bounds.joints.{joint_name}"
        )
        for metric, bounds in parsed.items():
            flattened[f"joint_response.{joint_name}.{metric}"] = bounds
    body = _object(metric_bounds["body"], "profile_metric_bounds.body")
    parsed_body = _validate_bounds(body, BODY_METRICS, "profile_metric_bounds.body")
    for metric, bounds in parsed_body.items():
        flattened[f"body_response.{metric}"] = bounds
    return flattened


def validate_supported_configuration_envelope_data(
    envelope: dict[str, Any],
) -> dict[str, tuple[float, float]]:
    """Validate a policy envelope before any physical response is observed."""
    return _validate_envelope(envelope)


def _evaluate_profile_against_envelope(
    profile: dict[str, Any],
    envelope: dict[str, Any],
    *,
    pass_status: str,
    hold_status: str,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    issues, profile_metrics = _validate_profile(profile)
    bounds = _validate_envelope(envelope)

    checks: list[dict[str, Any]] = []
    for name in sorted(bounds):
        if name not in profile_metrics:
            continue
        value = profile_metrics[name]
        low, high = bounds[name]
        passed = low <= value <= high
        checks.append(
            {
                "metric": name,
                "value": value,
                "minimum": low,
                "maximum": high,
                "pass": passed,
            }
        )
        if not passed:
            issues.append(f"{name}.outside_supported_envelope")

    passed = not issues and len(checks) == len(bounds)
    if len(checks) != len(bounds):
        issues.append(f"metric_population={len(checks)}/{len(bounds)}")
        passed = False
    status = pass_status if passed else hold_status
    return status, checks, list(dict.fromkeys(issues))


def evaluate_configuration_support_data(
    *, profile: dict[str, Any], envelope: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate already-loaded values without claiming raw-evidence verification.

    This is useful for unit tests and envelope diagnostics.  Only
    :func:`validate_configuration_support`, which reproduces the profile from the
    immutable inputs, may emit the full automatic-configuration PASS status.
    """
    status, checks, issues = _evaluate_profile_against_envelope(
        profile,
        envelope,
        pass_status="PASS_PROFILE_VALUES_INSIDE_POLICY_ENVELOPE",
        hold_status="HOLD_PROFILE_VALUES_OUTSIDE_POLICY_ENVELOPE",
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "decision": status,
        "profile": {
            "method": AUTOMATIC_METHOD,
            "manual_measurements_used": False,
            "raw_evidence_verified": False,
        },
        "envelope": {
            "policy": envelope["policy"],
            "preregistration": envelope["preregistration"],
        },
        "metric_checks": checks,
        "issues": issues,
        "authority": {
            "robot_clearance": False,
            "gate5": False,
            "runtime_deployment": False,
            "motion": False,
        },
    }


def _profile_reproduction_max_abs_error(
    supplied: Any,
    reproduced: Any,
    *,
    label: str = "profile",
) -> float:
    if isinstance(supplied, bool) or isinstance(reproduced, bool):
        if supplied is not reproduced:
            raise ConfigurationSupportError(f"{label} differs from reproduced profile")
        return 0.0
    if isinstance(supplied, (int, float)) and isinstance(reproduced, (int, float)):
        supplied_number = float(supplied)
        reproduced_number = float(reproduced)
        if not math.isfinite(supplied_number) or not math.isfinite(reproduced_number):
            raise ConfigurationSupportError(f"{label} contains a nonfinite value")
        error = abs(supplied_number - reproduced_number)
        if error > 1e-9:
            raise ConfigurationSupportError(
                f"{label} differs from reproduced profile: absolute_error={error}"
            )
        return error
    if isinstance(supplied, dict) and isinstance(reproduced, dict):
        if set(supplied) != set(reproduced):
            raise ConfigurationSupportError(f"{label} keys differ from reproduced profile")
        maximum = 0.0
        for key in sorted(supplied):
            maximum = max(
                maximum,
                _profile_reproduction_max_abs_error(
                    supplied[key], reproduced[key], label=f"{label}.{key}"
                ),
            )
        return maximum
    if isinstance(supplied, list) and isinstance(reproduced, list):
        if len(supplied) != len(reproduced):
            raise ConfigurationSupportError(f"{label} length differs from reproduced profile")
        maximum = 0.0
        for index, (supplied_item, reproduced_item) in enumerate(
            zip(supplied, reproduced, strict=True)
        ):
            maximum = max(
                maximum,
                _profile_reproduction_max_abs_error(
                    supplied_item, reproduced_item, label=f"{label}[{index}]"
                ),
            )
        return maximum
    if type(supplied) is not type(reproduced) or supplied != reproduced:
        raise ConfigurationSupportError(f"{label} differs from reproduced profile")
    return 0.0


def validate_configuration_support(
    *,
    profile_path: Path,
    envelope_path: Path,
    trace_path: Path,
    metadata_path: Path,
    configuration_path: Path,
) -> dict[str, Any]:
    profile_path = profile_path.expanduser().resolve()
    envelope_path = envelope_path.expanduser().resolve()
    trace_path = trace_path.expanduser().resolve()
    metadata_path = metadata_path.expanduser().resolve()
    configuration_path = configuration_path.expanduser().resolve()
    profile = _load_object(profile_path, "automatic configuration profile")
    envelope = _load_object(envelope_path, "supported configuration envelope")
    _validate_profile(profile)
    envelope_sha256 = _sha256(envelope_path)
    if profile["source"]["policy_envelope_sha256"] != envelope_sha256:
        raise ConfigurationSupportError(
            "profile was not collected against this preregistered policy envelope"
        )

    # Local import avoids a module cycle: the profile builder uses the strict
    # profile schema validator above before returning a generated artifact.
    from .configuration_profile import (  # noqa: PLC0415
        ConfigurationProfileError,
        build_automatic_configuration_profile,
    )

    try:
        reproduced = build_automatic_configuration_profile(
            trace_path=trace_path,
            metadata_path=metadata_path,
            configuration_path=configuration_path,
        )
    except ConfigurationProfileError as exc:
        raise ConfigurationSupportError(
            f"could not reproduce profile from raw evidence: {exc}"
        ) from exc
    reproduction_error = _profile_reproduction_max_abs_error(profile, reproduced)
    status, checks, issues = _evaluate_profile_against_envelope(
        profile,
        envelope,
        pass_status="PASS_AUTOMATIC_CONFIGURATION_INSIDE_POLICY_ENVELOPE",
        hold_status="HOLD_AUTOMATIC_CONFIGURATION_OUTSIDE_POLICY_ENVELOPE",
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": status,
        "decision": status,
        "profile": {
            "path": str(profile_path),
            "sha256": _sha256(profile_path),
            "method": AUTOMATIC_METHOD,
            "manual_measurements_used": False,
            "raw_evidence_verified": True,
            "reproduction_max_abs_error": reproduction_error,
        },
        "raw_evidence": {
            "trace": {"path": str(trace_path), "sha256": _sha256(trace_path)},
            "metadata": {
                "path": str(metadata_path),
                "sha256": _sha256(metadata_path),
            },
            "configuration": {
                "path": str(configuration_path),
                "sha256": _sha256(configuration_path),
            },
        },
        "envelope": {
            "path": str(envelope_path),
            "sha256": envelope_sha256,
            "precommitted_before_collection": True,
            "policy": envelope["policy"],
            "preregistration": envelope["preregistration"],
        },
        "metric_checks": checks,
        "issues": issues,
        "authority": {
            "robot_clearance": False,
            "gate5": False,
            "runtime_deployment": False,
            "motion": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an automatic robot profile against a policy support envelope"
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.expanduser().resolve()
    protected = {
        args.profile.expanduser().resolve(),
        args.envelope.expanduser().resolve(),
        args.trace.expanduser().resolve(),
        args.metadata.expanduser().resolve(),
        args.configuration.expanduser().resolve(),
    }
    if output in protected:
        print("result=FAIL reason=--output must not overwrite an input")
        return 2
    try:
        output.unlink(missing_ok=True)
    except OSError as exc:
        print(f"result=FAIL reason=could not clear prior output: {exc}")
        return 2
    try:
        result = validate_configuration_support(
            profile_path=args.profile,
            envelope_path=args.envelope,
            trace_path=args.trace,
            metadata_path=args.metadata,
            configuration_path=args.configuration,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except ConfigurationSupportError as exc:
        print(f"result=FAIL reason={exc}")
        return 2
    print(f"result={result['status']} checks={len(result['metric_checks'])}")
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
