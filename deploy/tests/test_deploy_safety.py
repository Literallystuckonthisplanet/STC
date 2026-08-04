"""Safety regressions for deploy manifests and orphan pruning."""

import json
import os
import sys
from pathlib import Path


DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
import deploy as D  # noqa: E402


def test_prune_rejects_absolute_and_parent_escape_manifest_entries(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    absolute_victim = outside / "absolute.stc.md"
    parent_victim = outside / "SKILL.md"
    absolute_victim.write_text("keep", encoding="utf-8")
    parent_victim.write_text("keep", encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "codex": {
                    "files": [
                        str(absolute_victim),
                        os.path.join("..", "outside", "SKILL.md"),
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    old_manifest = D.MANIFEST
    D.MANIFEST = str(manifest)
    try:
        pruned = D._prune_orphans("codex", str(native), [])
    finally:
        D.MANIFEST = old_manifest

    assert pruned == []
    assert absolute_victim.read_text(encoding="utf-8") == "keep"
    assert parent_victim.read_text(encoding="utf-8") == "keep"
