# ClaudeIsland

Notch live-activity for Claude Code (macOS). Deep reference: `src/island/ARCHITECTURE.md`.

## Build
```bash
node bin/cli.js install --no-hooks
```
- No manual `pkill` needed. The installer compiles/signs a staged `.app` in tmp first, then unloads the LaunchAgent only for the final app swap/relaunch. If launch fails, it rolls back to the previous app.
- Use `--no-hooks` for normal rebuilds so Claude settings are left alone. Use `--yes` for first install / hook refresh, or run interactively.
- If macOS asks for file/automation permissions after every rebuild, ad-hoc signing is the cause. Create/use a persistent local Code Signing identity named `Claude Island Local`, or set `CLAUDE_ISLAND_CODESIGN_IDENTITY` before install.
- Compile-only check (no install/kill): `swiftc -O -o /tmp/x src/island/island.swift -framework Cocoa -framework SwiftUI 2>&1 | grep -i error` (empty = clean). Ignore `+`/`onChange` deprecation warnings.
- Other: `node bin/cli.js test` (cycle states), `uninstall`.

## Animation in the panel
The island is a non-activating `NSPanel`: SwiftUI's animation clock doesn't tick there. `withAnimation(.repeatForever)` and bare `TimelineView(.animation)` freeze. Animate only via a self-stepped `Timer` + `@Published` (see `Ticker`, `WobbleClock`). Note `Ticker.shared` is stopped in `attention`/`idle` modes, so anything relying on it freezes in those states — give resting-state motion its own clock.

## Render paths for the `!`/status marker (patch all that apply)
- Front pill, ≥2 sessions: `leading` → `aggKind` switch.
- Front pill, single: `leadingSingle` → `state.mode` switch.
- Dropdown: `rowMarker(_:)` (dot/`!`) and `dropdownRow(_:)` (verb + title + grey preview).
- `Spinner`'s `.attention`/`.done` cases are mostly unused for the pill — editing it won't change the visible `!`.

## Add a per-session field (thread all 6)
`island-hook.py` (extract from transcript; add to **both** full emits and keep emits when retention matters) → `SessionFile` → `LiveSession` → `merge` → `makeCard` → `SessionCard`.

## Inspect state
- `~/.claude-island/sessions/<tabUUID>.json` — exact payload the daemon reads.
- `~/.claude/projects/<slug>/<id>.jsonl` — CC transcript (titles/preview/prompt/context). Types: `user` (skip `isMeta`/tool_result), `assistant`, `ai-title`, `custom-title`.

## Flags
- `kRowTitleUsesPrompt` (top of `island.swift`): dropdown rows lead with the latest user prompt (falls back to the opening prompt, then tab name) vs tab name. Done/stale rows show the agent's response regardless.
