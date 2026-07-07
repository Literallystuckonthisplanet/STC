# Failure-modes catalog (typical pitfalls + solutions, per use-case)

A reference catalog. Not loaded into always-context; read when writing a
spec for EACH use-case, and as a debug-reflex before any edit to business
logic.

**The idea.** Pitfalls cannot be caught by trial-and-error along the way —
they must be **known in advance and laid down at design time**, exactly as
negative AC and security NFRs. **The scope is all business logic, not only
integrations:** an ordinary scenario — password authentication, "add to
cart" — has its own failure-modes too. Tied to a **use-case**, not to a
technology/file. Symmetrical to `reference_abuse_cases.md`: there it is
"how they will break it" (abuse), here it is "where it will
stall/break" (failure) — both are enumerated for EACH spec use-case.

Connected: `reference_defect_ledger.md` (a caught defect → a row here,
design-time prevention) · `reference_abuse_cases.md` (the sibling, the
abuse angle) · PEV (the Plan phase).

## When to read / populate
- **The spec (the main layer): on EACH use-case** enumerate its
  failure-modes + abuse-cases (as AC/NFR). The hook on the file path is
  only a coarse backstop — it does not know the use-case.
- **Debug-reflex (universal, no own/third-party split):** on any bug —
  first the authoritative source/contract (library docs, the API spec,
  the module's own contract), then the edit. Not a trial of symptomatic
  patches.
- **Population:** each caught defect from `reference_defect_ledger.md` → a
  row under the corresponding use-case.

## Format

Grouped by **use-case** (a business scenario). Inside:
`symptom → cause → solution/pattern → how to verify`.

## The registry (by use-case)

<!--
Seed with your own project's use-cases. One use-case can have several
failure-mode rows. Example shape:

### Checkout · choosing a pickup-point on a map widget
- **Symptom:** choosing the map option freezes the page for several seconds.
  - **Cause:** mounting the widget immediately initialises a heavy map with
    all points.
  - **Solution:** lazy-mount — initialise the map ONLY on an explicit click
    "choose on map", not on selecting the radio.
  - **Verify:** an e2e run — select the map option → a point → switch the
    method → re-select the map: the map loads without a reload, 0 console
    errors, the page is clickable throughout.
-->

*(empty — add use-cases here as you spec and debug them)*
