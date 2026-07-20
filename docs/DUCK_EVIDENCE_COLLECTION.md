# Duck Evidence Collection

`tools/collect_duck_evidence.py` creates a bounded, hashed evidence bundle from the
RDK-X5 and the preserved runtime. Its default mode is read-only: it does not infer a
policy, enable torque, write a goal position, move the robot, or upload anything.

## Run the safe default at home

Clone or update this repository on the X5, then run from its root without `sudo`:

```bash
python3 tools/collect_duck_evidence.py \
  --legacy-root /home/sunrise/project \
  --notes "pre-gate board inventory"
```

The collector searches the legacy root for configs, ONNX candidates, and JSONL
telemetry, and also checks `~/duck_config.json`. Models and logs stored elsewhere in
the home directory are not recursively scanned because that would traverse virtual
environments, caches, and potentially unrelated large files. Select those with exact
paths:

```bash
python3 tools/collect_duck_evidence.py \
  --legacy-root /home/sunrise/project \
  --config /home/sunrise/project/duck_config.json \
  --policy /path/to/candidate.onnx \
  --include-telemetry /path/to/legacy-telemetry.jsonl
```

The Python script adds this repository's `src` directory to its import path, so an
editable install is not required. It does require the normal runtime Python packages,
including NumPy. ONNX Runtime is optional; without it, the model is still hashed but
its tensor interface is reported as `UNVERIFIED`.

## What the bundle contains

- board, OS, kernel, CPU, clock-governor, scheduler, affinity, and RT-isolation state;
- USB, serial, serial-driver/latency, I2C-adapter, and GPIO inventory without an active
  I2C address scan;
- installed Python package versions and module locations for the servo/sensor stack;
- legacy Git revision/status/diff summary and a bounded copy of reviewable source;
- exact `duck_config.json` copy and frozen-semantics validation;
- ONNX hashes and input/output metadata, but never the policy binary or an inference;
- JSONL schema/tick summaries and, when available, an extracted and verified adjacent
  legacy 101/14 contract snapshot;
- `policy_handoff.json`, which records all 101 observation labels, action/servo order,
  home values, deterministic ONNX session settings, the three distinct target
  quantities, and unresolved semantic gates;
- a SHA-256 manifest, compressed archive, and archive hash sidecar.

Likely credential assignments cause a source file to be hashed but not copied. Virtual
environments, models, raw log directories, build output, and Git internals are skipped.
The archive remains local until the operator deliberately copies it.

## Output and verification

The default output directory is `~/duck-evidence/`. The command prints the exact paths
to the bundle directory, `.tar.gz` archive, and `.sha256` sidecar. On the X5, verify the
archive before copying it:

```bash
cd ~/duck-evidence
sha256sum --check duck-evidence-*.tar.gz.sha256
```

Read `metadata.json` warnings before relying on the bundle. Missing optional commands
or unreadable sysfs files are recorded as evidence instead of aborting the collection.

## Optional Gate 1 read probe

The default command never opens the servo bus. The only hardware mode is the existing
single-servo, torque-off Gate 1 probe. It remains prohibited until Rob authorizes that
exact gate and the robot is physically suspended or benched. When that authorization
exists, both acknowledgements are still mandatory:

```bash
python3 tools/collect_duck_evidence.py \
  --legacy-root /home/sunrise/project \
  --include-gate1 \
  --servo-id 20 \
  --hardware-authorized \
  --suspended-or-benched
```

This mode torque-disables the selected frozen-map servo before ping/read timing and
does not write a goal position. The flags are an operator assertion for that run only;
they do not authorize later gates, torque-on motion, or grounded testing.

## Policy handoff blockers

An ONNX shape match proves only `[1,101] -> [1,14]` interface compatibility. It cannot
prove that training and runtime assign the same meaning to each element. Before a
policy hardware gate, resolve these from training source plus the board golden vector:

1. whether training `obs[83:97]` is the post-slew commanded target or a
   bridge-realized/measured state;
2. whether phase is sampled before or after the 27-tick clock advance;
3. whether training used the frozen 5.24 rad/s slew semantics.

`policy_handoff.json` keeps these at `PENDING_EVIDENCE`; collecting a bundle does not
grant policy clearance.
