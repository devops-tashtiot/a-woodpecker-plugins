# master-versions — internals

Technical reference for how `master-versions` works under the hood.

---

## Contents

1. [What is git-cliff?](#1-what-is-git-cliff)
2. [Stateless mode — how this plugin uses git-cliff](#2-stateless-mode--how-this-plugin-uses-git-cliff)
3. [cliff.toml explained](#3-clifftoml-explained)
4. [How git-cliff is called internally](#4-how-git-cliff-is-called-internally)
5. [Clone settings don't matter — how shallow/partial clones are handled](#5-clone-settings-dont-matter--how-shallowpartial-clones-are-handled)
6. [Message retrieval — per-event dispatch](#6-message-retrieval--per-event-dispatch)
7. [Fail-fast error handling](#7-fail-fast-error-handling)

---

## 1. What is git-cliff?

git-cliff is a changelog generator. It reads commit messages, groups them by type, and produces structured `CHANGELOG.md` files. It also calculates the next semantic version by looking at what types of changes are present — a `feat` bumps minor, a `fix` bumps patch, a `breaking` change bumps major.

By default git-cliff reads from the git log. This plugin does **not** use that mode.

---

## 2. Stateless mode — how this plugin uses git-cliff

This plugin bypasses git history entirely. Instead of reading commits from the log, it injects the exact commit string — retrieved internally based on `CI_PIPELINE_EVENT` (see [§6](#6-message-retrieval--per-event-dispatch)) — directly into git-cliff via `--with-commit`.

The key flags that make this work:

| Flag | Purpose |
|------|---------|
| `--with-commit` | Injects a commit string directly — git history is never read for the current change |
| `--tag-pattern` | Restricts git-cliff to only tags belonging to the current component (e.g. `^nati-[0-9]+\.[0-9]+\.[0-9]+$`) — prevents cross-component tag pollution |
| `--bump --bumped-version` | Asks git-cliff to calculate the next version from the injected commit(s), using the last matching tag as the base |
| `--tag` | Sets the new version label when writing the changelog body |
| `-- HEAD..HEAD` | Passes an empty commit range — git-cliff sees no real history, only the `--with-commit` injections |

**Why stateless?**

The PR body line is the **single source of truth**. The same run always produces the same result regardless of what is or isn't in git history. There is no risk of an unrelated commit in the log accidentally triggering a version bump.

git-cliff still uses the git tag list to find the previous version for the base — but only to answer "what was the last version?" It never reads the commit log for the current change.

---

## 3. cliff.toml explained

```toml
[git]
conventional_commits = false

commit_parsers = [
  { message = "^breaking", group = "🚀 🚀 Breaking Changes" },
  { message = "^feat",     group = "✨ Features" },
  { message = "^fix",      group = "🐛 Bug Fixes" },
  { message = "^other",    group = "📦 other", skip = true },
]

[bump]
custom_major_increment_regex = "^breaking"

[changelog]
trim = false
body = """
...
"""
```

### `[git]` section

| Field | Value | What it does |
|-------|-------|-------------|
| `conventional_commits` | `false` | Disables git-cliff's built-in `type(scope): description` parser. Every commit is treated as a raw string. Bump rules and group assignment come entirely from `commit_parsers` regex matches. |

#### `commit_parsers`

An ordered list — **first match wins**, same as the plugin's own `_match_line`. Each entry defines one commit type.

| Field | Meaning |
|-------|---------|
| `message` | Regex matched against the raw commit string from position 0. The plugin uses these exact same patterns to decide which lines in the PR body are commit lines. |
| `group` | The heading this commit appears under in `CHANGELOG.md`. |
| `skip = true` | Drop the commit entirely — no changelog entry, no version bump. The commit still acts as a line boundary in the PR body. |

**Any commit whose message doesn't match any entry is silently dropped by git-cliff.**

To add a new type, add an entry. Example — add `chore` as a no-op:
```toml
{ message = "^chore", group = "🔧 Chores", skip = true }
```

### `[bump]` section

| Field | What it does |
|-------|-------------|
| `custom_major_increment_regex` | Any commit whose message matches this regex forces a **major** bump. Set to `^breaking` so any line starting with `breaking` always produces a major release, regardless of other rules. |

The standard bump logic (when `custom_major_increment_regex` does not match):
- `feat` → minor bump
- `fix` → patch bump
- `!` after `]` → major bump (handled by git-cliff's `breakage_always_bump_major`)

### `[changelog]` section

| Field | What it does |
|-------|-------------|
| `trim = false` | Preserves leading/trailing whitespace in the rendered output. |
| `body` | Tera template rendered once per release. Produces the `CHANGELOG.md` section. |

Key template variables available inside `body`:

| Variable | Value |
|----------|-------|
| `version` | The new tag string, e.g. `nati-1.6.0`. |
| `timestamp` | Unix timestamp — formatted via `date(format="%Y-%m-%d %H:%M")`. |
| `commits` | List of commit objects, grouped by `group` to produce per-section lists. |
| `commit.message` | The raw commit string injected via `--with-commit`, with newlines replaced for multi-line entries. |

The `get_env(name="CI_REPO_URL", default="")` call in the default template links the version heading to the Gitea browse URL if `CI_REPO_URL` is set in the environment.

---

## 4. How git-cliff is called internally

The plugin calls git-cliff **twice** per component.

### Call 1 — bump calculation (subject line only)

```bash
git cliff \
  --config cliff.toml \
  --tag-pattern '^nati-[0-9]+\.[0-9]+\.[0-9]+$' \
  --bump --bumped-version \
  --with-commit 'feat: add login' \
  -- HEAD..HEAD
```

Output: the next version string, e.g. `nati-1.1.0`.

**Why only the subject line?**
With `conventional_commits = false`, git-cliff applies `custom_major_increment_regex` and bump rules against the commit subject. When a commit has a body attached without a blank-line separator, git-cliff fails to isolate the subject and falls back to a patch bump regardless of what the regex matched. Passing only the first line of each commit (the subject) avoids this — the subject alone is sufficient to determine the bump level.

If the output equals the current latest tag, the component is skipped — no releasable commit.

### Call 2 — changelog generation (full multiline string)

```bash
git cliff \
  --config cliff.toml \
  --tag-pattern '^nati-[0-9]+\.[0-9]+\.[0-9]+$' \
  --tag 'nati-1.1.0' \
  --with-commit 'feat: add login
  Full description here.
  Second line of body.' \
  --prepend nati/CHANGELOG.md \
  -- HEAD..HEAD
```

The full multiline commit string is passed here — the body content is needed for the rendered changelog entry. `--prepend` is used if `CHANGELOG.md` already exists; `--output` is used for the first release.

### Per-component flow summary

```
1. git tag -l 'nati-[0-9]*'           → find latest tag (base version)
2. git cliff --bump --bumped-version   → calculate new version (subject only)
3. git cliff --tag 'nati-1.1.0' ...   → write CHANGELOG.md (full commit body)
4. append 'nati-1.1.0' to output tags file
```

---

## 5. Clone settings don't matter — how shallow/partial clones are handled

Version resolution (`git describe`, and git-cliff's own tag lookup) needs real commit ancestry.
`plugin-git`'s `partial: true` default runs `git fetch --depth=1 --filter=tree:0`, which cuts
history at a shallow boundary — on such a clone `git describe` fails with `fatal: No names found,
cannot describe anything`, because the shallow boundary makes the checked-out commit look like it
has no parents.

`release.py` handles this itself before any tag resolution happens: it checks
`git rev-parse --is-shallow-repository`, and if the workspace is shallow, folds `--unshallow`
into the same fetch that establishes the resolved branch:

```python
fetch_result = run_command(
    f"git {auth_opt}fetch {unshallow_opt}origin {resolve_branch}:refs/remotes/origin/{resolve_branch}"
)
```

Verified directly, not assumed: reproduced a real `--depth=1 --filter=tree:0` clone against a git
server with `uploadpack.allowFilter=true` (so the filter was genuinely honored — confirmed via
`remote.origin.partialclonefilter` and a near-empty initial pack, not silently ignored the way a
local `file://` remote does by default), then ran the exact fetch above. Result: `is_shallow`
flipped to `false`, every commit became reachable again, tags auto-followed, and `git describe`
resolved correctly. The `tree:0` filter itself turned out to be irrelevant to the outcome — `git
describe` only needs commit and tag objects, never tree/blob content.

This is why the clone step's `partial`/`depth`/`tags` settings are non-load-bearing: whatever
state the clone leaves the workspace in, `release.py` repairs it before computing any version.

**`PLUGIN_BITBUCKET_TOKEN` is also used for this fetch, not just the PR-description lookup.**
The plugin's own step image has no Bitbucket credentials of its own, so the token is sent as an
`Authorization: Bearer <token>` header via `git -c http.extraHeader=…` (the only scheme Bitbucket
DC HTTP tokens accept). Without it the fetch 401s — and since this branch fetch runs whenever
`resolve_branch` is set (`CI_COMMIT_BRANCH`/`CI_COMMIT_TARGET_BRANCH`, present on essentially
every real Woodpecker run, `manual` and `push` included, not just `pull_request`), the fetch
failure hits `release.py`'s fail-fast path (§7) and exits the run with code 1 rather than
silently mis-detecting components as first releases — that was the pre-fail-fast behavior. Set
`PLUGIN_BITBUCKET_TOKEN` on every event.

**Works with the clone's `tags: true` OR `tags: false`.** Version resolution is always scoped to
the correct branch, regardless of how many tags the clone brought into the workspace:

- git-cliff's bump is invoked with `--use-branch-tags`, so it only considers tags reachable from
  the checked-out `HEAD`. With `tags: false` only ancestry tags are present anyway (no-op); with
  `tags: true` (every tag from every branch present) it still resolves correctly — a `fix` on a
  hotfix cut from `v1.0.0` bumps to `v1.0.1`, never `v2.0.1` from an unrelated mainline `v2.0.0`.
  **No tags are ever deleted.**
- Because `--use-branch-tags` looks at the checked-out branch, a `pull_request` run must resolve
  against its **target** branch, not the PR's own branch. So for `pull_request` events the plugin
  temporarily `git checkout`s the target branch (`CI_COMMIT_TARGET_BRANCH`), calculates every
  version there, then checks back to the PR branch before writing any `CHANGELOG.md` (so the
  changelog files persist for the push step). Non-PR runs calculate directly on the current
  branch.

---

## 6. Message retrieval — per-event dispatch

The plugin retrieves the message to parse itself — there's no file-path input for it. It
dispatches on `CI_PIPELINE_EVENT` (a Woodpecker-provided variable, not user-set); see the
README's §6 "Triggering events" for the full walkthrough of each case. The exact dispatch:

| `CI_PIPELINE_EVENT` | Source | Required variables |
|---|---|---|
| `pull_request` | Fetched from the Bitbucket Server REST API (`GET .../pull-requests/{id}`), using the PR's `description` field. | `PLUGIN_BITBUCKET_TOKEN`, `CI_FORGE_URL`, `CI_REPO_OWNER`, `CI_REPO_NAME`, `CI_COMMIT_PULL_REQUEST` |
| `manual` (default) | The `PLUGIN_MESSAGE` env var, used as-is. On a manual run the plugin loudly echoes the full message back — a banner and every line numbered between `BEGIN PLUGIN_MESSAGE` / `END PLUGIN_MESSAGE` markers (tabs shown as `\t`) — so you can see exactly what was submitted. This is the fastest way to spot a mistyped message (e.g. a leading space or a pasted image reference) that would otherwise make every line silently `IGNORED`. | `PLUGIN_MESSAGE` |
| any other event (e.g. `push`) | `git log -1 --pretty=%B`. If the commit message contains a `DESCRIPTION` section (the custom merge-commit template — see README §7A), only the text after that marker is used; otherwise the full commit message is used. | *(none — reads local git history)* |

The plugin exits with code 1 if the message can't be determined (e.g. a missing required
variable, or an empty `PLUGIN_MESSAGE` on a manual run). Whatever message is retrieved is also
written to `pr_body.txt` in the working directory, so later pipeline steps that grep it for
override values (e.g. `PLUGIN_BASE_PATH=`) keep working.

---

## 7. Fail-fast error handling

Any git command that could affect a computed version fails the run instead of degrading silently.
Earlier versions of the plugin logged a `WARNING` and fell back to a possibly-wrong ref (e.g.
`HEAD` instead of the resolved branch, or the PR's own branch instead of its target) when a
fetch/checkout failed — which could silently compute a version from the wrong base. It now exits
with code 1 in every case where that would happen:

| Failure | Old behavior | New behavior |
|---|---|---|
| `git rev-parse --is-shallow-repository` fails | assumed "not shallow" | exit 1 |
| Branch fetch (`git fetch origin <branch>:refs/remotes/origin/<branch>`) fails | fell back to resolving against `HEAD` | exit 1 |
| Unshallow fetch fails (bare local run on a shallow clone) | previously an unrelated `NameError` crash — now a proper diagnosed failure | exit 1 |
| PR target-branch checkout fails | fell back to computing versions against the PR's own branch | exit 1 |
| Restoring the original checkout after PR version calculation fails | unchecked — Phase B could write `CHANGELOG.md` files against the wrong tree | exit 1 |
| `git-cliff --bump` itself exits non-zero | silently treated the same as "no releasable commits" (SKIP) | exit 1 |
| One component's `CHANGELOG.md` write fails in Phase B | logged an error but the run still exited 0 with the other components released | run still attempts every component, but the process now exits 1 if any failed |

`git config --unset-all remote.origin.tagOpt` is the one exception left unchecked on purpose: it
legitimately returns non-zero when the key was never set (e.g. the clone used `tags: true`),
which isn't a failure.
