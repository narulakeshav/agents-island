# ClaudeIsland — Vision

> A notch-native, ambient supervisory layer for a fleet of autonomous agents.

## The primitive

Strip away "Claude Code" and the thing underneath is **an ambient attention-router for a fleet of async workers.**

The moment work shifts from *you do the task* to *you direct N agents that do tasks*, the scarce resource stops being your ability to type and becomes your **attention** — specifically, knowing which of N running things needs a decision *right now*, and getting there without losing your place.

Everything the island does — the aggregate headline, the "needs input" escalation, click-to-focus — is attention allocation. It is a **supervisor's console, not a dashboard.**

## Why now

As agents get more parallel and more autonomous, **supervision becomes the bottleneck, and there's no OS-native surface for it.**

The system tray tells you which *apps* are alive. Nothing tells you which *agents* are alive, working, stuck, or waiting on you. Today the answer is "tab through six terminals." That's the opening.

The pattern isn't specific to coding. Anything that is **(1) long-running, (2) async, (3) occasionally needs a human** has the same missing interface: *where do I look to know if my fleet needs me?*

## What it becomes

**The island's end-state isn't a Claude Code widget — it's the menu bar for autonomous work.**

The natural arc is **monitor → controller.** Right now you can *see* "needs input" and *focus* it. The leap is to *act* on it. When you can clear a fleet's decisions from the notch without opening a single terminal, it stops being a nice indicator and becomes the **control plane** for your agents.

The notch is a genuinely good beachhead — not because it's cute, but because it's **dead space you never have to open.** Most agent-management tools are a window or a tab, which defeats the entire purpose: if you have to *go look*, it isn't ambient, and you'll just look at the terminal instead. Living in the periphery is the whole game.

## Three axes of growth

1. **Breadth (sources).** The agent-agnostic session-file schema is a universal adapter. Every new agent type that writes that schema shows up in the same notch. This is how "Claude companion" becomes "the status bar for all your background work." Low integration cost per source, compounding value.

2. **Depth (monitor → control).** The axis that converts *interesting* into *indispensable*. Today: see "needs input," focus it. Next: **act without leaving** — approve/deny a permission inline (the most common "needs input" case is a yes/no), answer a question, pause/kill a stuck agent. The day you clear a fleet's decisions from the notch without opening a terminal, it's the control plane, not an indicator.

3. **Reach (cross-device).** The async nature *implies* you should be able to walk away. The natural extension of "it'll tell me when it needs me" is "…on my phone." Approve a permission from your pocket. Later — the desktop loop has to be undeniable first.

## What we can absorb today

The key realization: **you don't need per-integration engineering for most of it — you need to expose the seam.** The session-file schema (`~/.claude-island/sessions/<id>.json`) is already the universal contract; anything that writes `{status, label, detail, needs-input?, done?, focus-target}` shows up.

**Tier 1 — one adapter absorbs a whole class.** A public `island emit` / `island wrap -- <cmd>` CLI that emits `working → done/error` around any process and streams the last log line as the live detail. That single tool instantly covers:
- **Cron jobs / scheduled scripts** — "did my nightly job finish?" answered in the notch.
- **Long builds / test suites / data pipelines** (make, docker, dbt) — progress as the verb.
- **ML training runs** — "training… epoch 12, loss 0.31," ping when done or diverged. The canonical "kicked it off, keep checking" pain.

**Tier 2 — thin per-source pollers (~50 lines each), added one at a time.** For API-only sources with no local process to wrap:
- **CI runs** (`gh run list --json`) — `working` while running, `attention` when a deploy needs approval, `done`/`error` on finish; click opens the run.
- **Deploys** (Vercel/Netlify) — in-progress → needs-approval → succeeded/rolled-back.
- **PR review queue** — "3 PRs waiting on *your* review" as `attention`; your review is the blocking input.
- **Batch LLM jobs** — poll status → `working` with % complete → `done`.
- **Computer-use / browser agents** — long autonomous runs that hit a login wall or CAPTCHA surface as `attention` ("needs login"). A killer attention case — these get stuck on human-verification constantly.
- **Research / deep-research agents** — `working` with the current sub-step, `attention` on a clarification, `done` when the report's ready (focus = the output file).

**The picture, today:** one notch reading *"2 need input"* (a Claude permission + a browser agent stuck at a login), *"3 running"* (a CC session, an ML run at epoch 12, a CI build), *"1 done"* (the nightly pipeline). Four different tools, one glance.

**Be opinionated about what earns the notch.** A source belongs only if it (a) runs long enough that you'd otherwise poll it, and (b) occasionally needs a decision or produces a result you're waiting on. A backup that never needs you and you never wait on is noise. CI that gates your merge, training you're waiting on, an agent that gets stuck — yes.

## The discipline — useful, not just interesting

The failure mode of every ambient dashboard is becoming **wallpaper**: pretty, then ignored. Three rules hold the line.

- **Its best state is showing nothing.** The value is in the *silence between signals*. An island that's usually dark and empty, and only earns your eye when something genuinely needs you, is one you learn to trust. Guard the interrupt threshold jealously — too noisy and you ignore it, too quiet and you go back to polling. The entire product is the calibration of that one threshold.

- **Every feature must pass "does this change what I *do*, or just what I *see*?"** The context ring passed — it changes whether you wrap up a session. A cumulative activity graph would fail — interesting, changes nothing. That test is the defense against drifting into dashboard-land.

- **Trust is the moat, and it's brittle.** One wrong "done," one missed "needs input," and the user goes back to the terminal and never fully returns. Accuracy of state detection matters more than any feature. Depth-on-a-few beats breadth-on-many: nail the interrupt-and-act loop for Claude Code so hard people *stop babysitting it* — that proof is what makes the generalization credible.

## The next move

**Close the loop: act on "needs input" from inside the island.** It upgrades the island from a trusted notifier to a fleet controller, directly attacks the #1 reason you still touch the terminal, and passes the "changes what I do" test cleanly.

Breadth (more sources) is the bigger eventual market, but depth is what proves the primitive is real — and a proven primitive is what makes breadth worth anything.

The honest limiter: acting-from-the-island needs *write-back* into each agent, not just reading its state — harder, and per-agent. But that difficulty is the moat. Anyone can read a status file into a menu bar; the loop from *signal → decision → acted* is the defensible part.
