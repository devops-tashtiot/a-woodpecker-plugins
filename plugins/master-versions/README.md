# master-versions

Woodpecker CI plugin that parses a message file containing conventional commit lines,
calculates semantic versions via git-cliff, writes `CHANGELOG.md` files per component,
and records created tags to an output file for downstream steps.

---

## What is git-cliff?

git-cliff is a changelog generator that reads commit messages and produces structured
`CHANGELOG.md` files, calculating the next semantic version from the types of changes present.

### How this plugin uses git-cliff (stateless mode)

This plugin does **not** feed git-cliff the full git log. Instead:

- `--with-commit` injects the exact commit string from `PLUGIN_MESSAGE_FILE` directly — git history is bypassed entirely
- `--tag-pattern` restricts git-cliff to only tags belonging to the current component (e.g. `^nati-[0-9]+\.[0-9]+\.[0-9]+$`)
- `--bump --bumped-version` asks git-cliff to calculate the next version from the injected commit(s), using the last matching tag as the base
- `--tag` sets the new version label when generating the changelog body

The file passed to `PLUGIN_MESSAGE_FILE` (usually the PR description, but can be anything)
is the **single source of truth** — the same run always produces the same result regardless
of what is or isn't in git history.

---

## How to Use — The Most Important Part

This is the full end-to-end flow. Everything else in this document is detail.

### Step 1 — Write your PR description

Your PR body is the **source of truth**. Write commit lines using this format:

```
type[location]: description
```

> **The `[` bracket immediately after the type is what makes a line a commit line.**
> Without it, the line is ignored — even if it starts with `feat` or `fix`.
> The type alone means nothing. The type + `[` is the trigger.

> **The available types are defined entirely in `cliff.toml` `commit_parsers`.**
> This is the most important configuration in the whole system. If a type is not listed
> there, no release is produced — the line is silently ignored regardless of what you write.
> Default types: `feat` (minor), `fix` (patch), `breaking` (major), `other` (skip/no-op).

**Real PR body example:**

```
## What changed

feat[nati]: add OAuth2 login support
fix[plugins/docker]: resolve socket timeout on large uploads
breaking[base/argo]: rename all env vars to SNAKE_CASE

This PR also updates the docs — no release needed for that.
```

This produces:
- `nati` → minor bump → `nati-1.1.0`, `nati/CHANGELOG.md` updated
- `plugins/docker` → patch bump → `plugins-docker-1.0.1`, `plugins/docker/CHANGELOG.md` updated
- `base/argo` → major bump → `base-argo-2.0.0`, `base/argo/CHANGELOG.md` updated

### Step 2 — CI picks it up automatically

In your Woodpecker pipeline, the PR description is written to a file and passed to the plugin:

```yaml
- name: Fetch PR body
  commands:
    - curl -s <gitea-api>/pulls/$CI_COMMIT_PULL_REQUEST | jq -r '.body' > pr_body.txt

- name: Run release
  image: netanelzucaim123/master-versions:latest
  settings:
    message_file: pr_body.txt       # PLUGIN_MESSAGE_FILE — the file to read
    base_path: .                    # PLUGIN_BASE_PATH — root of your repo (critical — see below)
    changelog_level: 1              # PLUGIN_CHANGELOG_LEVEL — expected location depth
    output_tags_file: new_tags.txt  # PLUGIN_OUTPUT_TAGS_FILE — tags for downstream
```

### Step 3 — Tags and changelogs are created

For every matched component the plugin:
1. Finds the latest existing tag for that component (e.g. `nati-1.0.3`)
2. Calculates the next version (patch / minor / major) using git-cliff
3. Writes or prepends the `CHANGELOG.md` entry
4. Creates the git tag locally (`git tag -f nati-1.1.0`)
5. Records the new tag to `new_tags.txt` for kaniko-master-versions

The tag points to the commit at the time `release.py` runs — before the CI step commits
the `CHANGELOG.md` changes. The tag marks the code release; the changelog update follows
as a separate docs-only commit.

---

## PLUGIN_MESSAGE_FILE — the input file

`PLUGIN_MESSAGE_FILE` is a **path to a file** containing the text to parse.

It can point to **any file** — the plugin reads its contents and scans every line for commit
patterns. The file can contain any mix of prose, markdown, checklists, and commit lines —
only lines matching the commit pattern trigger a release.

**Most common use: PR description**

```bash
# In CI: write the PR body to a file, then point the plugin at it
curl -s <api>/pulls/$CI_COMMIT_PULL_REQUEST | jq -r '.body' > pr_body.txt
PLUGIN_MESSAGE_FILE=pr_body.txt python3 release.py
```

**Other valid uses:**

```bash
# Manual trigger — write your own file
echo "feat[nati]: hotfix login" > release.txt
PLUGIN_MESSAGE_FILE=release.txt python3 release.py

# Cron job — generate a file from any source
PLUGIN_MESSAGE_FILE=/tmp/scheduled_release.txt python3 release.py

# Pipeline variable written to a file
echo "$RELEASE_NOTES" > notes.txt
PLUGIN_MESSAGE_FILE=notes.txt python3 release.py
```

---

## PLUGIN_BASE_PATH — the most critical variable

> **Getting `PLUGIN_BASE_PATH` wrong breaks everything silently.**
> The plugin will look for components in the wrong place, create tags with wrong slugs,
> and write `CHANGELOG.md` files in the wrong directories — with no errors, just wrong output.

`PLUGIN_BASE_PATH` is the **root directory** that every `[location]` is resolved against.
When you write `feat[nati]: msg`, the plugin looks for the component at `PLUGIN_BASE_PATH/nati/`.

```
repo/
  nati/          ← PLUGIN_BASE_PATH="."         → write [nati]
  plugins/
    docker/      ← PLUGIN_BASE_PATH="."         → write [plugins/docker]
                    PLUGIN_BASE_PATH="./plugins" → write [docker]
```

**When in doubt, set it to `"."` (repo root) and write full relative paths in `[location]`.**

Setting `PLUGIN_BASE_PATH="./plugins"` lets you write shorter locations (`[docker]` instead
of `[plugins/docker]`) but your tags become `docker-1.0.0` instead of `plugins-docker-1.0.0`.
Choose based on what tag names you want — and be consistent.

The value and meaning are printed at every run:
```
>>> PLUGIN_BASE_PATH='.' — root directory; all [location] paths are resolved relative to this
```

---

## Message format

```
type[location]!: description
```

| Part | Required | Description |
|------|----------|-------------|
| `type` | Yes | Must be a type defined in `cliff.toml` `commit_parsers` — lowercase, no leading spaces |
| `[` | **Critical** | **Must immediately follow the type with no gap.** This bracket is what identifies a commit line. `feat: msg` (no bracket) is not a commit line and is ignored. |
| `location` | Yes (content optional) | Component path relative to `PLUGIN_BASE_PATH`. Empty `[]` means repo root. |
| `]` | Yes | Closes the bracket |
| `!` | No | Forces a major bump regardless of type |
| `:` | Yes | Immediately after `]` or `!` — no spaces |
| `description` | Yes | What changed — goes into the changelog as-is |

> **No scope.** With `conventional_commits = false` in `cliff.toml`, git-cliff treats the
> whole string as a raw message — `type(scope): description` is not parsed. Do not write
> `feat(scope)[nati]: msg`. Write `feat[nati]: msg`.

> **Lowercase, no indent.** `Feat[nati]: ...`, `FIX[nati]: ...`, or `  feat[nati]: ...`
> (leading spaces) are all silently ignored — they do not match `^feat` etc.

> **`[location]` must not contain `[` or `]`.** A nested bracket like `feat[na[ti]: msg`
> will never match as a commit line.

> **After `]`, only `!?:` is valid.** `feat[nati]!!: msg` (double bang) does **not** match
> and becomes continuation text of the previous commit instead.

---

## Continuation lines — how multi-line entries work

After a commit line is recognised, **every following line is collected as continuation text**
until the next commit line is encountered.

**A line starts a new commit when:**
1. It matches a `commit_parsers` pattern at position 0, **AND**
2. That match is immediately followed by `[`

Both conditions must be true simultaneously. If either is false, the line is continuation.

**A line is continuation when** it does not match any commit_parser pattern, or it matches
one but is not followed by `[` (e.g. plain prose that happens to start with the word "fix").

```
feat[nati]: add login
  This whole paragraph is continuation text.
  It becomes part of the changelog entry for nati.

  Blank lines are included too.

fix[check]: resolve race condition   ← NEW COMMIT — ends nati's continuation
  Short description here.            ← continuation of fix[check]
feat[nati]: another feature          ← NEW COMMIT — ends fix[check]'s continuation
```

**A level-failing line also acts as a commit boundary.**
Even if a line is skipped due to wrong `PLUGIN_CHANGELOG_LEVEL`, it still ends the
continuation of the line before it:

```
PLUGIN_CHANGELOG_LEVEL=1

feat[nati]:
  body line 1
  body line 2
fix[plugins/docker]: wrong level  ← SKIPPED (too deep), but still ends nati's continuation
feat[check]: new commit           ← starts fresh
```

**`other` as a continuation stopper.**
`other[loc]: ...` is a skip type — git-cliff produces no release entry. But it still
acts as a commit boundary, making it useful to stop a continuation block cleanly:

```
feat[nati]: big feature
  Details here — these are continuation lines.

other[nati]: stop the block above   ← ends continuation cleanly, no release entry
## Checklist                         ← continuation of "other" — also skipped
- [x] Tests pass
```

---

## Location `[]` — where to release

> **The `[location]` bracket is the routing mechanism.** It controls three things at once:
> where `CHANGELOG.md` is written, what tag prefix is used, and what git history is isolated to.
> It is stripped before being passed to git-cliff — git-cliff never sees it.

| What you write | Meaning |
|----------------|---------|
| `[nati]` | Component at `PLUGIN_BASE_PATH/nati/` → tag `nati-1.0.0` |
| `[plugins/docker]` | Component at `PLUGIN_BASE_PATH/plugins/docker/` → tag `plugins-docker-1.0.0` |
| `[]` | Repo root (`PLUGIN_BASE_PATH` itself) → tag `1.0.0` |
| `[nati, check]` | Releases **both** `nati` and `check` from one line |
| `[*]` | Wildcard — expands to **all direct subdirs** of `PLUGIN_BASE_PATH` |
| `[plugins/*]` | Wildcard — expands to **all subdirs** of `PLUGIN_BASE_PATH/plugins/` |

Slashes in the path become hyphens in the tag:

| Location | Tag prefix | Example tag |
|----------|------------|-------------|
| `nati` | `nati-` | `nati-1.1.0` |
| `plugins/docker` | `plugins-docker-` | `plugins-docker-1.0.1` |
| `base/argo` | `base-argo-` | `base-argo-2.0.0` |
| *(empty)* | *(none)* | `1.0.0` |

---

## Type reference

> **Types are defined entirely in `cliff.toml` `commit_parsers`.** This is the single most
> important config in the system. A type not listed there produces no release — the line is
> silently skipped. To add a new type, add an entry to `commit_parsers`. See the
> `cliff.toml explained` section below.

| Type | Bump | When to use |
|------|------|-------------|
| `feat` | Minor | New feature, new capability |
| `fix` | Patch | Bug fix, crash fix, incorrect behaviour |
| `breaking` | Major | Removes or changes something backwards-incompatibly |
| `other` | None | Explicit no-op — creates no release, useful as a continuation stopper |
| Any `!` after `]` | Major | Forces major regardless of type — e.g. `fix[nati]!: ...` |

---

## PLUGIN_CHANGELOG_LEVEL enforcement

Every `[location]` must match the declared path depth. If any location in a multi-location
line fails, **the entire line is skipped**.

```
PLUGIN_CHANGELOG_LEVEL=1   (expects 0 slashes — top-level dirs like [nati])

feat[nati]: add dashboard          → ACCEPT
fix[plugins/docker]: fix socket    → SKIP (1 slash, expected 0)
feat[nati, plugins/docker]: shared → SKIP (plugins/docker fails — whole line skipped)
feat[nati, harel]: auth update     → ACCEPT (both have 0 slashes)
```

| Level | Accepts | Example |
|-------|---------|---------|
| `0` | root only | `feat[]: msg` |
| `1` | top-level dirs | `feat[nati]: msg` |
| `2` | one level nested | `feat[plugins/docker]: msg` |
| `N` | N−1 slashes | `feat[a/b/.../z]: msg` |

---

## cliff.toml explained

> **`cliff.toml` is the most important configuration file in this system.**
> It defines which commit types are recognised, what version bump each produces, and how the
> changelog is rendered. If a type is not in `commit_parsers`, it does not exist to the plugin.

The `cliff.toml` controls all of git-cliff's behaviour.

### `[bump]` — version increment rules

```toml
[bump]
custom_major_increment_regex = "^breaking"
```

| Parameter | What it does |
|-----------|-------------|
| `custom_major_increment_regex` | Any commit whose message matches this regex forces a **major** bump. Set to `^breaking` so any line starting with `breaking` always produces a major release, regardless of other rules. |

### `[git]` — commit parsing

```toml
[git]
conventional_commits = false

commit_parsers = [
  { message = "^breaking", group = "🚀 🚀 Breaking Changes" },
  { message = "^feat",     group = "✨ Features" },
  { message = "^fix",      group = "🐛 Bug Fixes" },
  { message = "^other",    group = "📦 other", skip = true },
]
```

| Parameter | What it does |
|-----------|-------------|
| `conventional_commits = false` | git-cliff treats each commit as a raw string — no `type(scope): description` parsing. Bump rules and group assignment come entirely from `commit_parsers` patterns. |
| `commit_parsers` | **The type registry.** Ordered list — first match wins. Each entry's `message` regex is matched against the start of the raw commit string. This list defines every type the plugin recognises. Anything not listed here is silently dropped. |

#### commit_parsers fields

| Field | Meaning |
|-------|---------|
| `message` | Regex matched against the raw commit message from position 0. |
| `group` | Changelog section heading this commit appears under. |
| `skip = true` | Drop the commit entirely — no changelog entry, no version bump. |

**Any commit whose message doesn't match any entry is also silently skipped.**

To add a new type, add a new entry. Example — add `chore` as a no-op:
```toml
{ message = "^chore", group = "🔧 Chores", skip = true }
```

### `[changelog]` — output template

```toml
[changelog]
trim = false
body = """
{% if version %}
    ## [{{ version }}] - {{ timestamp | date(format="%Y-%m-%d %H:%M") }}
...
"""
```

| Parameter | What it does |
|-----------|-------------|
| `trim = false` | Preserves leading/trailing whitespace in the rendered output. |
| `body` | Tera template rendered once per release. Produces the `CHANGELOG.md` section. |

Key template variables:

| Variable | Value |
|----------|-------|
| `version` | The new tag string (e.g. `nati-1.6.0`). |
| `timestamp` | Unix timestamp formatted via `date(format=...)`. |
| `commits` | List of commit objects. Grouped by `group` to produce per-section lists. |

---

## How git-cliff is called (internals)

The plugin calls git-cliff **twice** per component:

**1. Bump call** — subject line only, to calculate the next version:
```
git cliff --tag-pattern '^nati-[0-9]+\.[0-9]+\.[0-9]+$' \
          --bump --bumped-version \
          --with-commit 'feat: add login' \
          -- HEAD..HEAD
```
Only the first line of each commit is passed. This is required because with
`conventional_commits = false`, git-cliff applies `custom_major_increment_regex` against
the commit subject. A multiline string without a blank separator causes git-cliff to fail
isolating the subject and fall back to a patch bump regardless of the regex.

**2. Changelog call** — full multiline string, to write the entry:
```
git cliff --tag-pattern '^nati-[0-9]+\.[0-9]+\.[0-9]+$' \
          --tag 'nati-1.1.0' \
          --with-commit 'feat: add login\n  Full description here' \
          --prepend nati/CHANGELOG.md \
          -- HEAD..HEAD
```

---

## Variables

### Required

| Variable | Description |
|----------|-------------|
| `PLUGIN_MESSAGE_FILE` | **Path to a file** containing the message to parse. Can be any file — a PR body saved to disk, a manually written release note, a cron-generated file, etc. Usually populated from the PR description in CI. |
| `PLUGIN_BASE_PATH` | **Critical — getting this wrong silently breaks tag names, CHANGELOG paths, and directory resolution.** The root directory all `[location]` paths are resolved against. When in doubt, use `"."` and write full relative paths in `[]`. Printed at startup so you can verify it. |
| `PLUGIN_CHANGELOG_LEVEL` | Enforces the expected path depth of every `[location]`. Lines whose locations do not match are skipped. Level 0 = root (`[]`). Level 1 = top-level dirs (`[nati]`). Level 2 = one level nested (`[plugins/docker]`). If not set the plugin prints an error and exits. |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_OUTPUT_TAGS_FILE` | `""` | File to append created tags to — one tag per line. Tags are already created locally by the plugin; this file is read by `kaniko-master-versions` to know which images to build. |
| `PLUGIN_SCOPE_EXCLUDE_REGEX` | `""` | Python regex applied to every location before processing — both explicit and wildcard-expanded. Any matching location is silently skipped. Primary guard against releasing non-service folders when using `[*]`. Example: `^docs$\|^scripts$`. |
| `PLUGIN_VERBOSE` | `0` | `0` = minimal, `1` = info, `2` = trace (full git-cliff commands and output). |
| `PLUGIN_INITIAL_TAG` | `1.0.0` | Version for the first release of a component with no existing tag. |
| `PLUGIN_V_PREFIX` | `""` | Set to `"true"` to prefix version with `v`. `true` → `nati-v1.0.0`, unset → `nati-1.0.0`. |
| `PLUGIN_CLIFF_TOML` | *(bundled)* | Path to a custom `cliff.toml`. Resolution order: (1) this variable, (2) `./cliff.toml` in working dir, (3) bundled image copy. |

---

## Examples

### Release a single component

```
feat[nati]: add sidebar with user stats
```
→ `nati/CHANGELOG.md` updated, tag `nati-1.1.0`

---

### Release a component two levels deep

```
fix[plugins/docker]: increase read deadline to 30s
```
→ `plugins/docker/CHANGELOG.md` updated, tag `plugins-docker-1.0.1`

---

### Release the repo root (no component prefix)

```
feat[]: add woodpecker pipeline definition
```
→ `CHANGELOG.md` at root updated, tag `1.0.0`

---

### Release multiple components from one line

```
feat[nati, check, base/argo]: centralise JWT validation
```
→ Three independent releases: `nati-1.1.0`, `check-1.1.0`, `base-argo-1.1.0`

---

### Breaking change — always major

```
breaking[nati]: remove /v1 endpoints
feat[nati]!: replace REST with gRPC interface
```
Both produce a major bump. The second uses `!` on a `feat` — same result.

---

### Multi-line changelog entry

```
feat[nati]:
  Replace basic auth with OAuth2.
  Supports Google, GitHub, and GitLab providers.
  Adds token refresh logic and session expiry handling.

fix[check]: unrelated fix — this line ends the continuation above
```

The full multi-line text becomes the `nati` changelog entry.

---

### Stopping a continuation block cleanly

```
feat[nati]: big feature
  These lines are continuation text.

other[nati]: stop                ← ends continuation, no release entry for this line
## PR Checklist                  ← continuation of "other" — also skipped
- [x] Tests pass
- [x] Docs updated

fix[check]: separate fix         ← new commit, clean start
```

---

### Wildcard — release all plugins at once

```
feat[plugins/*]: bump all third-party libs to latest
```
→ Expands to every subdirectory inside `plugins/` and releases each one independently.

---

### Wildcard expansion output

When a wildcard is used, two blocks are printed:

```
>>> COMMITS TO PROCESS:
    [plugins/*]
      feat: bump all third-party libs to latest
>>> SKIP: location 'plugins/master-versions' excluded by SCOPE_EXCLUDE_REGEX
>>> COMMITS AFTER WILDCARD EXPANSION:
    Wildcards replaced with concrete component paths.
    [plugins/docker]
      feat: bump all third-party libs to latest
    [plugins/kaniko]
      feat: bump all third-party libs to latest
```

---

### Mixed message — multiple components, multiple types

```
feat[nati]: add avatar upload
fix[plugins/docker]: lock shared map access
breaking[base/argo]!: rename all env vars to SNAKE_CASE
other[]: explicit no-op at root

This is a checklist:
- [x] Tests pass
```

Result:
- `nati` → minor bump
- `plugins/docker` → patch bump
- `base/argo` → major bump (breaking + !)
- root → skipped (`other` is skip type)
- Checklist lines → continuation of `other[]` → also skipped
