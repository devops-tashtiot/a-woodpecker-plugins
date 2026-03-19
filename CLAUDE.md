# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Stateless Monorepo Release Orchestrator**. It automates semantic versioning and changelog generation for multiple independent components within a monorepo. The **PR body is the single source of truth** — release decisions are determined solely from PR body content, not from Git history.

## Commands



### Run the release orchestrator
```bash
PR_BODY="feat(nati): add dashboard" PLUGIN_MONOREPO_PATH="." python3 release.py
```

### Run tests
```bash
python test_release.py
```

### Create test PRs in Gitea (for CI validation)
```bash
./create-test-prs.sh
```

## Architecture

### Core Flow

1. **PR body** → parsed by `release.py`
2. Conventional commit lines matching `^([a-z]+)\(([^)]+)\):\s*(.*)` are extracted
3. Multi-scope commits are exploded: `feat(a, b): msg` → `{"feat(a): msg", "feat(b): msg"}`
4. A Python `set` deduplicates entries
5. For each entry, the scope is mapped to a filesystem path and a slug (`base/argo` → `base-argo`)
6. `git-cliff` is invoked per component with `--include-path` for isolation and `--body` for the current bump message
7. Each component gets its own `CHANGELOG.md` and a tag like `base-argo-v1.1.0`

### Slug Logic

| Scope | Path | Slug | Example Tag |
|-------|------|------|-------------|
| `nati` | `nati/` | `nati` | `nati-v1.1.0` |
| `plugins/docker` | `plugins/docker/` | `plugins-docker` | `plugins-docker-v1.0.1` |
| `base/argo` | `base/argo/` | `base-argo` | `base-argo-v2.0.0` |
| `base/infra/networking/firewall` | `base/infra/networking/firewall/` | `base-infra-networking-firewall` | `base-infra-networking-firewall-v1.0.0` |

Forward slashes in scopes are replaced with hyphens to form the tag prefix.

### Key Files

- `release.py` — main orchestrator (Python, not shell)
- `test_release.py` — 17 unit tests covering parsing, slug logic, explosion, edge cases
- `cliff.toml` — global git-cliff config: `feat` → minor bump, breaking → major bump, `initial_tag = "1.0.0"`, `limit_commits_to_path = true`
- `.woodpecker/Build.yaml` — CI pipeline (Woodpecker): clone → fetch PR body from Gitea API → run release → push changelogs
- `.claude/CLAUDE.md` — detailed technical spec with test cases (authoritative for explosion/slug logic)

### Plugins (under `plugins/`)

| Plugin | Purpose |
|--------|---------|
| `changed-files/changed.sh` | Detects modified files in CI via `CI_PIPELINE_FILES` |
| `kaniko-monorepo/plugin.sh` | Builds and pushes Docker images per plugin; reads `VERSION` files for tags |
| `docs2confluence/docs2confluence.sh` | Syncs local markdown docs to Confluence page hierarchy |
| `git-cliff.sh` | Legacy versioning script that reads `changed_folders.txt` as input |

### Stateless Design Constraints

- `--include-path 'scope/**/*'` isolates each component's git history
- `--body` provides the current bump message directly (PR body line), bypassing git log
- git-cliff only uses git history to find the previous tag for the base version
- Missing directories are skipped with an error message (not fatal)

## CI/CD (Woodpecker)

Required secrets: `GITEA_TOKEN`, `GITEA_URL`, `GIT_AUTH_TOKEN`

Commits pushed back by CI use `[skip ci]` to avoid re-triggering the pipeline.

## MCP Integration

`.claude/.mcp.json` connects to a local Gitea MCP server at `http://localhost:3000` for PR management from within Claude Code sessions.
