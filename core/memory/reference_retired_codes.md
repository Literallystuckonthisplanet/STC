# Registry of retired code-labels

A reference catalog. Not loaded into always-context; read when a label
disappears from always or during an infra audit.

When a rule migrates from always-text to a HOOK (ADR-001) and its code no
longer has a definition anywhere — it is **retired** here, not orphaned.
The doc-backend generator reads this registry so a retired code:

- (a) is **not** flagged as an orphan (the orphan-scan skips it, even though
  hook headers/text still mention it);
- (b) does **not** create a numbering gap (the gap-scan subtracts retired
  numbers).

## When NOT to register here

If the rule was merely **slimmed to a pointer** (the `<!-- Ixx -->` label
stays as a pointer line "→ enforced by Hxx") — it is still defined, it will
not orphan. The registry is only for a **complete removal** of the label.

## Format

One line per retired code, parsed by the regex `- Ixx → Hyy`:

```
- Ixx → Hyy (YYYY-MM-DD): what migrated
```

## Retired

<!--
Seed this with your own retirements as rules migrate to hooks.
Example shape (replace with real entries):
- I04 → H09 (YYYY-MM-DD): the memory-edit style/protocol (dedup → place →
  format) migrated to the JIT-inject of memory-guard.
-->

- S05 → I26 (2026-07-10): the `/handoff` command removed — cross-session
  continuity now comes from Memory rotation (`behavior.md` § I26): STATE of
  `project_<name>.md` is always the latest session, no handoff doc needed.
- S09 → I26 (2026-07-10): the `/save-and-compact` command removed — session
  memory is saved live per I26 (facts as they arise, rotation at session
  end); the compact itself is the harness-native `${COMPACT_CMD}`, prompted
  by hook H03.
