# master-versions

Woodpecker CI plugin that parses a message containing conventional commits,
calculates semantic versions via git-cliff, writes `CHANGELOG.md` files per
component, and records created tags to an output file for downstream steps.

---

## What is git-cliff?

git-cliff is a changelog generator that reads **conventional commits** and produces structured `CHANGELOG.md` files. It also calculates the next semantic version based on the types of changes present (patch / minor / major).

It works by:
1. Scanning git history (or receiving commits directly via `--with-commit`)
2. Matching each commit message against configured patterns (`commit_parsers`)
3. Grouping matched commits into changelog sections (e.g. Features, Bug Fixes)
4. Applying a Tera template to render the final output

### How this repo uses git-cliff

This plugin does **not** feed git-cliff a git log. Instead it uses git-cliff in **stateless mode**:

- `--with-commit` injects the exact commit string from `PLUGIN_MESSAGE` directly — git history is bypassed entirely
- `--tag-pattern` restricts git-cliff to only look at tags belonging to the current component (e.g. `^nati-[0-9]+\.[0-9]+\.[0-9]+$`)
- `--bump --bumped-version` asks git-cliff to calculate the next version from the injected commit(s), using the last matching tag as the base
- `--tag` sets the new version label when generating the changelog body

This means the PR body is the **single source of truth** — the same run produces the same result regardless of what is or isn't in git history.

---

## cliff.toml explained

The `cliff.toml` file controls all of git-cliff's behaviour.

### `[bump]` — version increment rules

```toml
[bump]
features_always_bump_minor = true
breakage_always_bump_major = true
custom_major_increment_regex = "^breaking"
```

| Parameter | What it does |
|-----------|-------------|
| `features_always_bump_minor` | Any commit in the `Features` group always bumps **minor**, even if git-cliff's default logic would only produce a patch. |
| `breakage_always_bump_major` | Any commit in the `Breaking Changes` group always bumps **major**. |
| `custom_major_increment_regex` | Extra regex applied to the raw commit message. Any commit matching `^breaking` forces a **major** bump — catches `breaking(...)` and `breaking:` before the parser table is consulted. |

---

### `[git]` — commit parsing and tag isolation

```toml
[git]
conventional_commits = true
filter_unconventional = true
tag_pattern = "[a-zA-Z0-9-]+-v[0-9]+\.[0-9]+\.[0-9]+$"
commit_parsers = [ ... ]
```

| Parameter | What it does |
|-----------|-------------|
| `conventional_commits` | Enables conventional commit parsing (`type(scope): description`). Without this, commit grouping and bump calculation do not work. |
| `filter_unconventional` | Commits that do not match any `commit_parsers` entry are silently dropped — no changelog entry, no version bump. |
| `tag_pattern` | Default pattern git-cliff uses to discover existing version tags. Overridden at runtime by `release.py` with a component-specific pattern (e.g. `^nati-[0-9]+\.[0-9]+\.[0-9]+$`) so each component only sees its own tags. |

#### `commit_parsers` — type recognition table

```toml
commit_parsers = [
  { message = "^breaking\\((.*?)\\)", group = "Breaking Changes", bump_type = "major" },
  { message = "^breaking",            group = "Breaking Changes", bump_type = "major" },
  { message = "^feat\\((.*?)\\)",     group = "Features" },
  { message = "^feat",                group = "Features" },
  { message = "^fix\\((.*?)\\)",      group = "Bug Fixes" },
  { message = "^fix",                 group = "Bug Fixes" },
  { message = "^other\\((.*?)\\)",    skip = true },
  { message = "^other",               skip = true },
]
```

**Order matters — first match wins.** Each entry has:

| Field | Meaning |
|-------|---------|
| `message` | Regex matched against the start of the raw commit message. Scoped variants (with `(.*?)`) come before bare variants so `feat(scope): ...` does not accidentally match just `^feat`. |
| `group` | The changelog section heading this commit type appears under. |
| `bump_type` | Explicitly sets the bump level (`"major"`, `"minor"`, `"patch"`). If omitted, the level is inferred from the group name combined with the `[bump]` rules above. |
| `skip = true` | Commit is dropped entirely — no changelog entry, no version bump. Used for `other`, a deliberate no-op marker. |

Any commit type not listed here is also dropped. To add a new type (e.g. `chore`), add a new entry to this table.

---

### `[changelog]` — output template

| Parameter | What it does |
|-----------|-------------|
| `header` | Written once at the top of a newly created `CHANGELOG.md`. Skipped in prepend mode since the header already exists. |
| `body` | Tera template rendered once per release. Has access to `version`, `timestamp`, `commits`, and environment variables via `get_env(name="VAR", default="")`. |

Key template variables used in `body`:

| Variable | Value |
|----------|-------|
| `version` | The new tag string (e.g. `nati-1.6.0`). `trim_start_matches(pat="v")` strips a leading `v` so the display reads `1.6.0`. |
| `timestamp` | Unix timestamp of the release moment, formatted via `date(format=...)`. |
| `commits` | List of commit objects with `.group`, `.scope`, `.message`. Grouped with `group_by(attribute="group")` to produce per-section lists. |
| `get_env(name="CI_REPO_LINK", default="")` | Reads `CI_REPO_LINK` at render time to build the release URL. Falls back to empty string if not set. |

---

## Message format

```
type(scope)[location]!: description
```

A line is recognised as a commit when it matches a pattern from `cliff.toml` `commit_parsers` **immediately followed by `[`**. The `[location]` part is the only addition on top of a standard conventional commit — everything else is identical to how you would write a commit message for git-cliff directly.

> **`(scope)` is optional.** `feat[nati]: msg` and `feat(scope)[nati]: msg` are both valid.

> **`[location]` content must not contain `[` or `]`.** A line like `feat[na[ti]: msg` will never match as a commit line — the nested `[` fails the bracket content check. If such a line appears after any commit line, it is collected as continuation text instead.

> **No line stripping.** Lines are never stripped. A line with leading whitespace (e.g. `  feat[nati]: ...`) does not match `^feat` and is silently ignored. Continuation lines are stored exactly as written.

**What `[location]` does:**
- Routes the release to the correct component (decides where `CHANGELOG.md` is written and what tag is created)
- Marks the line as a new commit entry in `PLUGIN_MESSAGE` — because `cliff.toml pattern + []` is not a combination that appears in normal description text, it unambiguously identifies a commit line

**What git-cliff receives:**
The `[location]` is stripped before passing the commit to git-cliff. git-cliff sees a perfectly normal conventional commit:

```
feat(auth)[nati]!: add login   →  git-cliff receives: feat(auth)!: add login
feat[nati]: add login          →  git-cliff receives: feat: add login
```

> **Important:** The type must be **lowercase** and must start at the **very beginning of the line** — no leading spaces or indentation. A line like `  feat[nati]: ...` (with spaces before) is silently ignored.

---

## The four parts explained

### `type` — what kind of change is this?

Drives the version bump level. Defined in `cliff.toml`.

| Type | Bump | When to use |
|------|------|-------------|
| `feat` | Minor | New feature, new capability |
| `fix` | Patch | Bug fix, crash fix, incorrect behavior |
| `breaking` | Major | Removes or changes something in a backwards-incompatible way |
| `other` | — | Explicit no-op marker (git-cliff skips it; stops the previous commit's continuation) |

> **Rules:**
> - Must be **all lowercase** — `Feat`, `FIX`, `Breaking` are not recognised.
> - Must appear at the **start of the line** with **no leading spaces** — indented lines are silently ignored.

Any type not listed in `cliff.toml` is forwarded to git-cliff and silently
filtered out — no release is produced. A warning is printed so you know why.

---

### `(scope)` — what specifically changed?

Free text. Describes **the thing that changed** — a feature name, a module,
a concept. It goes directly into the changelog entry as context.

It is **not** a path. It does not affect where files are written or what tag
is created. That is the job of `[]`.

```
feat(OAuth2 login)[nati]: add Google and GitHub providers
     ^^^^^^^^^^^^
     what changed — goes into the changelog

feat(user profile API)[nati, check]: add avatar upload endpoint
     ^^^^^^^^^^^^^^^^
     still just a description — both nati and check get this in their changelog
```

Think of it as the subject line of a commit message.

---

### `[location]` — where should the release happen?

The filesystem path of the component you want to release. This is **routing information only** — it is stripped before the commit is passed to git-cliff, so git-cliff never sees it.

Controls **three things** simultaneously:
- Where `CHANGELOG.md` is written
- What tag prefix is used
- What git history is isolated to (via `--include-path`)

| What you write | What it means |
|----------------|---------------|
| `[nati]` | component at `PLUGIN_BASE/nati/` → tag `nati-1.0.0` |
| `[plugins/docker]` | component at `PLUGIN_BASE/plugins/docker/` → tag `plugins-docker-1.0.0` |
| `[]` | repo root (`PLUGIN_BASE` itself) → tag `1.0.0` |
| `[nati, check]` | releases **both** `nati` and `check` from one line |
| `[plugins/*]` | wildcard — expands to **all subdirectories** of `plugins/` |
| `[*]` | wildcard — expands to **all direct subdirectories** of `PLUGIN_BASE` |

Slashes in the path become hyphens in the tag: `plugins/docker` → `plugins-docker-1.0.0`.

---

### `!` — breaking change override

Placed **after** `[]`, before `:`. Forces a **major bump** regardless of the
commit type. Even a `fix` or `chore` with `!` produces a major release.

```
fix(session tokens)[auth]!: drop insecure cookie format
```

---

## Examples

### Release a single component

```
feat(dashboard)[nati]: add sidebar with user stats
```
→ `nati/CHANGELOG.md` updated, tag `nati-1.1.0`

---

### Release a component two levels deep

```
fix(socket timeout)[plugins/docker]: increase read deadline to 30s
```
→ `plugins/docker/CHANGELOG.md` updated, tag `plugins-docker-1.0.1`

---

### Release the repo root (no component prefix)

```
feat(CI config)[]: add woodpecker pipeline definition
```
→ `CHANGELOG.md` at root updated, tag `1.0.0`

---

### Release multiple components from one line

```
feat(shared auth middleware)[nati, check, base/argo]: centralise JWT validation
```
→ Three independent releases: `nati-1.1.0`, `check-1.1.0`, `base-argo-1.1.0`
Each gets its own `CHANGELOG.md` entry with the same description.

---

### Breaking change — always major

```
breaking(REST API)[nati]: remove /v1 endpoints
feat(gRPC)[nati]!: replace REST with gRPC interface
```
Both produce a major bump. The second uses `!` on a `feat` — same result.

---

### Wildcard — release all plugins at once

```
feat(dependency upgrades)[plugins/*]: bump all third-party libs to latest
```
→ Expands to every subdirectory inside `plugins/` and releases each one.

---

### Wildcard — release everything under PLUGIN_BASE

```
feat(Go 1.22 migration)[*]: update all components to Go 1.22
```
→ Expands to every direct subdirectory of `PLUGIN_BASE`.

---

### Multi-line description

All lines that follow a commit line are collected as continuation text until
the next known commit type header is encountered. This applies whether the
description is empty or not — any non-commit line is absorbed.

```
feat(auth flow)[nati]:
  Replace basic auth with OAuth2.
  Supports Google, GitHub, and GitLab providers.
  Adds token refresh logic and session expiry handling.

fix(null pointer)[check]: unrelated fix — this stops the block above
```

The full multi-line text becomes the changelog entry for `nati`.

Prose lines, blank lines, or markdown mixed in between commits are also
absorbed as continuation of the preceding commit:

```
other(scope)[nati]: no-op marker
## Checklist
- [x] Tests pass

fix(bug)[check]: stops continuation above
```

Here the checklist lines become part of the `other` commit string passed to
git-cliff (which will skip it anyway since `other` is `skip = true`).

---

### Mixed message — multiple components, multiple types

```
feat(user profiles)[nati]: add avatar upload
fix(race condition)[plugins/docker]: lock shared map access
breaking(config schema)[base/argo]!: rename all env vars to SNAKE_CASE
other(scope)[]: this line is a no-op (stops the previous commit's continuation)
```

Result:
- `nati` → minor bump
- `plugins/docker` → patch bump
- `base/argo` → major bump (breaking + !)
- root → skipped (`other` is a no-op type)

---

### Skipped type — no release produced

```
chore(scope)[nati]: update dependencies
```

`chore` is not in `cliff.toml` by default. The line is never matched as a commit line (no parser pattern matches it), so it is silently ignored — no release is produced for `nati`.

To make `chore` releasable, add it to `cliff.toml`:
```toml
{ message = "^chore", group = "Chores" }
```

---

## Variables

### Required

| Variable | Description |
|----------|-------------|
| `PLUGIN_MESSAGE` | Text containing conventional commit lines. Can be a PR body, manual trigger input, pipeline variable, cron message, etc. |
| `PLUGIN_BASE` | **The single most important variable.** The root directory all component locations are resolved against. Every path you write inside `[]` is joined onto this. Getting this wrong means the plugin looks for components in the wrong place, creates tags with wrong slugs, and writes `CHANGELOG.md` files in the wrong directories. When in doubt, set it to `"."` (repo root) and write full relative paths in `[]`. |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_OUTPUT_TAGS_FILE` | `""` | File to append created tags to (used by `kaniko-master-versions`) |
| `PLUGIN_SCOPE_EXCLUDE_REGEX` | `""` | **Python regex applied to every location before it is processed — both explicit ones you wrote and ones expanded from wildcards.** Any location that matches is silently skipped. This is the primary guard against accidentally releasing non-service folders (e.g. `docs/`, `scripts/`, `shared/`) when using `[*]` or `[plugins/*]` wildcards. Without it, a wildcard would release every subdirectory it finds, including utility folders that are not versioned components. Example: `^docs$\|^scripts$\|^shared$` |
| `PLUGIN_DRY_RUN` | `""` | `"true"` → show what would be released, skip all file writes |
| `PLUGIN_DEBUG` | `false` | `true` → detailed debug output for every git-cliff command and its result. Only `true` or `false` are valid values. |
| `PLUGIN_INITIAL_TAG` | `1.0.0` | Version for the first release of a component that has no existing tag |
| `PLUGIN_V_PREFIX` | `""` | Set to `"true"` to prepend `v` to the version number. `true` → `nati-v1.0.0`, unset/false → `nati-1.0.0` |
| `PLUGIN_CLIFF_TOML` | *(see below)* | Path to a custom `cliff.toml`. Resolution order: (1) this variable if set, (2) `./cliff.toml` in the working directory if it exists, (3) the `cliff.toml` bundled in the Docker image. |

#### `PLUGIN_BASE` examples

```
repo/
  nati/          ← PLUGIN_BASE="."  →  location [nati]
  plugins/
    docker/      ← PLUGIN_BASE="."  →  location [plugins/docker]
                    PLUGIN_BASE="./plugins"  →  location [docker]
```

Setting `PLUGIN_BASE="./plugins"` lets you write shorter locations (`[docker]`
instead of `[plugins/docker]`) but your tags will be `docker-1.0.0` instead of
`plugins-docker-1.0.0`. Choose based on what tag names you want.

#### `PLUGIN_SCOPE_EXCLUDE_REGEX` examples

```
# Exclude docs and scripts from wildcard expansion
PLUGIN_SCOPE_EXCLUDE_REGEX: "^docs$|^scripts$|^shared$"

# Exclude an entire group in a nested repo
PLUGIN_SCOPE_EXCLUDE_REGEX: "^base/legacy"

# Also works on explicit locations — if someone writes [docs] in their message,
# it is silently skipped without error
PLUGIN_SCOPE_EXCLUDE_REGEX: "^docs$"
```

---

## Building the plugin image

Build context must be the **repo root** (not this directory):

```bash
docker build -f plugins/master-versions/Dockerfile -t netanelzucaim123/master-versions:latest .
docker push netanelzucaim123/master-versions:latest
```
