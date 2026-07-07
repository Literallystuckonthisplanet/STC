<!--
TEMPLATE. The /to-spec command copies this structure into
specs/<project>-<feature-kebab>.md with the frontmatter filled in.
Do NOT fill this file in directly — it is the source template.
-->
---
node_type: spec
project: <Project Name>
status: draft
created: YYYY-MM-DD
feature: <feature name>
---

# <Feature name>

## Use cases
1. As [role], I want [action], so that [goal]

## Acceptance criteria
<!-- AC = a checklist with the #ac tag (Dataview/Tasks collect progress).
Replaces a separate AC database. -->
- [ ] [criterion 1] #ac
- [ ] [criterion 2] #ac

## Architectural decisions (ADR)
### <Decision name>
**Decision:** <what was chosen>
**Why:** <rationale>
**Rejected:** <alternatives and why>

## Buy-vs-build (DEP-4)
- [capability] → Took [X] / by hand, because [Y]   (or "n/a" for a trivial task)

## Abuse cases / forbidden scenarios
- [use-case] → bypass vector [how] → countermeasure [what] → negative test [hook]

## Failure modes / typical pitfalls
- [use-case] → symptom [how it shows] → solution/pattern [lay down in design] → how to verify

## Block plan
<!--
For a large task: A/B/C blocks. Each block is an execution slice that becomes
a task via /to-tasks.
-->
### Block A
- A0: <step>
- A1: <step>
