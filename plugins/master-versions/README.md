# master-versions

Woodpecker CI plugin that parses a PR description, calculates semantic versions via git-cliff, writes `CHANGELOG.md` files per component, and records created tags for downstream steps.

### What is a CHANGELOG.md?

A `CHANGELOG.md` is a file that lives inside each component's directory and tracks every release of that component in a human-readable format. Every time a component is released, a new entry is prepended to its `CHANGELOG.md` containing the version, the date, and the commit messages that triggered the release.

```
## [nati-1.2.0] - 2024-03-15 14:30

### ✨ Features
* add OAuth2 login support

---

## [nati-1.1.0] - 2024-02-10 09:00

### 🐛 Bug Fixes
* resolve socket timeout on large uploads
```

This file is committed to the repository so the full release history is always visible in source control — no external service needed.

In a monorepo, each component has its own independent `CHANGELOG.md` and its own version — `nati/CHANGELOG.md`, `plugins/docker/CHANGELOG.md`, `base/argo/CHANGELOG.md`, and so on. Releasing one component never affects the version or changelog of another. Managing all of this manually across many components is error-prone and tedious. This plugin automates it: one PR description drives all the releases, each component gets its own entry, and nothing is touched unless you explicitly named it.

---

## Contents

1. [PR body format](#1-pr-body-format)
2. [Continuation lines](#2-continuation-lines)
3. [Wildcard expansion](#3-wildcard-expansion)
4. [PLUGIN_CHANGELOG_LEVEL enforcement](#4-plugin_changelog_level-enforcement)
5. [Variables](#5-variables)
6. [Cross-referencing with changed-files](#6-cross-referencing-with-changed-files)
7. [Pipeline — standalone](#7-pipeline--standalone)
8. [Pipeline — with buildah-master-versions (optional)](#8-pipeline--with-buildah-master-versions-optional)
9. [Examples](#9-examples)


---

## 1. PR body format

Every release is triggered by a **commit line** in your PR description:

```
type[location]: description
```

> The `[` bracket immediately after the type is what makes a line a commit line.
> Without it the line is ignored — even if it starts with `feat` or `fix`.

### Semantic versioning — major, minor, patch

Every version has three numbers: `MAJOR.MINOR.PATCH` (e.g. `1.4.2`).

| Part | When it bumps | Example |
|------|--------------|---------|
| `PATCH` | A bug fix — nothing new, nothing removed | `1.4.2` → `1.4.3` |
| `MINOR` | A new feature — backwards compatible, nothing removed | `1.4.2` → `1.5.0` |
| `MAJOR` | A breaking change — existing behaviour removed or changed incompatibly | `1.4.2` → `2.0.0` |

When a part is bumped, all lower parts reset to `0`.

### Types (defined in `cliff.toml`)

| Type | Version bump | Notes |
|------|-------------|-------|
| `feat` | Minor | New feature or capability |
| `fix` | Patch | Bug fix, crash fix |
| `breaking` | Major | Backwards-incompatible change |
| `other` | None | Explicit no-op — no release, useful as a continuation stopper |
| `code_description` | None | Code-level description update (comments, docstrings) — no release, skip=true |
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

**Unknown type (not in `cliff.toml`) becomes continuation, not a new commit:**

A line only opens a new commit if its type matches a `commit_parsers` pattern. If the type is unknown, `_match_line` returns nothing and the line is absorbed into the body of the preceding commit — even if it looks like a commit line.

```
feat[plugins/nati]: checking non cliff.toml word
checkcheck[plugins/nati]: should be continuation
```

`checkcheck` is not in `cliff.toml` `commit_parsers` → `_match_line` returns nothing → the line is **not** treated as a new commit. It becomes continuation body of the `feat` line above. The commit passed to git-cliff is:

```
feat: checking non cliff.toml word
checkcheck[plugins/nati]: should be continuation
```

Both lines land in `plugins/nati/CHANGELOG.md` under the same entry. `checkcheck[...]` is preserved verbatim in the changelog body.

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

Every `[location]` must match one of the declared path depths. If any location in a multi-location line fails, **the entire line is skipped**.

| Level | Accepts | Example |
|-------|---------|---------|
| `0` | root only | `feat[]: msg` |
| `1` | top-level dirs | `feat[nati]: msg` |
| `2` | one level nested | `feat[plugins/docker]: msg` |
| `N` | depth `N` (N−1 slashes) | `feat[a/b/.../z]: msg` |

```
PLUGIN_CHANGELOG_LEVEL=1

feat[nati]: add dashboard          → ACCEPT (0 slashes)
fix[plugins/docker]: fix socket    → SKIP  (1 slash, expected 0)
feat[nati, plugins/docker]: shared → SKIP  (plugins/docker fails — whole line skipped)
feat[nati, harel]: auth update     → ACCEPT (both have 0 slashes)
```

### Allowing several depths at once

`PLUGIN_CHANGELOG_LEVEL` may be a **comma-separated list** of depths. A location is accepted
if its depth matches **any** value in the set (exact membership — not a min/max range). This lets
a single run release components living at different nesting levels — e.g. flat plugins at depth 2
alongside deeply-nested base images at depth 4.

```
PLUGIN_CHANGELOG_LEVEL=2,4

feat[plugins/docker]: fix socket             → ACCEPT (depth 2 ∈ {2,4})
feat[base/uv/0.11.29/python-310]: uv image   → ACCEPT (depth 4 ∈ {2,4})
feat[nati]: add dashboard                    → SKIP   (depth 1 ∉ {2,4})
feat[base/infra/x]: rules                    → SKIP   (depth 3 ∉ {2,4})
```

---

## 5. Variables

### Required

| Variable | Description |
|----------|-------------|
| `PLUGIN_BASE_PATH` | Root directory all `[location]` paths are resolved against. Getting this wrong silently breaks tag names, CHANGELOG paths, and directory resolution. When in doubt use `"."` and write full relative paths in `[]`. |
| `PLUGIN_CHANGELOG_LEVEL` | Enforces the expected path depth of every `[location]`. A single depth (`2`) or a comma-separated set of depths (`2,3,4`); a location is accepted if its depth is in the set. Lines with non-matching depth are skipped. If not set the plugin exits with code 1. |

### Message retrieval

The plugin retrieves the message to parse itself — there's no file-path input for it. It dispatches on `CI_PIPELINE_EVENT` (a Woodpecker-provided variable, not user-set):

| `CI_PIPELINE_EVENT` | Source | Required variables |
|---|---|---|
| `pull_request` | Fetched from the Bitbucket Server REST API (`GET .../pull-requests/{id}`), using the PR's `description` field. | `PLUGIN_BITBUCKET_TOKEN`, `CI_FORGE_URL`, `CI_REPO_OWNER`, `CI_REPO_NAME`, `CI_COMMIT_PULL_REQUEST` |
| `manual` (default) | The `PLUGIN_MESSAGE` env var, used as-is. On a manual run the plugin loudly echoes the full message back — a banner and every line numbered between `BEGIN PLUGIN_MESSAGE` / `END PLUGIN_MESSAGE` markers (tabs shown as `\t`) — so you can see exactly what was submitted. This is the fastest way to spot a mistyped message (e.g. a leading space or a pasted image reference) that would otherwise make every line silently `IGNORED`. | `PLUGIN_MESSAGE` |
| any other event (e.g. `push`) | `git log -1 --pretty=%B`. If the commit message contains a `DESCRIPTION` section (the custom merge-commit template — see the "Pipeline Integration" notes), only the text after that marker is used; otherwise the full commit message is used. | *(none — reads local git history)* |

The plugin exits with code 1 if the message can't be determined (e.g. a missing required variable, or an empty `PLUGIN_MESSAGE` on a manual run). Whatever message is retrieved is also written to `pr_body.txt` in the working directory, so later pipeline steps that grep it for override values (e.g. `PLUGIN_BASE_PATH=`) keep working.

**`PLUGIN_BITBUCKET_TOKEN` is also used for tag resolution.** Before processing any component, the plugin does an authenticated `git fetch` of the resolved branch so git's tag auto-follow pulls the existing version tags (the CI clone uses `tags: false`, so the workspace starts with none). The plugin's own step image has no Bitbucket credentials of its own, so the token is sent as an `Authorization: Bearer <token>` header via `git -c http.extraHeader=…` (the only scheme Bitbucket DC HTTP tokens accept). Without it the fetch 401s, no tags are visible, and every component is mistakenly treated as a first release (recreating `…-v1.0.0` instead of bumping). Set `PLUGIN_BITBUCKET_TOKEN` on any event where you want correct version bumps, not just `pull_request`.

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_OUTPUT_TAGS_FILE` | `""` | File to write created tags to — one per line. Always created/truncated at startup even if no tags are produced. Consumed by `buildah-master-versions` when building Docker images. |
| `PLUGIN_OUTPUT_LOCATIONS_FILE` | `""` | File to write all accepted locations to — one per line, sorted. Always created/truncated at startup (empty if nothing qualifies). A location appears here only when **both** conditions are met: (1) the line starts with a type defined in `cliff.toml` `commit_parsers` (including `skip=true` types such as `other` and `code_description`) followed immediately by `[`, and (2) the location inside `[]` matches `PLUGIN_CHANGELOG_LEVEL`. Lines that fail either check are silently excluded. Example with `PLUGIN_CHANGELOG_LEVEL=2`: `other[natnat]: msg` is excluded (0 slashes, level expects 1); `other[plugins/natnat]: msg` is included (1 slash, passes level 2). Useful for cross-referencing against actually-changed directories; see [section 6](#6-cross-referencing-with-changed-files). |
| `PLUGIN_SCOPE_EXCLUDE_REGEX` | `""` | Python regex applied to every location before processing. Any matching location is skipped. Example: `^docs$\|^scripts$`. |
| `PLUGIN_VERBOSE` | `0` | `0` = minimal output, `1` = show git-cliff commands, `2` = full trace including stderr. |
| `PLUGIN_INITIAL_TAG` | `1.0.0` | Version used for the first release of a component with no existing tag. |
| `PLUGIN_V_PREFIX` | `"true"` | `"true"` → tags use `v` prefix (`nati-v1.0.0`). Set to `"false"` to disable — `nati-1.0.0`. |
| `PLUGIN_CLIFF_TOML` | *(bundled)* | Path to a custom `cliff.toml`. Resolution order: (1) this variable, (2) `./cliff.toml` in working dir, (3) bundled copy in the image. |

---

## 6. Cross-referencing with changed-files

`PLUGIN_OUTPUT_LOCATIONS_FILE` writes every accepted location as a sorted, newline-separated list. Because it captures all qualifying locations — including those whose commit type is `skip=true` in `cliff.toml` (e.g. `other`, `code_description`) — it acts as a full scope manifest of everything the PR author claimed to touch, regardless of whether a release was produced.

The [`changed-files`](../changed-files/) plugin writes the set of directories that actually changed in the push. The [`master-versions-vs-changed-files`](../master-versions-vs-changed-files/) plugin then compares the two and reports mismatches:

- **Changed but not declared** — a directory changed on disk but no `[location]` in the PR body covers it
- **Declared but not changed** — a `[location]` appears in the PR body but no files under it actually changed

```yaml
steps:
  - name: Fetch PR body
    image: alpine/curl
    commands:
      - curl -s $GITEA_API/repos/$CI_REPO/pulls/$CI_COMMIT_PULL_REQUEST
          | jq -r '.body' > pr_body.txt

  - name: Get changed dirs
    image: netanelzucaim123/changed-files:latest
    settings:
      output_file: changed_dirs.txt
      output_type: dirs
      folder_depth: 1

  - name: Run release
    image: netanelzucaim123/master-versions:latest
    settings:
      message_file: pr_body.txt
      base_path: .
      changelog_level: 1
      output_tags_file: new_tags.txt
      output_locations_file: release_locations.txt

  - name: Check scopes vs changes
    image: netanelzucaim123/master-versions-vs-changed-files:latest
    settings:
      master_versions_locations_file: release_locations.txt
      changed_dirs_file: changed_dirs.txt
      fail_on_mismatch: false
```

> Set `fail_on_mismatch: true` to fail the pipeline when the PR description and the actual changed directories do not match exactly.

---

## 7. Pipeline — standalone

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

## 8. Pipeline — with buildah-master-versions (optional)

> **Only add this step if your repository contains Dockerfiles you want to build and push.**
> If you only do versioning and changelogs, the previous section is all you need.

When each component has a `Dockerfile`, `buildah-master-versions` reads the tags file produced by `master-versions` and builds + pushes the corresponding Docker image for each tag.

```
master-versions                         buildah-master-versions
──────────────────────────────          ──────────────────────────────────────────
parse retrieved message                 reads new_tags.txt line by line
  → nati-1.1.0                     ──►  nati-1.1.0       → PLUGIN_BASE_PATH/nati/Dockerfile
  → plugins-docker-2.0.0           ──►  plugins-docker-2.0.0 → PLUGIN_BASE_PATH/plugins/docker/Dockerfile
appended to new_tags.txt                builds and pushes each image via buildah
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
    image: netanelzucaim123/buildah-master-versions:latest
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

## 9. Examples

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
code_description[nati]: improve inline comments

This is a checklist:
- [x] Tests pass
- [x] Docs reviewed
```

Result:
- `nati` → minor bump (`feat` wins; `code_description` is skip=true and adds no release on its own)
- `plugins/docker` → patch bump
- `base/argo` → major bump (`breaking` + `!`)
- root → no release (`other` is skip=true)
- Checklist lines → continuation of `other[]` → also skipped
