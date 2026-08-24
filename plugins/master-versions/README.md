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

> ### ⚠️ Required one-time Bitbucket setup
> A real release only happens on a `push` to `main` after a PR merge — and that step reads the
> PR description out of the **merge commit itself**. This only works if the repository's PR merge
> strategy is set to **Squash**, with a custom commit message template that injects the PR
> description under a `DESCRIPTION` marker. Without this, every merge "succeeds" but silently
> releases nothing. Full steps and the exact template: [§6](#6-triggering-events--manual-pull_request-and-push-merge).

---

## Contents

1. [PR body format](#1-pr-body-format)
2. [Continuation lines](#2-continuation-lines)
3. [Wildcard expansion](#3-wildcard-expansion)
4. [PLUGIN_CHANGELOG_LEVEL enforcement](#4-plugin_changelog_level-enforcement)
5. [Variables](#5-variables)
6. [Triggering events — manual, pull_request, and push (merge)](#6-triggering-events--manual-pull_request-and-push-merge)
7. [Tutorial — set up Bitbucket, add the pipeline, release a hotfix](#7-tutorial--set-up-bitbucket-add-the-pipeline-release-a-hotfix)
8. [Cross-referencing with changed-files](#8-cross-referencing-with-changed-files)
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
| `PLUGIN_MESSAGE` | Required only for a `manual` run — the text to parse. Not used for `pull_request` or `push` events (those retrieve the message themselves). See [§6](#6-triggering-events--manual-pull_request-and-push-merge). |
| `PLUGIN_BITBUCKET_TOKEN` | Required on **every** event, not just `pull_request` — it authenticates the branch fetch used for tag resolution (`CI_COMMIT_BRANCH`/`CI_COMMIT_TARGET_BRANCH`, set on essentially every real run). Missing it fails the run outright on any event: on `pull_request` there's no PR description to fetch at all; on `manual`/`push` the branch fetch 401s and the run exits with code 1 rather than silently computing a wrong version. See [§6](#6-triggering-events--manual-pull_request-and-push-merge). |

Clone step settings (`partial`, `depth`, `tags`) don't matter — any combination works; see
`DETAILEDREADME.md` for why.

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_OUTPUT_TAGS_FILE` | `""` | File to write created tags to — one per line. Always created/truncated at startup even if no tags are produced. Consumed by `buildah-master-versions` when building Docker images. |
| `PLUGIN_OUTPUT_LOCATIONS_FILE` | `""` | File to write all accepted locations to — one per line, sorted. Always created/truncated at startup (empty if nothing qualifies). A location appears here only when **both** conditions are met: (1) the line starts with a type defined in `cliff.toml` `commit_parsers` (including `skip=true` types such as `other` and `code_description`) followed immediately by `[`, and (2) the location inside `[]` matches `PLUGIN_CHANGELOG_LEVEL`. Lines that fail either check are silently excluded. Example with `PLUGIN_CHANGELOG_LEVEL=2`: `other[natnat]: msg` is excluded (0 slashes, level expects 1); `other[plugins/natnat]: msg` is included (1 slash, passes level 2). Useful for cross-referencing against actually-changed directories; see [section 8](#8-cross-referencing-with-changed-files). |
| `PLUGIN_SCOPE_EXCLUDE_REGEX` | `""` | Python regex applied to every location before processing. Any matching location is skipped. Example: `^docs$\|^scripts$`. |
| `PLUGIN_VERBOSE` | `0` | `0` = minimal output, `1` = show git-cliff commands, `2` = full trace including stderr. |
| `PLUGIN_INITIAL_TAG` | `1.0.0` | Version used for the first release of a component with no existing tag. |
| `PLUGIN_V_PREFIX` | `"true"` | `"true"` → tags use `v` prefix (`nati-v1.0.0`). Set to `"false"` to disable — `nati-1.0.0`. |
| `PLUGIN_CLIFF_TOML` | *(bundled)* | Path to a custom `cliff.toml`. Resolution order: (1) this variable, (2) `./cliff.toml` in working dir, (3) bundled copy in the image. |

---

## 6. Triggering events — manual, pull_request, and push (merge)

The plugin retrieves its own message — there's no explicit input step. It looks at
`CI_PIPELINE_EVENT` (a Woodpecker-provided variable) and picks one of three retrieval paths.
This section walks through what actually happens on each, end to end, across this repo's two
pipelines (`.woodpecker/pr.yml` and `.woodpecker/publish.yml`).

### `manual` — you trigger a run yourself

You open Woodpecker's UI (or CLI) and manually trigger a pipeline, typing the release message
into the trigger dialog's `MESSAGE` field. `publish.yml`'s `Run release (manual)` step passes it
straight through as `PLUGIN_MESSAGE: "${MESSAGE}"`. `_retrieve_manual_message()` uses it as-is
(no external calls) and — because a mistyped message is the #1 cause of a confusing "nothing
released" run — echoes it back line-numbered, whitespace-marked, between `BEGIN`/`END
PLUGIN_MESSAGE` banners, so you can see exactly what was submitted before wondering why a line
didn't match.

**When to use it:** a hotfix on a branch that never goes through a PR, or any release that
doesn't have a PR description to source from. First-releasing a new component still goes through
a PR like any other change — its description drives the release the same way via the
`pull_request`/`push` path below, nothing special about a first release requires `manual`. There's
no branch restriction on this trigger (`when: - event: manual` in `publish.yml`, no `branch:`
filter), so it can run against whatever branch you're on when you trigger it.

### `pull_request` — every PR open/update (`pr.yml`)

Fires whenever a PR is opened or updated against its target branch. The plugin fetches the PR's
**live** description directly from the Bitbucket Server REST API
(`_retrieve_pull_request_message()`, using `PLUGIN_BITBUCKET_TOKEN` /
`CI_FORGE_URL` / `CI_REPO_OWNER` / `CI_REPO_NAME` / `CI_COMMIT_PULL_REQUEST`) — not whatever the
description said when the PR was first opened.

This run computes what *would* be released and builds the candidate images
(`Build and push plugin images` step in `pr.yml`) — but it **never** pushes changelog commits
or creates tags. Doing so would rewrite the PR's own source branch on every push, which would
both re-trigger the `pull_request` event (Woodpecker does not honor `[skip ci]` on
`pull_request`, unlike `push`) and — because a brand-new component doesn't exist on the target
branch yet — re-release `v1.0.0` and duplicate its changelog entry on every single build. This
event exists purely to preview and validate the release and to produce buildable images; nothing
is persisted until the merge.

### `push` to the main branch (merge) — the only event that persists anything

`publish.yml` also triggers on `push`, but scoped tightly: `branch: main` **and**
`evaluate: 'CI_COMMIT_MESSAGE contains "Merge pull request"'`. This is deliberately not
`pull_request_closed` — that event also fires on PR decline and PR delete, which would silently
push stale changelogs and tags for a PR that never actually merged (see
`INCIDENT_PULL_REQUEST_CLOSED_TRAP.md` for the incident this guards against).

By the time this fires, there is no PR context left — `CI_COMMIT_PULL_REQUEST` isn't set on a
plain push — so the Bitbucket-API path used by `pull_request` isn't available here.
`_retrieve_push_message()` instead reads the merge commit's own body via
`git log -1 --pretty=%B` and takes everything after a `DESCRIPTION` marker line. **This only
works if Bitbucket's merge commit actually contains that marker and the PR description under
it** — which is not what Bitbucket produces by default. That's the required setup covered in
[§7A](#7-tutorial--set-up-bitbucket-add-the-pipeline-release-a-hotfix).

Once the message is retrieved, `publish.yml`'s `Run release (merge)` step computes every
version, builds and pushes the real images, and the final `Push changelogs to Git` step commits
`CHANGELOG.md` files and creates the release tags — the only point in either pipeline where
anything is actually persisted back to git.

---

## 7. Tutorial — set up Bitbucket, add the pipeline, release a hotfix

A practical, copy-and-adapt guide for a repo that wants to *use* `master-versions`. Do the three
parts in order: A must be done before a merge will ever produce a release, B before any pipeline
runs at all, and C assumes A and B are already in place.

### A. One-time Bitbucket setup

You need **repository admin** rights. This is what makes the release description available to
the pipeline after a PR is merged.

1. Repo → **Repository settings** (gear icon) → **Pull Requests**.
2. Under **Merge strategies**, set **Squash** as the default. The `DESCRIPTION` template in step
   3 only ever applies to a Squash merge — whoever merges a PR still picks the strategy for that
   merge, and Bitbucket lets you leave other strategies enabled if you want that flexibility. But
   picking anything other than Squash for a given merge silently skips the release: a `no-ff`
   merge commit still matches `publish.yml`'s `evaluate: CI_COMMIT_MESSAGE contains "Merge pull
   request"` guard and the pipeline still runs — it just merges with **no `DESCRIPTION` section**,
   so the release step finds nothing to release and that merge quietly ships nothing. **Disabling
   every other strategy, so Squash is the only option, is the recommended way to avoid this** —
   nobody merging a PR can forget and pick the wrong one. If you do restrict it, order matters:
   Bitbucket won't let you disable whichever strategy is currently the default, so set Squash as
   default *first* — only then does e.g. **Merge commit** become disableable.
3. On the Squash strategy, turn on the custom commit message option and paste this template
   exactly:
   ```
   Merge pull request #${id} from ${fromRefName}

   METADATA
   Title: ${title}
   Target: ${toRepoSlug} (${toRefName})
   Source: ${fromRepoSlug} (${fromRefName})

   DESCRIPTION
   ${description}
   ```
4. Under **Commit summaries**, set the maximum to `0`.
5. Save, then verify: open a throwaway PR with a body like `feat[nati]: verify squash template`,
   merge it, and on `main` run `git log -1 --pretty=%B`. You should see the template above with
   your PR body under `DESCRIPTION`. If you only see `Merge pull request #123 in PROJECT/repo
   from feature-branch to main` with nothing else, the merge used a non-Squash strategy — go back
   to step 2, not step 3; the template itself only ever applies to a Squash merge.

### B. Add the pipeline to your repo

**Secrets to create first**, in Woodpecker's repo settings → Secrets:

| Secret | Value |
|---|---|
| `bitbucket_token` | A Bitbucket HTTP access token with read access to this repo |
| `docker_username` / `docker_password` | Only needed if you're adding the `buildah-master-versions` step below — credentials for the registry you push built images to |

**When to include the `Build and push plugin images` step (`buildah-master-versions`):** only if
your components have their own `Dockerfile` and you actually want an image built and pushed for
every tag `master-versions` creates. It reads `PLUGIN_OUTPUT_TAGS_FILE` (`new_tags.txt`) and
resolves each tag to `PLUGIN_BASE_PATH/<location>/Dockerfile`. If you only need versioning and
changelogs — no image builds — drop this step (and the `docker_username`/`docker_password`
secrets) from both pipelines below; everything else still works unchanged.

**Create `.woodpecker/pr.yml`** — runs on every PR, computes candidate versions and builds
images, never touches git:

```yaml
clone:
  git:
    image: woodpeckerci/plugin-git:latest

when:
  - event: pull_request

steps:
  - name: Run release
    image: netanelzucaim123/master-versions:latest
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_OUTPUT_TAGS_FILE: "new_tags.txt"
      PLUGIN_BITBUCKET_TOKEN:
        from_secret: bitbucket_token
      PLUGIN_CHANGELOG_LEVEL: "1"   # set to whatever depth(s) your components live at, e.g. "2,3"

  # Only needed if your components have Dockerfiles you want built and pushed — see §7B above.
  - name: Build and push plugin images
    image: netanelzucaim123/buildah-master-versions:latest
    privileged: true
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_TAGS_FILE: "new_tags.txt"
      PLUGIN_REPO: "myorg"
    secrets:
      - source: docker_username
        target: plugin_username
      - source: docker_password
        target: plugin_password
```

**Create `.woodpecker/publish.yml`** — the only pipeline that ever writes back to git:

```yaml
clone:
  git:
    image: woodpeckerci/plugin-git:latest

when:
  - event: manual
  - event: push
    branch: main
    evaluate: 'CI_COMMIT_MESSAGE contains "Merge pull request"'

steps:
  - name: Run release (manual)
    image: netanelzucaim123/master-versions:latest
    when:
      - event: manual
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_OUTPUT_TAGS_FILE: "new_tags.txt"
      PLUGIN_BITBUCKET_TOKEN:
        from_secret: bitbucket_token
      PLUGIN_MESSAGE: "${MESSAGE}"   # the text you type into Woodpecker's manual-trigger dialog
      PLUGIN_CHANGELOG_LEVEL: "1"

  - name: Run release (merge)
    image: netanelzucaim123/master-versions:latest
    when:
      - event: push
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_OUTPUT_TAGS_FILE: "new_tags.txt"
      PLUGIN_BITBUCKET_TOKEN:
        from_secret: bitbucket_token
      PLUGIN_CHANGELOG_LEVEL: "1"

  # Only needed if your components have Dockerfiles you want built and pushed — see §7B above.
  - name: Build and push plugin images
    image: netanelzucaim123/buildah-master-versions:latest
    privileged: true
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_TAGS_FILE: "new_tags.txt"
      PLUGIN_REPO: "myorg"
    secrets:
      - source: docker_username
        target: plugin_username
      - source: docker_password
        target: plugin_password

  - name: Push changelogs to Git
    image: alpine/git
    commands:
      - git config --global user.email "ci-bot@example.com"
      - git config --global user.name "CI Bot"
      - git config --global safe.directory '*'
      - find . -name "CHANGELOG.md" -not -path "./.git/*" | xargs -r git add
      - |
        if [ -n "$${CI_COMMIT_BRANCH}" ]; then
          if ! git diff --cached --quiet; then
            git commit -m "chore(release): update CHANGELOG.md files [skip ci]"
            git push --force-with-lease origin "HEAD:$${CI_COMMIT_BRANCH}"
          fi
          for tag in $(cat new_tags.txt); do git tag -f "$tag"; done
          git push --force --tags origin
        fi
```

> `$${CI_COMMIT_BRANCH}` (double `$`) is required, not a typo — Woodpecker rewrites `${...}` in
> `commands:` itself before the shell runs. A single `$` here silently becomes an empty string.

Swap `PLUGIN_CHANGELOG_LEVEL`, `PLUGIN_REPO`, and the two image names for your own values, then
test: open a throwaway PR (`pr.yml` should compute versions and build images, touching no git
state), then merge it (`publish.yml` should push a changelog commit and a tag to `main`). If the
merge run produces nothing, re-check part A first — a missing/incorrect squash template is the
most common cause.

### C. Release a hotfix

Use this when a bug is found in an **older** shipped version, not `main`'s current one — e.g.
`nati` is at `nati-v2.0.0` on `main`, but the fix is for the still-in-production `nati-v1.0.0`.
The goal is `nati-v1.0.1`, not `nati-v2.0.1`.

1. **Cut the branch from the broken release's tag — not from `main`:**
   ```bash
   git fetch --tags
   git checkout -b hotfix/nati-v1.0.1 nati-v1.0.0
   ```
   Branching from `main` instead would drag `main`'s later history (including `nati-v2.0.0`)
   into the new branch, and the release would bump from `2.0.0` instead of `1.0.0`.
2. **Make the fix and push the branch:**
   ```bash
   git commit -am "fix the bug"
   git push origin hotfix/nati-v1.0.1
   ```
3. **Trigger `publish.yml` manually** in Woodpecker: pick branch `hotfix/nati-v1.0.1`, and enter
   the release message in the trigger dialog:
   ```
   fix[nati]: patch bug found in 1.0.0
   ```
4. The pipeline resolves the previous version against this branch's own history — so it correctly
   bumps from `nati-v1.0.0` to `nati-v1.0.1`, builds and pushes the fixed image, and pushes the
   changelog commit and tag to `hotfix/nati-v1.0.1` (never to `main`).
5. **Verify:** `git tag -l 'nati-v*' --sort=-version:refname` should show `nati-v1.0.1` next to
   `nati-v1.0.0`, and the new image should be in your registry.
6. **If the fix should also land on `main`**, open a normal PR from the hotfix branch afterward —
   that's a separate, ordinary release through the usual `pull_request`/merge flow.

---

## 8. Cross-referencing with changed-files

**Use this when you want to verify that a PR's `[location]` declarations actually match the files
it changed** — catching a PR whose description says `feat[nati]: ...` but never touched `nati/`,
or one that touched `plugins/docker/` without declaring it anywhere. This compares what the PR
*claims* against what actually changed on disk, so it's PR-time validation — it's an addition to
`pr.yml` (§7B), not something `publish.yml` needs.

`PLUGIN_OUTPUT_LOCATIONS_FILE` writes every accepted location as a sorted, newline-separated list. Because it captures all qualifying locations — including those whose commit type is `skip=true` in `cliff.toml` (e.g. `other`, `code_description`) — it acts as a full scope manifest of everything the PR author claimed to touch, regardless of whether a release was produced.

The [`changed-files`](../changed-files/) plugin writes the set of directories that actually changed in the push. The [`master-versions-vs-changed-files`](../master-versions-vs-changed-files/) plugin then compares the two and reports mismatches:

- **Changed but not declared** — a directory changed on disk but no `[location]` in the PR body covers it
- **Declared but not changed** — a `[location]` appears in the PR body but no files under it actually changed

This is `pr.yml` from [§7B](#7-tutorial--set-up-bitbucket-add-the-pipeline-release-a-hotfix), with
two steps added: `Get changed dirs` runs first, and `Check scopes vs changes` runs right after
`Run release` (which gains `PLUGIN_OUTPUT_LOCATIONS_FILE`). Everything else — including whether
you keep the `Build and push plugin images` step — is unchanged from §7B:

```yaml
clone:
  git:
    image: woodpeckerci/plugin-git:latest

when:
  - event: pull_request

steps:
  - name: Get changed dirs
    image: netanelzucaim123/changed-files:latest
    settings:
      output_file: changed_dirs.txt
      output_type: dirs
      folder_depth: 1

  - name: Run release
    image: netanelzucaim123/master-versions:latest
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_OUTPUT_TAGS_FILE: "new_tags.txt"
      PLUGIN_OUTPUT_LOCATIONS_FILE: "release_locations.txt"
      PLUGIN_BITBUCKET_TOKEN:
        from_secret: bitbucket_token
      PLUGIN_CHANGELOG_LEVEL: "1"   # set to whatever depth(s) your components live at, e.g. "2,3"

  - name: Check scopes vs changes
    image: netanelzucaim123/master-versions-vs-changed-files:latest
    settings:
      master_versions_locations_file: release_locations.txt
      changed_dirs_file: changed_dirs.txt
      fail_on_mismatch: false

  # Only needed if your components have Dockerfiles you want built and pushed — see §7B.
  - name: Build and push plugin images
    image: netanelzucaim123/buildah-master-versions:latest
    privileged: true
    environment:
      PLUGIN_BASE_PATH: "."
      PLUGIN_TAGS_FILE: "new_tags.txt"
      PLUGIN_REPO: "myorg"
    secrets:
      - source: docker_username
        target: plugin_username
      - source: docker_password
        target: plugin_password
```

> Set `fail_on_mismatch: true` to fail the PR build when the description and the actual changed
> directories don't match exactly, instead of just reporting the mismatch. `publish.yml` is
> unaffected by any of this — its `Push changelogs to Git` step still runs exactly as shown in
> §7B.

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
