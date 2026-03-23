# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Stateless Monorepo Release Orchestrator** (`release.py`). It automates semantic versioning and changelog generation for polyrepo, monorepo, and nested monorepo structures. The **PR body is the single source of truth** — release decisions are determined solely from PR body content, not from Git history.

---

## Commands

### Run the release orchestrator
```bash
PR_BODY="feat(nati): add dashboard" PLUGIN_BASE="." python3 release.py
```

### Run with depth and exclusions
```bash
# Polyrepo (no scope)
PR_BODY="feat: new feature" PLUGIN_BASE="." SCOPE_DEPTH=0 python3 release.py

# Monorepo wildcard with exclusion
PR_BODY="feat(*): upgrade all" PLUGIN_BASE="." SCOPE_DEPTH=1 \
  SCOPE_EXCLUDE_REGEX="^docs$|^shared$" python3 release.py

# Nested monorepo group wildcard
PR_BODY="feat(base/*): refactor base" PLUGIN_BASE="." SCOPE_DEPTH=2 python3 release.py
```

### Run unit tests
```bash
python3 test_release.py
```

### Run Docker integration tests
```bash
./test_release_docker.sh
```

### Create test PRs in Gitea (for CI validation)
```bash
./create-test-prs.sh
```

---

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PR_BODY` | `""` | Yes | PR body text containing conventional commit lines |
| `PLUGIN_BASE` | `"."` | Yes | Root directory to scan from. All component paths are relative to this. |
| `SCOPE_DEPTH` | `"1"` | No | Repo structure depth: `0`=polyrepo, `1`=monorepo, `2`=nested monorepo |
| `SCOPE_EXCLUDE_REGEX` | `""` | No | Python regex — any scope matching this is skipped (wildcard and explicit) |
| `OUTPUT_TAGS_FILE` | `""` | No | If set, each successfully created tag is appended to this file (used by `kaniko-monorepo-cliff`) |

---

## Architecture

### SCOPE_DEPTH — Repo Type

| `SCOPE_DEPTH` | Repo type | PR body format | Tag format |
|---|---|---|---|
| `0` | Polyrepo | `feat: msg` (no scope) | `v1.0.0` |
| `1` | Monorepo | `feat(nati): msg` | `nati-v1.1.0` |
| `2` | Nested monorepo | `feat(base/argo): msg` | `base-argo-v1.1.0` |

### Core Flow

1. **PR body** → parsed by `release.py`
2. **depth=0**: scopeless pattern `^([a-z]+)(!?):\s*(.*)` → picks single highest-priority line
3. **depth=1/2**: scoped pattern `^([a-z]+)\(([^)]+)\)(!?):\s*(.*)` is extracted
4. Multi-scope commits are exploded: `feat(a, b): msg` → `{"feat(a): msg", "feat(b): msg"}`
5. `cliff.toml` `commit_parsers` are loaded — commits matching `skip = true` parsers are filtered out (e.g. `chore`, `docs`, `ci` with the default config)
6. Wildcard `*` scopes are expanded via filesystem discovery (`discover_scopes`)
7. `SCOPE_EXCLUDE_REGEX` is applied to ALL scopes — both wildcard-expanded and explicit
8. Per-scope deduplication: if same scope appears multiple times, highest bump priority wins — priority is driven by `cliff.toml` commit_parsers (`breaking`/`!` = 3 > `feat` = 2 > `fix`/others = 1 > skip = filtered)
9. For each surviving scope: `git-cliff` is invoked with `--include-path` for isolation and `--with-commit` for the current bump message
10. Each component gets its own `CHANGELOG.md` and a versioned tag
11. If `OUTPUT_TAGS_FILE` is set, each created tag is appended to that file

### Wildcard Rules

| Depth | Valid wildcard | Meaning |
|-------|---------------|---------|
| 1 | `feat(*): msg` | All direct subdirs of `PLUGIN_BASE` |
| 2 | `feat(base/*): msg` | All subdirs of `PLUGIN_BASE/base/` |
| 2 | `feat(*): msg` | **INVALID** — logs warning, skipped |

### Slug Logic

Forward slashes in scopes are replaced with hyphens to form the tag prefix.

| Scope | Slug | Example Tag |
|-------|------|-------------|
| `nati` | `nati` | `nati-v1.1.0` |
| `plugins/docker` | `plugins-docker` | `plugins-docker-v1.0.1` |
| `base/argo` | `base-argo` | `base-argo-v2.0.0` |
| `base/infra/networking/firewall` | `base-infra-networking-firewall` | `base-infra-networking-firewall-v1.0.0` |

### Key Functions in `release.py`

| Function | Purpose |
|----------|---------|
| `parse_pr_body(body)` | Parses scoped commits for depth=1/2; explodes multi-scope |
| `parse_pr_body_polyrepo(body)` | Parses scopeless commits for depth=0 |
| `discover_scopes(root, depth, parent_prefix)` | Finds component dirs via `os.listdir` |
| `expand_wildcard(messages, root, depth, exclude_regex)` | Replaces `*` scopes; filters via exclude regex |
| `load_cliff_parsers(toml_path)` | Reads `cliff.toml` and returns `(parsers, bump_cfg)` — drives type recognition and priority |
| `_bump_priority(msg, parsers, bump_cfg)` | Returns 3/2/1/0 driven by cliff.toml commit_parsers; falls back to hardcoded when called without parsers |
| `deduplicate_by_scope(messages, parsers, bump_cfg)` | Keeps highest-priority message per scope |
| `release()` | Main entry point — orchestrates the full pipeline |

### Key Files

| File | Description |
|------|-------------|
| `release.py` | Main orchestrator (~350 lines, single file by design) |
| `test_release.py` | **106** unit tests across 7 classes (`TestParsePrBody`, `TestParsePrBodyPolyrepo`, `TestBumpPriority`, `TestDeduplicateByScope`, `TestDiscoverScopes`, `TestExpandWildcard`, `TestRelease`) |
| `test_release_docker.sh` | **114** Docker integration tests across 8 sections (depth=0/1/1b/2, wildcard, exclude, dedup, OUTPUT_TAGS_FILE) |
| `cliff.toml` | git-cliff config and **source of truth for commit type recognition**: `commit_parsers` defines which types trigger releases and at what bump level; `skip = true` entries are filtered before any processing |
| `README.md` | User-facing documentation for all depths, wildcards, exclude regex, and examples |
| `.woodpecker/Build.yaml` | CI pipeline: clone → fetch PR body → run release → push changelogs → build Docker images |
| `plugins/kaniko-monorepo-cliff/` | Woodpecker plugin that reads `OUTPUT_TAGS_FILE` and builds/pushes Docker images via Kaniko |

### Plugins (under `plugins/`)

| Plugin | Purpose |
|--------|---------|
| `kaniko-monorepo-cliff/` | Reads tags from `OUTPUT_TAGS_FILE`, resolves each to a `Dockerfile` by reversing the slug, builds and pushes via Kaniko. Final step in the CI pipeline. |
| `changed-files/changed.sh` | Detects modified files in CI via `CI_PIPELINE_FILES` |
| `kaniko-monorepo/plugin.sh` | Older Kaniko plugin; reads `VERSION` files for tags |
| `docs2confluence/docs2confluence.sh` | Syncs local markdown docs to Confluence page hierarchy |

### Stateless Design Constraints

- `--include-path 'scope/**/*'` isolates each component's git history
- `--with-commit` provides the current bump message directly (PR body line), bypassing git log
- git-cliff only uses git history to find the previous tag for the base version
- Missing directories are skipped gracefully (not fatal)
- If no existing tag for a component → first release is always `slug-v1.0.0`

---

## CI/CD Pipeline (Woodpecker — `.woodpecker/Build.yaml`)

Steps run on every push to `main`:

1. **Fetch PR body** — curl Gitea API, write to `pr_body.txt`
2. **Run release** (`netanelzucaim123/python-git-cliff`) — runs `release.py`, writes created tags to `new_tags.txt` via `OUTPUT_TAGS_FILE`
3. **Push changelogs to Git** — commits `*/CHANGELOG.md` changes, force-pushes tags
4. **Build and push plugin images** (`netanelzucaim123/kaniko-monorepo-cliff`) — reads `new_tags.txt`, builds Docker image per tag via Kaniko

Required secrets: `docker_username`, `docker_password`
Environment constants: `GITEA_TOKEN`, `GITEA_URL`, `PLUGIN_REGISTRY`, `PLUGIN_REPO`

---

## MCP Integration

`.claude/.mcp.json` connects to a local Gitea MCP server at `http://localhost:3000` for PR management from within Claude Code sessions.

---

## Automation Hooks

- **Trigger:** Any edit to `release.py`.
- **Required Actions:** Immediately after saving changes to `release.py`, you MUST execute the following in order:
  1. `python3 test_release.py` — must show `Ran 106 tests ... OK`
  2. `./test_release_docker.sh` — must show `Results: 114 passed, 0 failed`
- **Error Handling:** If either test fails, stop and report the logs. Do not proceed until tests pass.
- **Note:** `test_release_docker.sh` requires Docker and the home directory to be traversable by the Docker daemon (`chmod o+x /home/netanelzucaim`).


