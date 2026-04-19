# master-versions

Woodpecker CI plugin that parses a PR description, calculates semantic versions via git-cliff, writes `CHANGELOG.md` files per component, and records created tags for downstream steps.

---

## Contents

1. [PR body format](#1-pr-body-format)
2. [Continuation lines](#2-continuation-lines)
3. [Wildcard expansion](#3-wildcard-expansion)
4. [PLUGIN_CHANGELOG_LEVEL enforcement](#4-plugin_changelog_level-enforcement)
5. [Variables](#5-variables)
6. [Pipeline — standalone](#6-pipeline--standalone)
7. [Pipeline — with kaniko-master-versions (optional)](#7-pipeline--with-kaniko-master-versions-optional)
8. [Examples](#8-examples)

---

## 1. PR body format

Every release is triggered by a **commit line** in your PR description:

```
type[location]: description
```

> The `[` bracket immediately after the type is what makes a line a commit line.
> Without it the line is ignored — even if it starts with `feat` or `fix`.

### Types (defined in `cliff.toml`)

| Type | Version bump | Notes |
|------|-------------|-------|
| `feat` | Minor | New feature or capability |
| `fix` | Patch | Bug fix, crash fix |
| `breaking` | Major | Backwards-incompatible change |
| `other` | None | Explicit no-op — no release, useful as a continuation stopper |
| `!` after `]` | Major | Forces major regardless of type — e.g. `fix[nati]!: msg` |

> A type not listed in `cliff.toml` `commit_parsers` is silently ignored. See `DETAILEDREADME.md` to understand how to add types.

### Location `[location]`

| What you write | What it means |
|----------------|--------------|
| `[nati]` | Component at `PLUGIN_BASE_PATH/nati/` → tag `nati-1.0.0` |
| `[plugins/docker]` | Component at `PLUGIN_BASE_PATH/plugins/docker/` → tag `plugins-docker-1.0.0` |
| `[]` | Repo root (`PLUGIN_BASE_PATH` itself) → tag `1.0.0` |
| `[nati, check]` | Releases **both** `nati` and `check` from one line |
| `[*]` | Wildcard — expands to all direct subdirs of `PLUGIN_BASE_PATH` |
| `[plugins/*]` | Wildcard — expands to all subdirs of `PLUGIN_BASE_PATH/plugins/` |

Slashes in the location become hyphens in the tag:

| Location | Tag |
|----------|-----|
| `nati` | `nati-1.1.0` |
| `plugins/docker` | `plugins-docker-1.0.1` |
| `base/argo` | `base-argo-2.0.0` |
| *(empty)* | `1.0.0` |

### Format rules

- Type must start at the **very beginning of the line** — no leading spaces
- Type must be **lowercase** — `FEAT[nati]: ...` is ignored
- `[location]` must immediately follow the type — no space between them
- After `]` only `:` or `!:` are valid — anything else makes the line continuation text of the previous commit
- `[location]` must not contain `[` or `]` inside it

---

## 2. Continuation lines

After a commit line is matched, **every following line is collected as the commit body** until the next commit line is encountered.

A line starts a new commit only when **both** are true simultaneously:
1. It matches a `commit_parsers` pattern at position 0
2. That match is immediately followed by `[`

```
feat[nati]:
  Replace basic auth with OAuth2.
  Supports Google, GitHub, and GitLab providers.

  Blank lines are included too.

fix[check]: unrelated fix — this line ends the continuation above
```

**Using `other` to stop a continuation block cleanly:**

```
feat[nati]: big feature
  These lines are continuation text.

other[nati]: stop                ← ends continuation, no release entry
## PR Checklist                  ← continuation of "other" — also skipped
- [x] Tests pass

fix[check]: separate fix         ← new commit, clean start
```

---

## 3. Wildcard expansion

`[*]` expands to all direct subdirectories of `PLUGIN_BASE_PATH`.
`[base/*]` expands to all subdirectories of `PLUGIN_BASE_PATH/base/`.

```
feat[plugins/*]: bump all third-party libs to latest
```

Expands to every subdirectory of `plugins/` and releases each independently.

Use `PLUGIN_SCOPE_EXCLUDE_REGEX` to exclude folders you never want released:

```
PLUGIN_SCOPE_EXCLUDE_REGEX=^docs$|^scripts$
```

When a wildcard is used, the plugin prints both the pre-expansion and post-expansion commit sets:

```
>>> COMMITS TO PROCESS:
    [plugins/*]
      feat: bump all third-party libs to latest
>>> COMMITS AFTER WILDCARD EXPANSION:
    [plugins/docker]
      feat: bump all third-party libs to latest
    [plugins/kaniko]
      feat: bump all third-party libs to latest
```

---

## 4. PLUGIN_CHANGELOG_LEVEL enforcement

Every `[location]` must match the declared path depth. If any location in a multi-location line fails, **the entire line is skipped**.

| Level | Accepts | Example |
|-------|---------|---------|
| `0` | root only | `feat[]: msg` |
| `1` | top-level dirs | `feat[nati]: msg` |
| `2` | one level nested | `feat[plugins/docker]: msg` |
| `N` | N−1 slashes | `feat[a/b/.../z]: msg` |

```
PLUGIN_CHANGELOG_LEVEL=1

feat[nati]: add dashboard          → ACCEPT (0 slashes)
fix[plugins/docker]: fix socket    → SKIP  (1 slash, expected 0)
feat[nati, plugins/docker]: shared → SKIP  (plugins/docker fails — whole line skipped)
feat[nati, harel]: auth update     → ACCEPT (both have 0 slashes)
```

---

## 5. Variables

### Required

| Variable | Description |
|----------|-------------|
| `PLUGIN_MESSAGE_FILE` | Path to a file containing the text to parse. Usually the PR body written to disk by CI. The file can contain any mix of prose and commit lines — only commit lines trigger a release. |
| `PLUGIN_BASE_PATH` | Root directory all `[location]` paths are resolved against. Getting this wrong silently breaks tag names, CHANGELOG paths, and directory resolution. When in doubt use `"."` and write full relative paths in `[]`. |
| `PLUGIN_CHANGELOG_LEVEL` | Enforces the expected path depth of every `[location]`. Lines with non-matching depth are skipped. If not set the plugin exits with code 1. |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_OUTPUT_TAGS_FILE` | `""` | File to write created tags to — one per line. Always created/truncated at startup even if no tags are produced. Consumed by `kaniko-master-versions` when building Docker images. |
| `PLUGIN_SCOPE_EXCLUDE_REGEX` | `""` | Python regex applied to every location before processing. Any matching location is skipped. Example: `^docs$\|^scripts$`. |
| `PLUGIN_VERBOSE` | `0` | `0` = minimal output, `1` = show git-cliff commands, `2` = full trace including stderr. |
| `PLUGIN_INITIAL_TAG` | `1.0.0` | Version used for the first release of a component with no existing tag. |
| `PLUGIN_V_PREFIX` | `""` | Set to `"true"` to prefix version with `v` — `nati-v1.0.0` instead of `nati-1.0.0`. |
| `PLUGIN_CLIFF_TOML` | *(bundled)* | Path to a custom `cliff.toml`. Resolution order: (1) this variable, (2) `./cliff.toml` in working dir, (3) bundled copy in the image. |

---

## 6. Pipeline — standalone

Use `master-versions` on its own when you only need versioning and changelogs — no Docker image builds involved.

```yaml
steps:
  - name: Fetch PR body
    image: alpine/curl
    commands:
      - curl -s $GITEA_API/repos/$CI_REPO/pulls/$CI_COMMIT_PULL_REQUEST
          | jq -r '.body' > pr_body.txt

  - name: Run release
    image: netanelzucaim123/master-versions:latest
    settings:
      message_file: pr_body.txt
      base_path: .
      changelog_level: 1
      output_tags_file: new_tags.txt

  - name: Push changelogs and tags
    image: alpine/git
    commands:
      - git config user.email "ci@example.com"
      - git config user.name "CI"
      - git add "*/CHANGELOG.md"
      - git diff --cached --quiet || git commit -m "chore: update changelogs"
      - git push --force --tags
```

---

## 7. Pipeline — with kaniko-master-versions (optional)

> **Only add this step if your repository contains Dockerfiles you want to build and push.**
> If you only do versioning and changelogs, the previous section is all you need.

When each component has a `Dockerfile`, `kaniko-master-versions` reads the tags file produced by `master-versions` and builds + pushes the corresponding Docker image for each tag.

```
master-versions                         kaniko-master-versions
──────────────────────────────          ──────────────────────────────────────────
parse PLUGIN_MESSAGE_FILE               reads new_tags.txt line by line
  → nati-1.1.0                     ──►  nati-1.1.0       → PLUGIN_BASE_PATH/nati/Dockerfile
  → plugins-docker-2.0.0           ──►  plugins-docker-2.0.0 → PLUGIN_BASE_PATH/plugins/docker/Dockerfile
appended to new_tags.txt                builds and pushes each image via Kaniko
```

```yaml
steps:
  - name: Fetch PR body
    image: alpine/curl
    commands:
      - curl -s $GITEA_API/repos/$CI_REPO/pulls/$CI_COMMIT_PULL_REQUEST
          | jq -r '.body' > pr_body.txt

  - name: Run release
    image: netanelzucaim123/master-versions:latest
    settings:
      message_file: pr_body.txt
      base_path: .
      changelog_level: 1
      output_tags_file: new_tags.txt

  - name: Push changelogs and tags
    image: alpine/git
    commands:
      - git config user.email "ci@example.com"
      - git config user.name "CI"
      - git add "*/CHANGELOG.md"
      - git diff --cached --quiet || git commit -m "chore: update changelogs"
      - git push --force --tags

  - name: Build and push images
    image: netanelzucaim123/kaniko-master-versions:latest
    settings:
      base_path: .
      tags_file: new_tags.txt
      repo: myorg
    secrets:
      - source: docker_username
        target: plugin_username
      - source: docker_password
        target: plugin_password
```

---

## 8. Examples

### Single component — minor bump

```
feat[nati]: add sidebar with user stats
```
→ `nati/CHANGELOG.md` updated, tag `nati-1.1.0`

---

### Nested component — patch bump

```
fix[plugins/docker]: increase read deadline to 30s
```
→ `plugins/docker/CHANGELOG.md` updated, tag `plugins-docker-1.0.1`

---

### Repo root release

```
feat[]: add woodpecker pipeline definition
```
→ `CHANGELOG.md` at root updated, tag `1.0.0`

---

### Multiple components from one line

```
feat[nati, check, base/argo]: centralise JWT validation
```
→ Three independent releases: `nati-1.1.0`, `check-1.1.0`, `base-argo-1.1.0`

---

### Breaking change — two ways to force major

```
breaking[nati]: remove /v1 endpoints
feat[nati]!: replace REST with gRPC interface
```
Both produce a major bump.

---

### Multi-line changelog entry

```
feat[nati]:
  Replace basic auth with OAuth2.
  Supports Google, GitHub, and GitLab providers.
  Adds token refresh logic and session expiry handling.

fix[check]: unrelated fix — ends the continuation above
```

The full multi-line text becomes the `nati` changelog entry.

---

### Wildcard — release all plugins at once

```
feat[plugins/*]: bump all third-party libs to latest
```
→ Expands to every subdirectory of `plugins/` and releases each independently.

---

### Mixed PR body — multiple components, types, and prose

```
feat[nati]: add avatar upload
fix[plugins/docker]: lock shared map access
breaking[base/argo]!: rename all env vars to SNAKE_CASE
other[]: explicit no-op at root

This is a checklist:
- [x] Tests pass
- [x] Docs reviewed
```

Result:
- `nati` → minor bump
- `plugins/docker` → patch bump
- `base/argo` → major bump (`breaking` + `!`)
- root → no release (`other` is skip type)
- Checklist lines → continuation of `other[]` → also skipped
