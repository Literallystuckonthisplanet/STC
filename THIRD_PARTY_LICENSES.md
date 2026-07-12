# Third-party licenses

STC Core is licensed under AGPL-3.0 + a commercial license (see
[`LICENSING.md`](LICENSING.md)). It also contains small portions **derived from**
third-party open-source work, which retain their original licenses. AGPL-3.0 is
compatible with including MIT-licensed material; the notices below are retained
as required by those licenses.

> Note: STC's `diagnose`, `tdd`, and `worktree` skills were authored by merging
> the maintainer's own commands with the *methodology* of the sources below.
> Where any expression (wording/structure) was adapted rather than independently
> written, the source's MIT notice below governs those portions. If a review
> confirms the skills are wholly original expressions of the (uncopyrightable)
> methodology, these remain courtesy attributions.

## obra/Superpowers — MIT License

- Source: <https://github.com/obra/superpowers>
- Copyright © Jesse Vincent (obra)
- Used in: `core/skills/diagnose/` (← `systematic-debugging`),
  `core/skills/tdd/` (← `test-driven-development`),
  `core/skills/worktree/` (← `using-git-worktrees`).

```
MIT License

Copyright (c) Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

> Verify obra/Superpowers' exact copyright line against its repository `LICENSE`
> before relying on this notice commercially.

## Matt Pocock skills set — methodology credit

- The `prototype` and `improve-codebase-architecture` command methodologies were
  inspired by the Matt Pocock skills set ([total-typescript.com](https://www.total-typescript.com)).
  Methodology/ideas are not copyrightable; no license obligation attaches, but the
  credit is retained.

## Non-bundled tools (no obligation)

graphify, Context7, Playwright, and GLM are **external** tools/services invoked by
STC, not redistributed within it. Their licenses govern those tools, not STC.
