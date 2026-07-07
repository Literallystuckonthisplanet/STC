<!--
PROFILE TEMPLATE. Copy to user/profile.md (gitignored) and fill in.
This is your private layer — who you are, how you work, how the agent should
talk to you. Read by the agent on session start (see core/rules/session.md).
-->

# User profile

## Identity

- **Name:** ${USER_NAME}
- **Role:** developer             <!-- developer | designer | BA/PO | student | ... -->
- **Language:** en                <!-- the language the agent talks to you in (en | ru | ...) -->
- **Timezone:** UTC               <!-- for handoff dates, audit cadence -->

## Git identity (for commits the agent makes on your behalf)

- **Name:** Your Git Name
- **Email:** you@example.com

<!--
NOTE: do NOT put API keys, tokens, or passwords here. Secrets live in
user/secrets.env (also gitignored). Reference them by env-var name only.
-->

## How I work

<!--
Personal workflow preferences that the agent should honor. Concrete and
short — situation → action. Examples below; edit freely.
-->

- **Self-execution scope:** docker / npm / pip / .env / dev servers / browser
  — the agent runs these itself. It asks me only for a value or a decision.
- **Commit style:** small commits, one logical change each, commit-then-push
  immediately (the git-guardrails hook does NOT block push).
- **Long context:** when the agent needs to compress context, it runs
  `/save-and-compact` first, then tells me to run the harness-native compact
  command — it never silently compacts.

## Voice-input dictionary  <!-- optional; delete if not using voice input -->

<!--
Homoglyph / misrecognition corrections for speech-to-text. The agent silently
substitutes the left side with the right when it appears in your prompts.
Keep it short — only entries that actually recur.
-->

| I say | I mean |
|-------|--------|
| PEV | plan–execute–verify (the task loop) |
| ADR | architecture decision record |

## Projects I work on  <!-- pointers only; detail lives in user/projects/<name>.md -->

<!--
One line per project: slug, one-phrase description, where it lives.
The full per-project memory (stack, schema, gotchas, status) lives in
user/projects/<name>.md — see user/projects/example.example.md for the shape.
-->

- (none yet)
