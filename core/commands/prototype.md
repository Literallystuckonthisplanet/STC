---
description: "Fast, throwaway exploration before committing to an approach. Two modes: LOGIC (a tiny interactive terminal app that pushes a state machine through hard cases) and UI (several radically different UI variations on one route, switchable via a URL search param + a floating bottom bar). Use when the user wants to prototype, sketch, or 'see how this feels' before building."
---

# Prototype
<!-- S08 -->

Fast, throwaway exploration. The point is to learn cheaply before committing.
The code is disposable — do not polish it, do not productionize it, do not
write it into the real codebase.

Ask the user which mode, or infer from the question:

- **"Does this logic / state model feel right?"** → **LOGIC mode.** Build a
  tiny interactive terminal app that drives the state machine through the
  cases that are hard to reason about on paper.
- **"What should this look like?"** → **UI mode.** Generate several radically
  different UI variations on a single route, switchable via a URL search param
  and a floating bottom bar.

## Shared rules (both modes)

- **Throwaway location.** Prototype in `prototype/` (gitignored) or a scratch
  dir — never in the real source tree. Say where it lives so the user can
  nuke it.
- **Fastest path to signal.** Hardcode data, skip auth, mock services, ignore
  styling polish. Whatever gets the user clicking / typing through the real
  decision fastest.
- **One decision per prototype.** A prototype answers one question ("does this
  flow feel right?", "which of these layouts reads better?"). If two
  unrelated questions are open, run two prototypes.
- **Explicit stop condition.** State up front: "This prototype answers:
  _[question]_. We're done when _[you can compare and pick]_."
- **No tests, no types polish, no error handling beyond what blocks the demo.**
  This is not production code. Say so.

## LOGIC mode — interactive state-machine probe

Goal: stress-test a state machine, algorithm, or data flow against the inputs
that are hard to reason about abstractly.

1. **Identify the hard cases first.** Before writing any code, list with the
   user the cases that are genuinely uncertain — edge transitions, concurrent
   updates, ambiguous inputs, rollback paths. The prototype exists to exercise
   these, not the happy path.
2. **Build the smallest terminal app that drives the model.** stdin prompts,
   printed state, a REPL. No HTTP, no DB, no UI. If the model lives in a
   module, import it directly; if not, copy the minimum logic into the
   prototype.
3. **Make every transition visible.** Print state before and after each step.
   The user should see the model move, not infer it.
4. **Make invalid paths fail loudly.** If a transition is illegal, print
   exactly why — silent rejection teaches nothing.
5. **Drive it through the hard cases together.** Hand the user the terminal
   and the list from step 1. Watch which cases surprise.
6. **Capture the verdict.** What did the prototype reveal? Which assumptions
   held, which broke? This is the artifact — not the code.

```
Example shape (language-agnostic):

  state = INITIAL
  print(state)
  while True:
      event = input("> ")
      prev = state
      state = transition(state, event) or illegal(state, event, prev)
      print(f"  {prev} --{event}--> {state}")
```

## UI mode — multi-variation explorer

Goal: let the user compare radically different UI treatments of the same
screen side by side, switching between them without rebuilding.

1. **One route, N variations.** Pick the single route/page in question.
   Generate **3–5 radically different** variations — not minor tweaks.
   Different layouts, different information density, different interaction
   models. If they feel similar, they're not different enough.
2. **Switch via URL search param + floating bar.**
   - `?variant=a`, `?variant=b`, …
   - A small fixed-position bar at the bottom of the page lists the variants
     as links, so the user flips between them in one click without losing
     context.
3. **Same data, same route, different render.** The variations share mock data
   and routing — only the rendering differs. This isolates the visual decision
   from the data decision.
4. **Hardcoded mock data.** No API calls, no auth, no state management beyond
   what the screen needs. The data is a constant.
5. **No shared component library polish.** Each variant is self-contained
   inline markup/styles. Pulling in the design system slows the comparison
   and biases toward "the one that matches the existing components."
6. **Capture the verdict.** Which variant did the user pick, and why? What
   did the comparison reveal about the screen's priorities? That's the
   artifact.

```html
<!-- floating variant switcher — same on every variant page -->
<nav style="position:fixed;bottom:0;left:0;right:0;background:#111;color:#fff;
            display:flex;gap:1rem;padding:0.75rem 1rem;font-family:system-ui;
            z-index:9999;justify-content:center;">
  <a href="?variant=a" style="color:#fff">A — [label]</a>
  <a href="?variant=b" style="color:#fff">B — [label]</a>
  <a href="?variant=c" style="color:#fff">C — [label]</a>
</nav>
```

## When to stop prototyping

Stop the moment the decision is made. Then **delete the prototype** (or leave
it in `prototype/` if the user wants to revisit). Do not migrate prototype
code into the real codebase wholesale — the real implementation should be
built properly (tests, types, error handling) informed by what the prototype
taught.

---

## Supporting sources

Migrated from the user's `~/.claude/commands/prototype.md` (originally from
the Matt Pocock skills set — partially installed, so cross-links to `LOGIC.md`
and `UI.md` dangle). Per Decision 1 in `docs/PROGRESS.md`, the dangling
cross-links were resolved by inlining the LOGIC and UI methodologies into this
file. Check for upstream drift during the monthly `infra-audit`.
