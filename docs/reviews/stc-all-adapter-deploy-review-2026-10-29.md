# Scoped all-adapter H17 deploy review — 2026-10-29

## Verdict: PASS

Reviewed only `deploy/deploy.py`, `deploy/hook_patch.py`, `deploy/README.md`, and `deploy/tests/test_hook_patch.py` against base `e66a6d7`.

No blocking finding in the requested scope. The v2 install path uses a fixed target map, verifies selected H17 bindings without writing config files, hashes target paths/existence/modes/bytes and binding identity into one aggregate precondition, and writes the shared policy before source and native wrappers. The v2 restore reader maps manifest targets back to fixed paths under the supplied home; manifest paths cannot select arbitrary destinations. Restore preflights all targets before writing, restores native wrappers before removing a newly-created policy, and retains the backup if the final status marker cannot be saved. The v1 reader remains strict to the original Codex paths and format.

The two final-delta concerns are closed. The legacy Codex hash path now requires the installed shared policy to match source bytes and mode before proceeding, and refuses missing or stale policy before writing either wrapper (`deploy/hook_patch.py:320-334`). The Claude binding verifier accepts the exact untagged legacy entry while requiring its canonical path, event, matcher, and full hook entry; present ownership tags must match, duplicate/lookalike entries fail, and the digest covers the actual stored entry (`deploy/hook_patch.py:487-543`). The v1 restore format and paths are unchanged.

The additional implementation is sizable, but the separate v1/v2 readers preserve the old backup format and make the new manifest handling explicit. Size alone is not a correctness blocker here.

## Validation boundary

- Read the changed call paths and restore readers directly; did not inspect the independent helper review or its history.
- Ran the synthetic all-adapter install/rerun/restore/partial-write/conflict scenario, a legacy Codex restore-conflict scenario, and the missing-success-marker restore scenario. All passed in temporary home directories.
- After the final delta, ran the legacy missing/stale-helper refusal, all-adapter lifecycle, exact/untagged/tagged Claude binding and lookalike rejection, and legacy v1 restore scenarios. All passed in temporary home directories.
- No real home directory, installed hooks, real configs, secrets, or deploy were accessed. This does not establish the live installed gate.
- Residual concurrency boundary: `_delete_state` checks then calls `unlink` (`deploy/hook_patch.py:720-725`), so an unrelated process could replace the newly-created policy in that narrow interval and have its file removed. The runbook already requires unrelated writers to stay inactive around these operations (`deploy/README.md:101-107`); the guarantee does not cover concurrent external writers.
