# Vendored: @shape-rotator/shape-ui

`shape-canvas.js` and `tokens.css` are vendored from
[shape-rotator-os/packages/shape-ui](https://github.com/dmarz/shape-rotator-os).

License: MIT, © 2026 dmarz. The `"private": true` flag in the upstream
`package.json` is an npm-publish guard, not a legal restriction
(`transcripts/IMPLEMENTATION_PLAN.md §M.4`).

Only the per-card `mountShape(canvas, opts)` API is consumed here — we
don't use the shared-overlay `data-shape-*` path.
