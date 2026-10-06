"""Focused acceptance tests for Codex rules-only deployment."""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
import deploy as D  # noqa: E402


@pytest.fixture
def rules_only_env(tmp_path, monkeypatch):
    native = tmp_path / "codex"
    rules = tmp_path / "stc" / "core" / "rules"
    native.mkdir(parents=True)
    rules.mkdir(parents=True)
    (native / "AGENTS.md").write_text(
        "USER BEFORE\n" + D.B.STC_BEGIN + "\nold managed\n" +
        D.B.STC_END + "\nUSER AFTER\n", encoding="utf-8")
    (native / "AGENTS.stc.md").write_text("old bundle\n", encoding="utf-8")
    unrelated = {
        "hooks.json": b'{"foreign":true}\n',
        "config.toml": b'model = "foreign"\n',
        "agents/foreign.toml": b"foreign agent\n",
        "roundtable/tables.yaml": b"foreign roundtable\n",
    }
    for rel, body in unrelated.items():
        p = native / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
    for source in (Path(D.CORE) / "rules").glob("*.md"):
        shutil.copy2(source, rules / source.name)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "codex": {
            "native_dir": str(native),
            "files": ["AGENTS.stc.md"],
            "always_context": "AGENTS.md",
        }
    }), encoding="utf-8")
    monkeypatch.setattr(D, "STC_HOME", str(tmp_path / "stc"))
    monkeypatch.setattr(D, "BACKUPS", str(tmp_path / "backups"))
    monkeypatch.setattr(D, "MANIFEST", str(manifest))
    stc, registry, adapters, _ = D._gather()
    adapter = copy.deepcopy(adapters["codex"])
    adapter["native_dir"] = str(native)
    return tmp_path, native, rules, manifest, stc, registry, adapter, unrelated


def test_rules_only_updates_only_rules_and_restores_both_roots(rules_only_env):
    tmp, native, rules, manifest, stc, registry, adapter, unrelated = rules_only_env
    before_user = (native / "AGENTS.md").read_text()
    before_unrelated = {rel: (native / rel).read_bytes() for rel in unrelated}
    before_rules = {p.name: p.read_bytes() for p in rules.glob("*.md")}

    assert D._apply_codex_rules_only(stc, registry, adapter) == 0
    updated_bundle = (native / "AGENTS.stc.md").read_bytes()
    assert updated_bundle != b"old bundle\n"
    after_user = (native / "AGENTS.md").read_text()
    assert after_user.startswith("USER BEFORE\n") and after_user.endswith("USER AFTER\n")
    assert before_unrelated == {rel: (native / rel).read_bytes() for rel in unrelated}

    assert D._apply_codex_rules_only(stc, registry, adapter) == 0
    assert updated_bundle == (native / "AGENTS.stc.md").read_bytes()
    assert before_unrelated == {rel: (native / rel).read_bytes() for rel in unrelated}
    assert json.loads(manifest.read_text())["codex"]["files"] == ["AGENTS.stc.md"]

    ledger = json.loads((tmp / "backups" / "_ledger.json").read_text())
    assert len(ledger) == 4
    for backup_id in list(ledger)[:2]:
        assert D.cmd_restore(type("Args", (), {"backup_id": backup_id})()) == 0
    assert before_rules == {p.name: p.read_bytes() for p in rules.glob("*.md")}
    assert (native / "AGENTS.stc.md").read_bytes() == b"old bundle\n"
    assert (native / "AGENTS.md").read_text() == before_user


@pytest.mark.parametrize("case", ["missing_manifest", "missing_rule", "new_rule", "symlink_root", "symlink_file", "non_codex"])
def test_rules_only_rejects_before_backup_or_writes(rules_only_env, case):
    tmp, native, rules, manifest, stc, registry, adapter, _ = rules_only_env
    before_native = {p.relative_to(native): p.read_bytes() for p in native.rglob("*") if p.is_file()}
    if case == "missing_manifest":
        manifest.unlink()
    elif case == "missing_rule":
        (rules / "pev.md").unlink()
    elif case == "new_rule":
        (rules / "new.md").write_text("new\n")
    elif case == "symlink_root":
        shutil.rmtree(rules)
        rules.symlink_to(tmp / "elsewhere")
    elif case == "symlink_file":
        target = tmp / "target.md"
        target.write_text("target\n")
        (rules / "pev.md").unlink()
        (rules / "pev.md").symlink_to(target)
    elif case == "non_codex":
        adapter["harness"] = "claude"

    result = D._apply_codex_rules_only(stc, registry, adapter)
    assert result == 1
    assert not (tmp / "backups").exists()
    assert before_native == {p.relative_to(native): p.read_bytes() for p in native.rglob("*") if p.is_file()}
