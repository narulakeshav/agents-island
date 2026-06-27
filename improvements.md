# Claude Island — Improvements & Tech Debt

A running list of known rough edges and follow-ups for the notch live-activity UI
(`src/island/island.swift`, `src/island/island-hook.sh`). Ordered roughly by payoff.

## High value

- **Consolidate dropdown geometry into one source of truth.**
  Row / ring / timer positions are currently re-derived independently in the SwiftUI
  view (`dropdownRow`) and the controller's mouse hit-test (`updateRowHover`,
  `pointInIslandHitArea`, `dismissDropdownIfOutside`). They share only loose constants,
  so any layout tweak can silently desync hover/hit areas from what's drawn. Define the
  row layout (x bands for marker/title/preview/ring/timer, item heights) in one place
  both sides consume.
  - The ring hover band estimates the timer width with `textWidth(card.elapsed, kTimerFont)`
    using a *proportional* font, while the timer is rendered `.monospacedDigit()` — the
    estimate is close but not exact. Same-metrics measurement would remove the fudge.

- **Brittle magic numbers.** Glass tint/gradient stops, thresholds (ring ≥25%,
  amber >30%, red >50%, stale 15min), paddings, peek/offset constants, and hit-test px
  fudges (`-30`, `12`, `10`, `-6`) are inline literals scattered across the file. Pull
  into a small named "theme"/layout struct so they're tunable and self-documenting.

## Medium value

- **Timer durability across daemon restarts.** `turnStartTs` lives only in daemon
  memory and is set on the `prompt` event, so a restart mid-turn drops the dropdown
  timers until the next prompt. (We tried persisting it via the hook + session JSON and
  reverted it as it caused issues — revisit with a cleaner approach, e.g. derive turn
  start from the transcript on demand in the daemon only when needed.)

- **Menu-bar passthrough relies on cursor motion.** Click-through is driven by toggling
  `panel.ignoresMouseEvents` from the global/local mouse-move monitors. It works because
  the cursor moves before a click, but a teleport-then-click (e.g. trackpad tap warp)
  could land a stale state for one event. Consider also recomputing on `mouseDown`.

- **Concurrency on `island.swift`.** Multiple agents editing the same file in the same
  working tree is working by luck. Serialize edits / avoid concurrent writers.

## Low value / housekeeping

- **Deprecation warnings.** `onChange(of:perform:)` (deprecated macOS 14) fires twice;
  migrate to the zero/two-parameter `onChange`.
- **Stale test fixtures.** `~/.claude-island/sessions/*.json` accumulate synthetic
  sessions (e.g. `glint`, `prosper`) with frozen timestamps / partial fields that render
  odd states. Add a cleanup or ignore non-live tabs more aggressively.
- **Package rename still pending** (per project memory: banner→notch pivot done, rename
  not yet shipped).
- **`idle_prompt` settles interrupted turns to "Finished"** — a small white lie (the
  turn was interrupted, not finished). Acceptable, but a dedicated neutral/"Stopped"
  state would be more truthful.
- **Verb bucket includes `Thinking` and `Working`**, which overlap the fixed
  "Thinking…" state and the `working` usage. Harmless; drop if exactness matters.

## Notes on what's solid (don't regress)

- Real behind-window glass (`NSVisualEffectView`) — SwiftUI `.ultraThinMaterial` and a
  nil `hitTest` both provably *don't* work in this non-activating panel; verified.
- Freezing dropdown row order while open (no reshuffle under the cursor).
- Stateless title read: `/rename` (`custom-title`) preferred over `ai-title`, picked up
  by the daemon's liveness scan without needing further tab activity.
