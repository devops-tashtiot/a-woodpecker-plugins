# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Stateless Monorepo Release Orchestrator** (`plugins/master-versions/release.py`). It automates semantic versioning and changelog generation for monorepo and nested monorepo structures. The **message (PR body) is the single source of truth** — release decisions are determined solely from message content, not from Git history.

---

## Commands

### Run the release orchestrator
```bash
PLUGIN_MESSAGE="feat(scope)[nati]: add dashboard" PLUGIN_BASE="." python3 plugins/master-versions/release.py
```

### Run with wildcards and exclusions
```bash
# Wildcard — release all direct subdirs
PLUGIN_MESSAGE="feat(scope)[*]: upgrade all" PLUGIN_BASE="." \
  PLUGIN_SCOPE_EXCLUDE_REGEX="^docs$|^shared$" python3 plugins/master-versions/release.py

# Wildcard — release all subdirs of a group
PLUGIN_MESSAGE="feat(scope)[base/*]: refactor base" PLUGIN_BASE="." python3 plugins/master-versions/release.py

# Dry run
PLUGIN_MESSAGE="feat(scope)[nati]: test" PLUGIN_BASE="." PLUGIN_DRY_RUN=true python3 plugins/master-versions/release.py
```

### Run unit tests
```bash
cd plugins/master-versions && python3 test_release.py
```

### Run unit tests (cliff.toml-coupled)
```bash
cd plugins/master-versions && python3 test_release_cliff.py
```

### Run Docker integration tests
```bash
cd plugins/kaniko-master-versions && ./test_release_docker.sh
```

---

## Environment Variables

### master-versions plugin (`release.py`)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PLUGIN_MESSAGE` | `""` | Yes | Text containing conventional commit lines (PR body, manual input, etc.) |
| `PLUGIN_BASE` | `"."` | Yes | Root directory. All `[location]` paths are resolved relative to this. |
| `PLUGIN_SCOPE_EXCLUDE_REGEX` | `""` | No | Python regex — any location matching this is skipped (wildcard and explicit) |
| `PLUGIN_OUTPUT_TAGS_FILE` | `""` | No | If set, each created tag is appended here (read by `kaniko-master-versions`) |
| `PLUGIN_DRY_RUN` | `""` | No | `"true"` → show what would be released, skip all file writes |
| `PLUGIN_DEBUG` | `false` | No | `true` or `false` — enables detailed debug output for every git-cliff call |
| `PLUGIN_INITIAL_TAG` | `1.0.0` | No | Version used for the first release of a component with no existing tag |
| `PLUGIN_V_PREFIX` | `""` | No | `"true"` → tags use `v` prefix (`nati-v1.0.0`); anything else → no prefix (`nati-1.0.0`) |
| `PLUGIN_CLIFF_TOML` | *(bundled)* | No | Path to a custom `cliff.toml`. Defaults to the one bundled in the image. |

### kaniko-master-versions plugin (`plugin.sh`)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PLUGIN_BASE` | — | Yes | Directory to scan for Dockerfiles |
| `PLUGIN_USERNAME` | — | Yes | Registry username |
| `PLUGIN_PASSWORD` | — | Yes | Registry password |
| `PLUGIN_TAGS_FILE` or `PLUGIN_TAGS` | — | Yes (one of) | Tags to process — file path or inline comma/newline string |
| `PLUGIN_REGISTRY` | `index.docker.io` | No | Docker registry |
| `PLUGIN_REPO` | `""` | No | Image repository/namespace prefix |
| `PLUGIN_DOCKERFILE` | `Dockerfile` | No | Dockerfile filename to look for |
| `PLUGIN_ALIASES` | *(not set)* | No | Comma-separated alias tags pushed alongside the version tag |
| `PLUGIN_DRY_RUN` | `false` | No | `"true"` → `--no-push` (skips actual push) |
| `PLUGIN_LOG_LEVEL` | `info` | No | Kaniko log verbosity |
| `PLUGIN_SKIP_TLS_VERIFY` | `false` | No | `"true"` → `--skip-tls-verify` |
| `PLUGIN_INSECURE` | `false` | No | `"true"` → `--insecure` |

---

## Architecture

### Message Format

```
type(scope)[location1, location2]!: description
```

- **`type`** — must be **lowercase**, must start at the **very beginning of the line** (no leading spaces — a line like `  feat[nati]: ...` is silently ignored). Drives the version bump level via `cliff.toml`.
- **`(scope)`** — **optional**. Free text describing what changed. Goes into the changelog entry. Does **not** affect which component is released. `feat[nati]: msg` (no scope) is valid.
- **`[location]`** — required. The filesystem path of the component to release, relative to `PLUGIN_BASE`. Controls tag prefix, `CHANGELOG.md` location, and `--include-path` isolation. Content must not contain `[` or `]` — `feat[na[ti]: msg` will never match as a commit line.
- **`!`** — optional bang after `[]`. Forces a major bump regardless of type.
- **Validation of bang/colon/description** is delegated entirely to git-cliff (`filter_unconventional = true` in `cliff.toml`). `release.py` only removes the `[locations]` bracket and passes the rest raw to git-cliff.
- **No line stripping**: lines are never `.strip()`-ed. A line with leading whitespace naturally fails to match `^feat` etc. Continuation lines are stored and joined exactly as written.

### Location (`[]`) Rules

| What you write | Meaning |
|----------------|---------|
| `[nati]` | Release component at `PLUGIN_BASE/nati/` → tag `nati-1.0.0` |
| `[plugins/docker]` | Release component at `PLUGIN_BASE/plugins/docker/` → tag `plugins-docker-1.0.0` |
| `[]` | Release repo root (`PLUGIN_BASE` itself) → tag `1.0.0` |
| `[nati, check]` | Release both `nati` and `check` from one line |
| `[*]` | Wildcard — expands to all direct subdirs of `PLUGIN_BASE` |
| `[base/*]` | Wildcard — expands to all subdirs of `PLUGIN_BASE/base/` |

### Slug Logic

Forward slashes in the location are replaced with hyphens to form the tag prefix.

| Location | Slug | Example Tag |
|----------|------|-------------|
| `nati` | `nati` | `nati-v1.1.0` |
| `plugins/docker` | `plugins-docker` | `plugins-docker-v1.0.1` |
| `base/argo` | `base-argo` | `base-argo-v2.0.0` |
| `base/infra/networking/firewall` | `base-infra-networking-firewall` | `base-infra-networking-firewall-v1.0.0` |
| *(empty)* | *(empty)* | `v1.0.0` |

### Core Flow

1. **Message** → parsed by `parse_pr_body(body, parsers)`
2. `cliff.toml` `commit_parsers` patterns are used directly by `_match_line` (inner function) — first-match-wins, same order as cliff.toml
3. A line is a commit line if and only if: a parser pattern matches at position 0 **AND** a `[...]` bracket immediately follows (no gap). Content inside `[]` must not contain `[` or `]`.
4. `[locations]` is stripped from the line; the rest is passed raw to git-cliff. git-cliff's `filter_unconventional = true` handles further validation.
5. If the commit string ends with a bare `:` after bracket removal, continuation lines are collected (raw, no stripping) until the next commit line.
6. Multi-location lines are exploded: `feat(scope)[a, b]: msg` → two entries, one per location
7. Wildcard `[*]` / `[base/*]` locations are expanded via `_expand_locations`
8. `PLUGIN_SCOPE_EXCLUDE_REGEX` is applied to ALL locations — wildcard-expanded and explicit
9. For each surviving location: `git-cliff` is invoked with `--include-path` for isolation and `--with-commit` for the bump message
10. Each component gets its own `CHANGELOG.md` and a versioned tag
11. If `PLUGIN_OUTPUT_TAGS_FILE` is set, each created tag is appended to that file

### Key Functions in `release.py`

| Function | Purpose |
|----------|---------|
| `load_cliff_parsers(toml_path)` | Reads `cliff.toml` → `(parsers, bump_cfg)` — drives type recognition |
| `_known_commit_types(parsers)` | Returns **raw message patterns** from `cliff.toml` as-is (e.g. `{"^feat\\((.*)\)", "^feat", ...}`) — no extraction or transformation |
| `parse_pr_body(body, parsers)` | Parses message lines → `dict[location → set[commit_str]]`; explodes multi-location. Uses `_match_line` inner function with cliff.toml patterns directly. Lines are never stripped. |
| `_expand_locations(location_to_commits, root_path, exclude_regex)` | Expands `[*]`/`[base/*]` wildcards; applies exclude regex |
| `release()` | Main entry point — orchestrates the full pipeline |

### Key Files

| File | Description |
|------|-------------|
| `plugins/master-versions/release.py` | Main orchestrator — reads `PLUGIN_*` env vars directly, no shell wrapper |
| `plugins/master-versions/test_release.py` | Unit tests — uses inline `PARSERS` fixture (mirrors `cliff.toml`), stable regardless of cliff.toml changes |
| `plugins/master-versions/test_release_cliff.py` | Unit tests that load the **real** `cliff.toml` — breaks loudly when cliff.toml changes, good for validating custom configs |
| `plugins/kaniko-master-versions/test_release_docker.sh` | Docker integration tests — runs `netanelzucaim123/master-versions:latest` against a real git repo |
| `plugins/master-versions/cliff.toml` | git-cliff config and source of truth for commit type recognition |
| `plugins/master-versions/README.md` | User-facing documentation |
| `plugins/master-versions/Dockerfile` | Plugin image — build context is repo root |
| `plugins/kaniko-master-versions/plugin.sh` | Reads tags from `PLUGIN_TAGS_FILE`, resolves each to a Dockerfile, builds and pushes via Kaniko |
| `plugins/kaniko-master-versions/README.md` | kaniko-master-versions documentation |
| `.woodpecker/Build.yaml` | CI pipeline |

### Stateless Design Constraints

- `--include-path 'location/**/*'` isolates each component's git history
- `--with-commit` provides the current bump message directly, bypassing git log
- git-cliff only uses git history to find the previous tag for the base version
- Missing directories are skipped gracefully (not fatal)
- If no existing tag for a component → first release uses `PLUGIN_INITIAL_TAG` (default `1.0.0`)

---

## Pipeline Integration

The two plugins run as consecutive steps:

1. **master-versions** — parses the message, calculates versions, writes `CHANGELOG.md` files, appends each created tag to `PLUGIN_OUTPUT_TAGS_FILE` (e.g. `new_tags.txt`)
2. **kaniko-master-versions** — reads `new_tags.txt` via `PLUGIN_TAGS_FILE`, resolves each tag to a Dockerfile on disk, builds and pushes via Kaniko

```
master-versions                       kaniko-master-versions
──────────────────────────────        ──────────────────────────────────────
parse PLUGIN_MESSAGE                  reads new_tags.txt line by line
  → nati-v1.1.0                  ──►  nati-v1.1.0  → slug=nati  → PLUGIN_BASE/nati/Dockerfile
  → plugins-docker-v2.0.0        ──►  plugins-docker-v2.0.0 → PLUGIN_BASE/plugins/docker/Dockerfile
appended to new_tags.txt              builds and pushes each image via Kaniko
```

---

## CI/CD Pipeline (Woodpecker — `.woodpecker/Build.yaml`)

Steps run on every push to `main`:

1. **Fetch PR body** — curl Gitea API, write to `pr_body.txt`
2. **Run release** (`netanelzucaim123/master-versions`) — runs `release.py`, writes created tags to `new_tags.txt` via `PLUGIN_OUTPUT_TAGS_FILE`
3. **Push changelogs to Git** — commits `*/CHANGELOG.md` changes, force-pushes tags
4. **Build and push plugin images** (`netanelzucaim123/kaniko-master-versions`) — reads `new_tags.txt`, builds Docker image per tag via Kaniko

Required secrets: `docker_username`, `docker_password`

---

## MCP Integration

`.claude/.mcp.json` connects to a local Gitea MCP server at `http://localhost:3000` for PR management from within Claude Code sessions.

---

## Automation Hooks

Hooks are configured in `.claude/settings.json` and fire automatically on `PostToolUse` for `Edit|Write`.

### `plugins/master-versions/release.py`

**Automatic (shell hook):** After every edit, the following run automatically:
1. `python3 test_release.py` — unit tests with inline PARSERS fixture
2. `python3 test_release_cliff.py` — tests coupled to the real `cliff.toml`

**Required manually by Claude:** After every edit, also:
3. Update `plugins/master-versions/README.md` to reflect any env var, behaviour, or interface changes.
4. Update `plugins/master-versions/test_release.py` / `test_release_cliff.py` if the change introduces new behaviours or modifies existing ones.

### `plugins/kaniko-master-versions/plugin.sh`

**Automatic (shell hook):** After every edit:
1. `./test_release_docker.sh` — Docker integration tests (timeout 300s)

**Required manually by Claude:** After every edit, also:
2. Update `plugins/kaniko-master-versions/README.md` to reflect any interface changes.
3. Update `plugins/kaniko-master-versions/test_release_docker.sh` if new behaviour needs coverage.

### Error Handling

If any test fails, stop and report the full logs. Do not proceed until all tests pass.

**Note:** `test_release_docker.sh` requires Docker and the home directory to be traversable by the Docker daemon (`chmod o+x /home/netanelzucaim`).
