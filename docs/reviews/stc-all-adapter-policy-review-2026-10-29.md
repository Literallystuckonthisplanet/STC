# H17 all-adapter policy review — 2026-10-29

## Initial review: PASS

No code-level bypass or false-negative was found in the frozen scope for the agreed structured-read and Codex command scenarios. The review was read-only; no source or test files were changed.

## Delta review — 2026-10-29

**Final delta verdict: PASS / CLOSED.** The Glob adjustment preserves ordinary wildcard listing (`**/*.md`), refuses a protected-looking pattern, refuses a protected base path, and permits an ordinary literal target (`core/hooks/secret_read_policy.py:354-374`).

Codex shell cwd resolution now considers `tool_input.cwd` and `tool_input.workdir`, resolves relative values against `event.cwd`, and returns `unparsed` when both supplied values resolve differently (`core/hooks/secret_read_policy.py:294-316`). Shell parsing uses the resolved directory (`core/hooks/secret_read_policy.py:386-390`). Focused synthetic cases cover both `command` and `cmd`: an ordinary file in B is allowed, a symlink in B to a protected synthetic file is denied, and conflicting cwd/workdir is refused (`deploy/tests/test_h17_adapter_parity.py:71-113`). Structured Grep deliberately ignores its unknown `workdir` field (`deploy/tests/test_h17_adapter_parity.py:116-130`).

Focused validation: `pytest -q deploy/tests/test_h17_adapter_parity.py -k 'workdir or glob or structured_read_policy_parity'` passed. The review did not access installed hooks, real secret files, credentials, clipboard, authentication, or external services. An earlier direct reproduction attempt was stopped by the active pre-tool guard; the final verdict rests on the reviewed implementation and the existing synthetic tests, not that attempt.

## Evidence checked

- `core/hooks/secret_read_policy.py:80-103` resolves paths against the event working directory, follows symlinks, handles `..`, and refuses literal home expansion for shell-shaped targets.
- `core/hooks/secret_read_policy.py:110-199` distinguishes `rg` expressions from path operands, treats `-f` as a file target, refuses unsupported protected-looking syntax, and requires the complete canonical exclusions for directory scans.
- `core/hooks/secret_read_policy.py:216-291` checks Codex shell path fields, preserves command/cmd conflict refusal, checks sibling raw fields for protected hints, and only skips the selected search command text.
- `core/hooks/secret_read_policy.py:294-341` keeps `Grep.pattern` separate from target paths, refuses structured directory walks without complete exclusions, and refuses wildcard `Glob` selectors.
- Adapter mappings bind Claude and ZCode to `Read|Glob|Grep` (`adapters/claude/adapter.yaml:132`, `adapters/zcode/adapter.yaml:126`) and bind Codex to those tools plus `Bash`, `exec`, `unified_exec`, and `unifiedExec` (`adapters/codex/adapter.yaml:155-157`). The Codex wrapper runs the shared policy for those shell tools (`core/hooks/block-secret-read.sh:13-14`); the Claude/ZCode wrapper selects the declared harness (`core/hooks/secret-read-guard.sh:14-16`).
- The parity cases exercise query text containing protected words, direct and traversing reads, symlink targets, directory-scan refusal, wildcard refusal, and structured writes outside the guard (`deploy/tests/test_h17_adapter_parity.py:35-119`). Existing Codex cases cover command/cmd conflict, sibling raw fields, supported `rg` scans, `-f` files, and unsupported commands (`deploy/tests/test_hook_behavior.py:756-997`).

## Initial findings

None requiring a fix within the agreed behavior at the time of the initial review.

## Validation boundary

This is a source and focused synthetic-test review, not proof of live hook delivery. In particular, ZCode's adapter remains frozen and documents the historical condition that plugin hooks registered but did not fire (`adapters/zcode/adapter.yaml:17-25`); its binding is present in configuration, but runtime enforcement is not established by this review. Claude's native deny layer is also not evidence that all three adapters enforce identically. No full suite, installed-home guard, real secret, credential, clipboard, authentication, or live external service was accessed.
