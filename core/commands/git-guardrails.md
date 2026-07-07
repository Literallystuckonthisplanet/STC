---
description: "Set up the git guard hook (H01, block-dangerous-git.sh): blocks dangerous git (reset --hard, clean, branch -D, checkout .), blocks push-to-main as a release gate (I08), and JIT-injects the commit verify-checklist + invariants (I17/I09, FR-5) before every git commit. Use when the user wants git safety guardrails."
---

# Set up git guardrails
<!-- S03 -->

Sets up the PreToolUse Bash hook **H01** (`block-dangerous-git.sh`). One
script, three responsibilities:

1. **🔒 Dangerous patterns** — `reset --hard`, `clean -f`, `clean -fd`,
   `branch -D`, `checkout .`, `restore .` → hard block (exit 2).
2. **🔒 Push to main/master = release (I08)** — blocked without a one-shot ack
   marker. The user says "releasing" → the agent runs security-deps, sets the
   marker (`touch ${RELEASE_ACK_FILE}`), then the push passes once.
3. **💉 Commit verify-checklist + invariants (I17/I09, FR-5)** — before every
   `git commit`, a JIT-inject via `additionalContext`: static/eyes/dynamic
   verify + one-task-one-commit + don't-commit-unfinished. `--no-verify` gets
   an extra reminder (pre-commit bypassed → run lint/tsc manually).

## Steps

### 1. Ask the scope

Ask the user: install for **this project only** (`settings.json` in the
project) or **all projects** (global `settings.json`)?

### 2. Copy the hook script

The bundled script is `core/hooks/block-dangerous-git.sh`. Copy it to the
target location based on scope and the harness's hook directory (see the
adapter for the exact path):

- **Project:** `<project>/${HOOKS_DIR}/block-dangerous-git.sh`
- **Global:** `${HOME}/${HARNESS_SUBDIR}/${HOOKS_DIR}/block-dangerous-git.sh`

Make it executable with `chmod +x`.

### 3. Add the hook to settings

Add to the appropriate settings file (merge into the existing `hooks.PreToolUse`
array — don't overwrite other settings):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "<absolute-path-to-script>" }
        ]
      }
    ]
  }
}
```

### 4. Verify (functional, not just structural)

Run the script under realistic inputs and confirm the exit code + output shape:

```bash
# dangerous → BLOCKED (exit 2)
echo '{"tool_input":{"command":"git reset --hard HEAD~1"}}' | <path-to-script>
echo "exit=$? (expect 2)"

# push to main → BLOCKED (exit 2)
echo '{"tool_input":{"command":"git push origin main"}}' | RELEASE_ACK_FILE=/tmp/x <path-to-script>
echo "exit=$? (expect 2)"

# commit → JIT-inject (exit 0, jq JSON on stdout)
echo '{"tool_input":{"command":"git commit -m test"}}' | RELEASE_ACK_FILE=/tmp/x <path-to-script> | jq -r '.hookSpecificOutput.hookEventName'
# expect: PreToolUse

# safe (push to feature) → PASS (exit 0)
echo '{"tool_input":{"command":"git push origin feature-x"}}' | RELEASE_ACK_FILE=/tmp/x <path-to-script>
echo "exit=$? (expect 0)"
```

A structural check alone (`bash -n`) is not enough — confirm the branches
actually fire (see playbook § Verifying infra).
