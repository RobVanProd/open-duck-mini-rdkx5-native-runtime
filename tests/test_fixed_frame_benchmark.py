from __future__ import annotations

from open_duck_x5.fixed_frame_benchmark import run_benchmark


def test_fixed_frame_benchmark_is_offline_and_equivalent() -> None:
    result = run_benchmark(warmup=2, batches=2, iterations_per_batch=2)
    assert not result["hardware_access"]
    assert result["population"]["response_bytes"] == 140
    assert all(result["equivalence"].values())
    assert result["generic"]["batches"] == 2
    assert result["fixed_frame"]["batches"] == 2
