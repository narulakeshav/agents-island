#!/usr/bin/env python3
"""codex-watch.py — surface OpenAI Codex sessions as island cards.

WHY A WATCHER AND NOT A HOOK
  Codex has nothing like Claude Code's hooks. Its only callback is config.toml's
  `notify`, which is (a) a SINGLE program, not a list — claiming it would silently
  displace whatever already owns it (Codex Computer Use ships pointing at it) — and
  (b) turn-end only, far too coarse to drive a live pill.

  But Codex writes a rollout JSONL per session under
  ~/.codex/sessions/<Y>/<M>/<D>/rollout-<ts>-<uuid>.jsonl, and it carries everything
  the island renders: task_started (turn clock + context window), function_call (the
  live verb), agent_message (the reply), token_count (the ring), task_complete /
  turn_aborted (the terminal states). So we tail those instead — the same move
  subagent-watch.py makes for subagents the hooks can't see.

KEYING, FOCUS, AND LIVENESS
  Codex Desktop hosts every chat inside ONE `codex app-server` process, so unlike
  Claude Code there's no per-session process to scan and no tty to key on. We key on the
  rollout's session id (`cdex-<sha1[:16]>`). Liveness can't come from a process either —
  a session is "live" while its rollout is still being written (mtime within LIVE_WINDOW),
  and this watcher owns the whole lifecycle: writes the card while warm, deletes it cold.

  Focus is a real per-conversation deep link: the app registers the `codex://` scheme and
  `codex://threads/<id>` opens a specific chat, where <id> is exactly the rollout's
  session id (== threads.id in the state DB). So a click jumps to the exact conversation,
  the same fidelity as Warp — not just fronting the app.

WHAT COMES FROM WHERE
  Two Codex-internal thread kinds (subagent delegates, scheduled automations) write
  rollouts that look just like a chat; session_meta.thread_source is the only tell, so we
  filter on it. Titles/preview are enriched from the desktop app's thread store
  (~/.codex/state_*.sqlite) when present — Codex's own titles beat scraping the first
  prompt — but that DB is a best-effort enhancement, never required.

WHY `transcript` IS DELIBERATELY EMPTY
  The daemon's Claude-specific reconcile paths — refreshLiveness() and
  pollLiveStatus() — both skip any session without a transcript. Leaving it empty is
  what keeps logic that only understands CC transcripts from flipping a Codex card to
  "interrupted". These cards are owned start-to-finish by this watcher.

USAGE
  codex-watch.py --once            # one pass
  codex-watch.py --watch           # poll forever (default interval 2s)
  codex-watch.py --once --dry-run  # print what would be sent, touch nothing
"""
import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

# thread_source values that are NOT a person's conversation — a Codex subagent (a Task-style
# delegate) or a scheduled automation run. Both write rollouts indistinguishable from a real chat
# except for this field, so without the filter they'd each surface a phantom card.
INTERNAL_SOURCES = {"subagent", "automation", "codex_sdk_ts"}

HOME = os.path.expanduser("~")
CODEX_SESSIONS = os.path.join(HOME, ".codex", "sessions")
# The desktop app's thread store. Optional enhancement, not a dependency: it gives us Codex's
# own generated titles (far better than scraping the first prompt) and the settled preview. The
# filename carries a schema version, so match the newest state_*.sqlite rather than pinning one.
CODEX_STATE_GLOB = os.path.join(HOME, ".codex", "state_*.sqlite")
ISLAND_DIR = os.path.join(HOME, ".claude-island")
HERE = os.path.dirname(os.path.abspath(__file__))
# island-send lives next to us inside the app bundle; fall back to the installed app so this
# script also works when run straight out of a source checkout.
SEND = os.path.join(HERE, "island-send")
if not os.path.exists(SEND):
    SEND = os.path.join(HOME, "Applications", "ClaudeIsland.app", "Contents", "MacOS", "island-send")

# A rollout untouched this long → the session is cold and its card goes away. Overridable so a
# demo/debug run can reach back past the last real session instead of waiting for a live one.
LIVE_WINDOW = float(os.environ.get("CODEX_WATCH_LIVE_WINDOW", "600"))
TAIL_BYTES = 256 * 1024    # bounded tail read; rollouts grow without limit
POLL_S = 2.0
CLIP = 140

# Codex tool name → the island's verb, mirroring island-hook.py's map so a Codex row reads
# like a Claude one. Unknown tools fall back to the raw name (same as the hook does).
VERBS = {
    "exec_command": "Running",
    "write_stdin": "Running",
    "js": "Running",
    "view_image": "Viewing",
    "update_plan": "Planning",
    "automation_update": "Updating",
    "load_workspace_dependencies": "Loading",
    "js_add_node_module_dir": "Loading",
}


def short_hash(s):
    return hashlib.sha1((s or "").encode("utf-8", "replace")).hexdigest()[:16]


def clip(s, n=CLIP):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n].rstrip() + "…"


def user_text(msg):
    """The user's ACTUAL words out of a user_message.

    Codex Desktop doesn't send what you typed — it wraps it. The message opens with an
    <in-app-browser-context> block of ambient UI state (`text_elements` is empty, so there's no
    structured copy to read instead), and the real prompt follows under a "## My request for
    Codex:" heading. Taking `message` raw makes every card's title read
    '<in-app-browser-context source="ambient-ui-state"…'. Returns "" for a message that is pure
    injected context, so it's skipped as a prompt rather than titling a card with machinery.
    """
    s = msg or ""
    i = s.find("</in-app-browser-context>")
    if i >= 0:
        s = s[i + len("</in-app-browser-context>"):]
    m = re.search(r"#+\s*My request for Codex:\s*", s)
    if m:
        s = s[m.end():]
    elif s.lstrip().startswith("<in-app-browser-context"):
        return ""   # nothing but ambient state — not a prompt
    return s.strip()


def read_first_line(path):
    try:
        with open(path, "r", errors="replace") as f:
            return json.loads(f.readline())
    except Exception:
        return None


def read_tail_events(path):
    """Last TAIL_BYTES of the rollout as parsed events, dropping the leading partial line."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > TAIL_BYTES:
                f.seek(size - TAIL_BYTES)
            blob = f.read()
    except Exception:
        return []
    lines = blob.decode("utf-8", errors="replace").split("\n")
    if size > TAIL_BYTES:
        lines = lines[1:]
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def tool_verb(name, arguments):
    """'<verb> <target>' for a function_call, mirroring the hook's tool_verb()."""
    label = VERBS.get(name, name or "")
    target = ""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except Exception:
        args = {}
    if isinstance(args, dict):
        if name in ("exec_command", "write_stdin"):
            cmd = (args.get("cmd") or args.get("command") or "").strip().split()
            target = cmd[0] if cmd else ""
        elif name == "view_image":
            target = os.path.basename(args.get("path") or "")
    return (label + " " + target).strip()


def db_titles():
    """{session_id: {"title", "preview"}} from the desktop app's thread store, or {} if it's
    absent/locked/renamed. Read-only (mode=ro, never immutable=1 — a mid-turn write lands in the
    WAL, which immutable can't see) and fully best-effort: a missing DB just means we fall back
    to the scraped-first-prompt title. Codex's own titles ("Clarify Hex content types") beat any
    heuristic on the raw prompt, which is why this is worth a try."""
    dbs = sorted(glob.glob(CODEX_STATE_GLOB))
    if not dbs:
        return {}
    out = {}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % dbs[-1], uri=True, timeout=0.5)
        try:
            # id IS the rollout's session_id (verified against rollout_path), so no join needed.
            for tid, title, preview in con.execute(
                    "SELECT id, title, preview FROM threads"):
                if tid:
                    out[tid] = {"title": (title or "").strip(),
                                "preview": (preview or "").strip()}
        finally:
            con.close()
    except Exception:
        return {}
    return out


def derive(path, titles=None):
    """Walk a rollout into the island's session shape. None if it isn't usable or is an internal
    (subagent/automation) thread. `titles` is the optional db_titles() index."""
    meta = read_first_line(path)
    if not meta or meta.get("type") != "session_meta":
        return None
    m = meta.get("payload") or {}
    session_id = m.get("session_id") or m.get("id") or ""
    cwd = m.get("cwd") or ""
    if not session_id:
        return None
    # session_meta carries thread_source itself, so the leak is filtered here without needing the
    # DB. Legacy rollouts predate the field (None) — those we keep; only drop the known-internal.
    if m.get("thread_source") in INTERNAL_SOURCES:
        return None

    mode, detail, preview = "done", "", ""
    first_prompt, last_prompt = "", ""
    started_at, turn_id, ctx_window, tokens = 0.0, "", 0, 0
    done_ts = 0.0

    for e in read_tail_events(path):
        p = e.get("payload")
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "task_started":
            # A new turn: reset the per-turn signals so a finished turn's reply can't bleed
            # into the next one's pill.
            mode, detail, preview = "thinking", "Thinking…", ""
            started_at = float(p.get("started_at") or 0) or started_at
            turn_id = p.get("turn_id") or turn_id
            ctx_window = int(p.get("model_context_window") or 0) or ctx_window
        elif t == "user_message":
            msg = user_text(p.get("message"))
            if msg:
                last_prompt = msg
                if not first_prompt:
                    first_prompt = msg
        elif t == "agent_reasoning":
            # The reasoning text is a sentence, not a verb — it would blow out the pill's left
            # side, so it stays out of `detail` (the island shows the turn timer there anyway).
            mode, detail = "thinking", "Thinking…"
        elif t == "function_call":
            vw = tool_verb(p.get("name"), p.get("arguments"))
            mode, detail = "working", (vw + "…" if vw else "Working…")
            preview = vw or preview
        elif t == "agent_message":
            preview = p.get("message") or preview
        elif t == "token_count":
            # last_token_usage, NOT total_token_usage: the latter ACCUMULATES every turn's usage
            # across the whole session, so dividing it by the window gives nonsense like 550%
            # full. The last turn's total is what actually approximates context fill.
            info = p.get("info") or {}
            usage = info.get("last_token_usage") or {}
            tokens = int(usage.get("total_tokens") or 0) or tokens
            ctx_window = int(info.get("model_context_window") or 0) or ctx_window
        elif t == "context_compacted":
            mode, detail, preview = "compacted", "Compacted", ""
        elif t == "task_complete":
            mode, detail = "done", ""
            preview = p.get("last_agent_message") or preview
            done_ts = float(p.get("completed_at") or 0) or done_ts
        elif t == "turn_aborted":
            # Codex records the abort explicitly, so we don't need the marker-sniffing the CC
            # path relies on.
            mode = "interrupted"
            detail = ""
            done_ts = float(p.get("completed_at") or 0) or done_ts

    ctx = round(tokens / ctx_window, 4) if (ctx_window and tokens) else 0.0
    # Title: Codex's own generated title (from the DB) is best; fall back to the scraped first
    # prompt, then the directory. Preview: the LIVE rollout signal (verb / streamed reply) wins
    # so a mid-turn card reads true; the DB's settled preview only fills in when the tail had none.
    db = (titles or {}).get(session_id) or {}
    # clip() the chosen title regardless of source — a DB title can itself be a multi-line first
    # message on threads Codex never named, and a raw newline would break the pill layout.
    title = clip(db.get("title") or first_prompt
                 or (os.path.basename(cwd.rstrip("/")) if cwd else "Codex"), 48)
    preview = preview or db.get("preview") or ""
    return {
        "tab": "cdex-" + short_hash(session_id),
        "mode": mode,
        "detail": detail,
        "preview": clip(preview),
        "project": os.path.basename(cwd.rstrip("/")) if cwd else "",
        "cwd": cwd,
        "context": ctx,
        # Per-conversation deep link — the app registers codex:// and threads.id == session_id, so
        # this focuses the exact chat (like Warp's warp://session/<uuid>), not just the app. The
        # daemon opens any URL-shaped focus via NSWorkspace, so no Swift change is needed.
        "focus": "codex://threads/" + session_id,
        "aiTitle": title,
        "firstPrompt": clip(first_prompt),
        "lastPrompt": clip(last_prompt),
        "turn_id": turn_id,
        "started_at": started_at,
        "done_ts": done_ts,
        "transcript": "",   # see module docstring — this is load-bearing
    }


def send(tab, payload, dry_run=False):
    out = "sessions/%s.json" % tab
    if dry_run:
        print(out, json.dumps(payload, indent=2)[:600])
        return
    try:
        p = subprocess.Popen([SEND, out], stdin=subprocess.PIPE)
        p.communicate(json.dumps(payload).encode("utf-8"))
    except Exception:
        pass


def sweep(seen_turn, dry_run=False):
    """One pass: refresh warm sessions, drop cold ones."""
    now = time.time()
    rollouts = glob.glob(os.path.join(CODEX_SESSIONS, "**", "rollout-*.jsonl"), recursive=True)
    titles = db_titles()   # one DB read per sweep, shared across every session below
    warm = set()
    live = 0
    for path in rollouts:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if now - mtime > LIVE_WINDOW:
            continue
        s = derive(path, titles)
        if not s:
            continue
        live += 1
        tab = s["tab"]
        warm.add(tab)
        # kind="prompt" is what seeds the daemon's turn clock (merge() copies ts → turnStartTs),
        # so it must be sent ONCE per turn carrying the turn's real start — not on every pass,
        # which would keep resetting the elapsed timer to zero. Every later update rides as
        # "tool"/"stop" with a fresh ts, which only moves the staleness clock.
        new_turn = s["turn_id"] and seen_turn.get(tab) != s["turn_id"]
        if new_turn and s["mode"] not in ("done", "interrupted"):
            seen_turn[tab] = s["turn_id"]
            kind, ts = "prompt", (s["started_at"] or mtime)
        elif s["mode"] in ("done", "interrupted"):
            kind, ts = "stop", (s["done_ts"] or mtime)
        else:
            kind, ts = "tool", mtime
        payload = {
            "id": tab, "mode": s["mode"], "detail": s["detail"], "preview": s["preview"],
            "project": s["project"], "cwd": s["cwd"], "context": s["context"],
            "focus": s["focus"], "aiTitle": s["aiTitle"], "firstPrompt": s["firstPrompt"],
            "lastPrompt": s["lastPrompt"], "transcript": s["transcript"],
            "kind": kind, "ts": float(int(ts)),
        }
        send(tab, payload, dry_run)
        if new_turn and s["mode"] not in ("done", "interrupted"):
            # The prompt emit only seeds the clock; follow it immediately with the real state so
            # the pill doesn't sit on a bare "thinking" until the next pass.
            payload = dict(payload, kind="tool", ts=float(int(mtime)))
            send(tab, payload, dry_run)

    # Cold sessions: delete the file. The daemon prunes any session whose file vanished, which
    # is what keeps a finished Codex chat from lingering as a phantom card forever. `warm` was
    # collected in the loop above, so this needs no second derive pass.
    if not dry_run:
        for f in glob.glob(os.path.join(ISLAND_DIR, "sessions", "cdex-*.json")):
            if os.path.basename(f)[:-5] not in warm:
                try:
                    os.remove(f)
                except OSError:
                    pass
    return live


def main():
    dry_run = "--dry-run" in sys.argv
    watch = "--watch" in sys.argv
    seen_turn = {}
    if not os.path.isdir(CODEX_SESSIONS):
        print("no ~/.codex/sessions — is Codex installed?", file=sys.stderr)
        return 1
    while True:
        n = sweep(seen_turn, dry_run)
        if not watch:
            print("live codex sessions: %d" % n, file=sys.stderr)
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
