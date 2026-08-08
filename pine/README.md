# Pine Scripts

Versioned Pine Script sources kept in the repo. Unlike `scripts/current.pine` (the
gitignored scratch file used by the push/pull loop), files here are tracked so a
known-good version can always be pushed back to TradingView.

## Scripts

| File | Type | Pine | Overlay | License |
|---|---|---|---|---|
| `smart-money-concepts.pine` | Indicator | v5 | Yes | CC BY-NC-SA 4.0 — © LuxAlgo |

### `smart-money-concepts.pine`

Smart Money Concepts (SMC) structure indicator. Draws, on the price chart:

- **Swing structure** — BOS / CHoCH lines and labels on swing pivots (`Show Swing Structure`, pivot length via `Show Swings Points`, default 50)
- **Internal structure** — the same on 5-bar internal pivots, dashed, with an optional confluence filter
- **Order blocks** — internal (default 5) and swing (off by default), filtered by ATR or cumulative mean range, mitigated on close or high/low
- **EQH / EQL** — equal highs and lows within an ATR-scaled threshold
- **Fair value gaps** — off by default; optional higher-timeframe source and auto threshold
- **MTF highs & lows** — previous daily / weekly / monthly high and low levels (all off by default)
- **Premium / equilibrium / discount zones** — off by default
- **Strong/Weak High/Low** — trailing swing extremes, labelled by the current swing bias

16 `alertcondition` hooks are exposed (BOS, CHoCH, OB breakouts, EQH/EQL, FVG) for
both internal and swing variants.

Terminology matches the `glossaire-smc` skill (BOS, CHoCH, OB, FVG, LQ).

## Reading it from Claude

The indicator draws with `line.new()`, `label.new()` and `box.new()`, so its output
is invisible to `data_get_study_values`. Use the Pine graphics tools with a filter
instead:

```
data_get_pine_lines   study_filter: "Smart Money"   → BOS/CHoCH lines, MTF levels
data_get_pine_labels  study_filter: "Smart Money"   → BOS, CHoCH, EQH, EQL, Strong/Weak High/Low
data_get_pine_boxes   study_filter: "Smart Money"   → order blocks, FVGs, premium/discount zones
```

The study must be visible on the chart for those tools to return anything.

## Pushing a script to TradingView

TradingView must be running with CDP on port 9222 (`scripts/launch_tv_debug_*`),
with the Pine Editor open on the script you want to overwrite.

```bash
node scripts/pine_push.js pine/smart-money-concepts.pine   # inject + compile + report errors
node scripts/pine_pull.js pine/smart-money-concepts.pine   # pull the editor back into the file
```

Both scripts still default to `scripts/current.pine` when no path is given, which is
what the `pine-develop` skill loop uses.

Note that `pine_push.js` overwrites whatever is currently open in the Pine Editor —
open a new blank script first if you don't want to clobber your working code.

## Licensing

The repository is MIT (see `../LICENSE`), but `smart-money-concepts.pine` is **not**.
It is published by LuxAlgo under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/): attribution
required, **non-commercial use only**, and derivatives must be shared alike. The
license header at the top of the file is part of that license — keep it intact, and
keep it on any modified copy.
