# Winner-v2 offline asset lock hold

Status: `SUPERSEDED_STALE_OFFLINE_ASSET_LOCK`

The lock at `winner_v2_offline_asset_lock_20260719.json` with SHA-256
`4da893b39c98d155fb0a0154a47dc46453a72b92d9d9855b5563746fa34de940`
is preserved as an audit artifact but is not the current deployable identity
set.

Policy commit `bc4132b8a7a9db28e32bb873747c164b3a3abb4d` found that the reduced
recursive-closure report named the teacher-forced observation gate as
`<=1e-6`, while the frozen rule requires exact zero. Every recorded value was
already exactly `0.0`, so the accepted decision and full formal artifact are
unchanged.

The runtime corrected only the reduced reporting gate and regenerated the
reduced artifact from unchanged full-result SHA-256
`e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14`.
The corrected reduced SHA-256 is
`1292772e54f3734f2e48b5b0d75fb0c931949d3b7820598c4a9040a8b765dc5e`.

Policy commit `4c99b5e3be203af419536382f11f3cce98283ba2` subsequently
independently validated the corrected reduced artifact and committed final
acceptance-result SHA-256
`5380897c21d3e438dbc4216ba049bc14fb6beb227a13407943d4d092519b7ddc`.
The active lock was therefore regenerated from new identities. This historical
SHA remains revoked and must never be rehabilitated or promoted.

`tools/verify_winner_v2_asset_lock.py` also rejects this exact stale SHA-256
before evaluating any lock contents. A later independently revalidated lock
must have a different byte identity to pass.
