// Settings.json is the one file the installer mutates in the user's home, so its logic is the
// most dangerous code in the repo — a wrong edit silently eats a user's own hooks. These tests
// pin that behavior. Run: `npm test` (or `node test/settings.test.js`).
//
// The suite drives bin/cli.js's exported pure functions directly (no launchctl / swiftc), against
// a throwaway HOME. HOME must be set BEFORE requiring cli.js — it resolves SETTINGS_PATH at load.

const fs = require("fs");
const os = require("os");
const path = require("path");
const assert = require("assert");

const HOME = fs.mkdtempSync(path.join(os.tmpdir(), "island-test-"));
process.env.HOME = HOME;
const CLAUDE = path.join(HOME, ".claude");
fs.mkdirSync(CLAUDE, { recursive: true });
const S = path.join(CLAUDE, "settings.json");

const cli = require("../bin/cli.js");
const HOOK = "/Users/x/Applications/ClaudeIsland.app/Contents/MacOS/island-hook.py";
const STATUS = "/Users/x/Applications/ClaudeIsland.app/Contents/MacOS/island-statusline.py";

const read = () => JSON.parse(fs.readFileSync(S, "utf8"));
const writeSettings = (o) => fs.writeFileSync(S, JSON.stringify(o, null, 2));
const backups = () => fs.readdirSync(CLAUDE).filter((f) => f.includes("island-backup"));
const clean = () => { for (const f of fs.readdirSync(CLAUDE)) fs.rmSync(path.join(CLAUDE, f), { force: true }); };

let pass = 0, fail = 0;
const t = (name, fn) => {
  try { fn(); console.log("  \x1b[32m✓\x1b[0m " + name); pass++; }
  catch (e) { console.log("  \x1b[31m✗\x1b[0m " + name + "\n      " + e.message); fail++; }
};

// ── The regression that matters: a stranger's own hooks must survive ──────
clean();
writeSettings({
  hooks: {
    Stop: [
      { matcher: "*", hooks: [{ type: "command", command: "~/bin/stop-hook.sh" }] },   // theirs
      { matcher: "*", hooks: [{ type: "command", command: "/x/ClaudeNotify.app/Contents/MacOS/stop-hook.sh" }] }, // legacy ours
    ],
    PreToolUse: [{ matcher: "Bash", hooks: [{ type: "command", command: "~/bin/audit.sh" }] }],
  },
  statusLine: { type: "command", command: "~/bin/my-statusline.sh" },
  model: "opus",
});
assert.strictEqual(cli.configureHooks(HOOK, STATUS), true);

t("user's own ~/bin/stop-hook.sh survives install", () => {
  const cmds = read().hooks.Stop.map((n) => n.hooks[0].command);
  assert.ok(cmds.includes("~/bin/stop-hook.sh"), "user hook eaten: " + JSON.stringify(cmds));
});
t("legacy ClaudeNotify hook is migrated away", () => assert.ok(!JSON.stringify(read()).includes("ClaudeNotify")));
t("unrelated PreToolUse hook preserved", () => assert.ok(read().hooks.PreToolUse.some((n) => n.hooks[0].command === "~/bin/audit.sh")));
t("user's own statusLine not clobbered", () => assert.strictEqual(read().statusLine.command, "~/bin/my-statusline.sh"));
t("unrelated keys (model) preserved", () => assert.strictEqual(read().model, "opus"));
t("all island hooks written", () => Object.keys(cli.HOOK_EVENTS).forEach((e) => assert.ok(read().hooks[e], "missing " + e)));
t("a backup of the original was taken", () => assert.strictEqual(backups().length, 1));

// ── Uninstall strip keeps its hands off other people's hooks ──────────────
t("stripIslandFromSettings removes our hooks, keeps the user's", () => {
  const s = read();
  assert.strictEqual(cli.stripIslandFromSettings(s), true);
  assert.ok(s.hooks.Stop.some((n) => n.hooks[0].command === "~/bin/stop-hook.sh"), "user hook eaten on uninstall");
  assert.ok(!JSON.stringify(s).includes("island-hook"), "our hook not removed");
  // The user brought their OWN statusline, so we never installed ours — uninstall must not touch it.
  assert.strictEqual(s.statusLine.command, "~/bin/my-statusline.sh", "user's statusline wrongly removed");
});
t("stripIslandFromSettings is a no-op on already-clean settings", () =>
  assert.strictEqual(cli.stripIslandFromSettings({ model: "opus" }), false));
t("stripIslandFromSettings DOES remove our own statusline", () => {
  // Empty statusline → configureHooks installs ours → strip must take it back out.
  clean();
  fs.writeFileSync(S, JSON.stringify({}));
  cli.configureHooks(HOOK, STATUS);
  assert.ok(/island-statusline/.test(read().statusLine.command), "ours wasn't installed");
  const s = read();
  assert.strictEqual(cli.stripIslandFromSettings(s), true);
  assert.strictEqual(s.statusLine, undefined, "our statusline not removed on uninstall");
});

// ── Malformed settings.json (the old crash) ──────────────────────────────
clean();
fs.writeFileSync(S, "{ not json ]]}");
const before = fs.readFileSync(S, "utf8");
t("configureHooks returns false, never throws, on unparseable settings", () =>
  assert.strictEqual(cli.configureHooks(HOOK, STATUS), false));
t("the unparseable file is left byte-for-byte alone", () => assert.strictEqual(fs.readFileSync(S, "utf8"), before));
t("no backup written when nothing changed", () => assert.strictEqual(backups().length, 0));

// ── Fresh install (no settings.json at all) ──────────────────────────────
clean();
t("creates settings.json from scratch", () => {
  assert.strictEqual(cli.configureHooks(HOOK, STATUS), true);
  assert.ok(/island-statusline/.test(read().statusLine.command));
});
t("no spurious backup when there was no prior file", () => assert.strictEqual(backups().length, 0));

// ── Backup pruning: repeated installs must not litter ~/.claude ──────────
t("backups are capped (repeated installs don't pile up)", () => {
  for (let i = 0; i < 8; i++) cli.writeSettings(read());
  assert.ok(backups().length <= 3, "backups grew unbounded: " + backups().length);
});

// ── cleanup ──
fs.rmSync(HOME, { recursive: true, force: true });
console.log(`\n${fail ? "\x1b[31m" : "\x1b[32m"}${pass} passed, ${fail} failed\x1b[0m\n`);
process.exit(fail ? 1 : 0);
