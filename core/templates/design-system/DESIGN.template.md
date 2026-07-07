<!--
TEMPLATE. Copy to the project root as DESIGN.md and fill it in.
This is a machine-readable brief — the agent reads it BEFORE generating UI.
Fill it in CONCRETELY: not "a modern font", but "Bricolage Grotesque".
Process → core/templates/design-system/process.md
-->
<!-- T03 -->
# DESIGN.md — <Project name>

## Project Type
<!-- Variant B: classification. Pick an archetype → it loads the relevant overlay from process.md §2 -->
**Type:** `<landing | e-commerce | saas-app | admin | content-docs>`
**Overlay elements** (from process.md §2 for this type): <list them, e.g. for e-commerce: Product card, Gallery, Badge, Review stars, PDP, Checkout, mobile-tap>

---

## 1. Visual Theme & Atmosphere
<!-- Emotional direction. Pick an EXTREME, not "clean and modern". -->
- **Tone / direction** (one of, or your own): editorial magazine / brutalist raw / luxury refined / retro-futuristic / organic-natural — `<pick>`
- **Memorable takeaway:** what the user should remember after the visit — `<one phrase>`
- **Primary user persona:** `<name, age, context>` — the agent designs for a specific person

## 2. Color Palette & Roles
<!-- A DOMINANT + 1 accent + neutrals. NOT 5-6 equal pastels. -->
- **Dominant** (strong, not pastel): `<oklch/hex>` → `--color-primary`
- **Accent** (1): `<oklch/hex>` → `--color-accent`
- **Neutrals:** `<background, surface, foreground, muted, border>`
- **Semantic:** `--color-danger`, `--color-success`, `--color-info`
- Background: `<NOT solid white/gray — mesh gradient / noise / grain / warm off-white>`

## 3. Typography
<!-- A pair of fonts. FORBIDDEN: Inter, Roboto, system-ui, Space Grotesk (defaults = generic AI look). -->
- **Display / heading** (with character): `<Playfair Display | DM Serif | Bricolage Grotesque | Syne | your own>`
- **Body:** `<DM Sans | Plus Jakarta Sans | your own — NOT Inter>`
- **Type scale** (custom, not the default): `<e.g. 14/16/20/28/40/56>` with line-height
- Loading: `next/font` (NOT `next/font/google` Inter)

## 4. Component Stylings
<!-- Base atoms + states (default/hover/focus/disabled/error). Tier 3 tokens. -->
- Button (variants: primary/secondary/ghost), Input, Badge, Card, Link — `<style, radius, states>`
- Type-specific components (from the Project Type overlay) — `<style>`

## 5. Layout Principles
<!-- A CUSTOM spacing scale (not the Tailwind default 4/8/12/16/24). -->
- **Spacing scale** (your own rhythm): `<e.g. 6/12/20/32/52>`
- **Grid / container:** `<max-width, columns, gutters>`
- **Asymmetry:** where the grid is deliberately broken — `<e.g. hero sections>`

## 6. Depth & Elevation
- **Shadows:** `<scale: sm/md/lg or "flat, no shadows">`
- **z-index layers:** `<base / dropdown / modal / toast>`

## 7. Do's & Don'ts
**DON'T (anti-generic ban list):**
- ❌ Inter / Roboto / system-ui / Space Grotesk
- ❌ purple/blue gradient on white
- ❌ 5-6 evenly distributed pastel colors
- ❌ solid white or solid gray background
- ❌ full symmetry everywhere
- ❌ micro-animations scattered, or none at all

**DO:**
- ✅ one dominant color + an accent
- ✅ a custom spacing scale (your own rhythm)
- ✅ 1-2 staggered reveals on page load
- ✅ deliberate asymmetry in the hero
- ✅ a textured background (mesh/noise/grain/off-white)

## 8. Responsive Behavior
- **Breakpoints:** `<sm/md/lg/xl>`
- **Mobile-first:** yes; tappable targets ≥44px (especially e-commerce)

## 9. Agent Prompt Guide
<!-- Direct instructions to me (the agent) when generating UI for this project. -->
- Read this file BEFORE generating any UI; invoke the `frontend-design` skill.
- Use tokens from `@theme` (Tier 1+2), not ad-hoc inline styles.
- For a new layout — ASCII-markup the structure first, then code.
- Stick to the Tone/persona from §1; cross-check against Do's & Don'ts §7.
- Verify: screenshot the result → compare to this DESIGN.md → list the gaps → fix them.
