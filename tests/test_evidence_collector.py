from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from open_duck_x5 import evidence_collector
from open_duck_x5.constants import JOINT_NAMES
from open_duck_x5.hardware_guard import HardwareAuthorizationError


class FakeSession:
    def __init__(self, _path: str, *, providers: list[str], input_dimension: int = 101) -> None:
        assert providers == ["CPUExecutionProvider"]
        self.input_dimension = input_dimension

    def get_inputs(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                name="obs",
                shape=[1, self.input_dimension],
                type="tensor(float)",
            )
        ]

    @staticmethod
    def get_outputs() -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                name="continuous_actions",
                shape=[1, 14],
                type="tensor(float)",
            )
        ]


def _install_fake_onnxruntime(
    monkeypatch: pytest.MonkeyPatch, *, input_dimension: int = 101
) -> None:
    def make_session(path: str, *, providers: list[str]) -> FakeSession:
        return FakeSession(path, providers=providers, input_dimension=input_dimension)

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=make_session),
    )


def _write_config(path: Path) -> None:
    payload = {
        "joints_offsets": {name: 0.0 for name in JOINT_NAMES},
        "imu_upside_down": False,
        "start_paused": True,
        "phase_frequency_factor_offset": 0.0,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_json(instance_path: Path, schema_name: str) -> dict[str, object]:
    instance = json.loads(instance_path.read_text(encoding="utf-8"))
    schema_path = Path(__file__).parents[1] / "schemas" / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        instance
    )
    return instance


def _arguments(
    tmp_path: Path,
    legacy_root: Path,
    config: Path,
    policy: Path,
    telemetry: Path,
) -> list[str]:
    return [
        "--output-dir",
        str(tmp_path / "evidence"),
        "--collection-id",
        "offline-test",
        "--legacy-root",
        str(legacy_root),
        "--config",
        str(config),
        "--policy",
        str(policy),
        "--include-telemetry",
        str(telemetry),
    ]


def test_safe_collection_builds_hashed_bundle_without_hardware_or_policy_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    (legacy_root / "runtime.py").write_text("SERIAL = '/dev/ttyACM0'\n", encoding="utf-8")
    (legacy_root / "secret.py").write_text("API_TOKEN = 'do-not-copy'\n", encoding="utf-8")
    config = legacy_root / "duck_config.json"
    _write_config(config)
    policy = legacy_root / "candidate.onnx"
    policy.write_bytes(b"fake policy bytes")
    telemetry = legacy_root / "timing.jsonl"
    telemetry.write_text(
        json.dumps({"schema_version": "test.telemetry.v1", "tick": 7}) + "\n",
        encoding="utf-8",
    )

    _install_fake_onnxruntime(monkeypatch)
    monkeypatch.setattr(evidence_collector, "_command_specs", lambda *_args: [])

    def forbid_gate1(*_args: object) -> dict[str, object]:
        raise AssertionError("safe collection must never enter Gate 1")

    monkeypatch.setattr(evidence_collector, "_run_gate1", forbid_gate1)
    args = evidence_collector.build_parser().parse_args(
        _arguments(tmp_path, legacy_root, config, policy, telemetry)
    )
    result = evidence_collector.collect_evidence(args)

    assert result["exit_code"] == 0
    output_root = Path(str(result["output_root"]))
    metadata = _validate_json(
        output_root / "metadata.json", "duck_evidence_bundle.schema.json"
    )
    handoff = _validate_json(
        output_root / "policy_handoff.json", "policy_handoff.schema.json"
    )
    assert metadata["safety"] == {
        "gate1_requested": False,
        "gate1_torque_off_before_reads": None,
        "goal_position_writes_performed": False,
        "local_only": True,
        "network_upload_performed": False,
        "policy_inference_performed": False,
        "torque_enable_performed": False,
    }
    assert handoff["candidate_policy"]["interface_status"] == "PASS"
    assert handoff["semantic_compatibility"]["status"] == "PENDING_EVIDENCE"
    assert handoff["runtime_contract"]["observation_slot_83_97"]["quantity_class"] == (
        "post-slew commanded target"
    )
    assert (output_root / "legacy" / "source" / "runtime.py").is_file()
    assert not (output_root / "legacy" / "source" / "secret.py").exists()
    assert (output_root / "legacy" / "duck_config.json").is_file()
    assert not list(output_root.rglob("*.onnx"))

    manifest_lines = (output_root / "manifest.sha256").read_text(encoding="utf-8").splitlines()
    assert manifest_lines
    for line in manifest_lines:
        digest, relative = line.split("  ", 1)
        assert _sha256(output_root / relative) == digest

    archive = Path(str(result["archive"]))
    assert _sha256(archive) == result["archive_sha256"]
    sidecar = Path(str(result["archive_sha256_file"]))
    assert sidecar.read_text(encoding="utf-8").startswith(str(result["archive_sha256"]))
    with tarfile.open(archive, "r:gz") as handle:
        members = {member.name for member in handle.getmembers()}
    assert "offline-test/metadata.json" in members
    assert "offline-test/policy_handoff.json" in members


def test_115_input_policy_is_interface_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    config = legacy_root / "duck_config.json"
    _write_config(config)
    policy = legacy_root / "candidate.onnx"
    policy.write_bytes(b"fake 115 input policy")
    telemetry = legacy_root / "timing.jsonl"
    telemetry.write_text("{}\n", encoding="utf-8")
    _install_fake_onnxruntime(monkeypatch, input_dimension=115)
    monkeypatch.setattr(evidence_collector, "_command_specs", lambda *_args: [])

    args = evidence_collector.build_parser().parse_args(
        _arguments(tmp_path, legacy_root, config, policy, telemetry)
    )
    result = evidence_collector.collect_evidence(args)
    handoff = json.loads(
        (Path(str(result["output_root"])) / "policy_handoff.json").read_text(
            encoding="utf-8"
        )
    )

    assert handoff["candidate_policy"]["interface_status"] == "BLOCKED"
    assert "115" in " ".join(handoff["candidate_policy"]["issues"])
    assert any("incompatible" in warning for warning in result["warnings"])


def test_gate1_requires_both_operator_acknowledgements_before_output(tmp_path: Path) -> None:
    args = evidence_collector.build_parser().parse_args(
        [
            "--output-dir",
            str(tmp_path / "evidence"),
            "--collection-id",
            "must-not-exist",
            "--include-gate1",
        ]
    )

    with pytest.raises(HardwareAuthorizationError):
        evidence_collector.collect_evidence(args)
    assert not (tmp_path / "evidence").exists()


def test_inventory_never_runs_active_i2c_scan_or_pip_freeze(tmp_path: Path) -> None:
    specs = evidence_collector._command_specs(tmp_path, "/dev/ttyACM0")
    argument_vectors = [spec.argv for spec in specs]

    assert ("i2cdetect", "-l") in argument_vectors
    assert all("-y" not in argv for argv in argument_vectors)
    assert all("freeze" not in argv for argv in argument_vectors)
    assert any(argv[-2:] == ("list", "--format=json") for argv in argument_vectors)
