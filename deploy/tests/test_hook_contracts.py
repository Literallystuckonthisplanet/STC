"""Runtime contract smoke tests for every source hook.

These are deliberately small: renderer tests prove wiring, while this matrix
proves that each shell entrypoint accepts a harness-shaped JSON envelope and
does not die on a missing optional field. Critical block/allow behavior remains
covered by focused tests next to the adapter and deploy code.
"""

import json
import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HOOKS = sorted(
    path for path in (REPO / "core" / "hooks").glob("*.sh")
    if not path.name.startswith("_")
)


def _env(tmp_path):
    env = os.environ.copy()
    env.update({
        "STC_CORE": str(REPO / "core"),
        "HARNESS_DIR": str(tmp_path / "harness"),
        "MEMORY_DIR": str(tmp_path / "memory"),
        "PROJECTS_ROOT": str(tmp_path / "projects"),
        "RELEASE_ACK_FILE": str(tmp_path / "release-ack"),
        "USER_LANG": "en",
    })
    return env


def test_every_source_hook_is_shell_valid_and_accepts_empty_envelope(tmp_path):
    payload = json.dumps({"source": "startup", "session_id": "contract-test"})
    failures = []
    for hook in HOOKS:
        result = subprocess.run(
            ["bash", str(hook)],
            input=payload,
            text=True,
            capture_output=True,
            env=_env(tmp_path),
            check=False,
        )
        if result.returncode not in (0, 2):
            failures.append(
                f"{hook.name}: rc={result.returncode}; stderr={result.stderr[-300:]}"
            )

    assert not failures, "\n".join(failures)


def test_every_source_hook_passes_bash_syntax_check():
    failures = []
    for hook in HOOKS:
        result = subprocess.run(
            ["bash", "-n", str(hook)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append(f"{hook.name}: {result.stderr.strip()}")

    assert not failures, "\n".join(failures)
