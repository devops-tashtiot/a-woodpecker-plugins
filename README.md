# MasterVersions — Stateless Monorepo Release Orchestrator

`release.py` automates semantic versioning and changelog generation for any repo structure — polyrepo, monorepo, or nested monorepo. The **PR body is the single source of truth**: what you write in the PR description determines which components get a new version tag and what the bump level is.

---

## How to recognise your repo type

Ask yourself: **how many levels of directories separate the repo root from my service code?**

```
Polyrepo (depth=0)          Monorepo (depth=1)          Nested Monorepo (depth=2)
────────────────────        ───────────────────         ─────────────────────────
my-service/                 repo/                       repo/
  src/                        nati/                       base/
  Dockerfile                  plugins/                      argo/
  ...                         base/                         infra/
                              docs/                       check/
One repo = one service.       ...                           auth/
No scope needed.            One level of folders          plugins/
                            = one level of scope.           docker/
                                                            ...
                                                        Two levels of folders
                                                        = two-level scope.
```

| Repo type | `SCOPE_DEPTH` | PR body scope format |
|-----------|---------------|----------------------|
| Polyrepo | `0` | No scope — `feat: msg` |
| Monorepo | `1` | Single folder — `feat(nati): msg` |
| Nested monorepo | `2` | Two folders — `feat(base/argo): msg` |

---

## Environment variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `PR_BODY` | `""` | Yes | The PR body text containing conventional commit lines |
| `PLUGIN_BASE` | `"."` | Yes | Root directory to scan from. All component paths are relative to this. |
| `SCOPE_DEPTH` | `"1"` | No | Repo structure depth: `0`=polyrepo, `1`=monorepo, `2`=nested |
| `SCOPE_EXCLUDE_REGEX` | `""` | No | Python regex — any scope matching this is skipped (wildcard and explicit) |
| `OUTPUT_TAGS_FILE` | `""` | No | If set, each successfully created tag is appended to this file (used by `kaniko-monorepo-cliff`) |

---

## Depth 0 — Polyrepo

**Use when:** one repository = one service. No subdirectories to distinguish components.

**PR body format:** `type: message` (no scope)

```
feat: add user authentication
fix: resolve memory leak on shutdown
fix!: drop support for Python 3.8
```

**What happens:**
- All commit lines are parsed
- The highest-priority one determines the version bump
- Tag is created at the root level: `v1.0.0`, `v1.1.0`, `v2.0.0`, etc.
- CHANGELOG.md is written at the repo root

**Example:**
```
PR body:
  feat: add login page
  fix: correct typo in error message

Result:
  feat wins (higher priority than fix)
  → tag: v1.1.0  (minor bump from feat)
  → CHANGELOG.md updated
```

---

## Depth 1 — Monorepo

**Use when:** multiple services live as direct subdirectories under `PLUGIN_BASE`.

```
repo/
  nati/         ← component
  plugins/      ← component
  base/         ← component
  docs/         ← NOT a component (exclude with regex)
```

**PR body format:** `type(scope): message`

Scope = the folder name directly under `PLUGIN_BASE`.

```
feat(nati): add dashboard
fix(plugins): resolve timeout
feat(nati, base): update shared config   ← multi-scope, explodes into two releases
feat(*): upgrade all dependencies        ← wildcard, releases ALL subdirs
```

**Example — single scope:**
```
PR body: feat(nati): add dashboard

Result:
  → tag: nati-v1.1.0  (minor bump)
  → nati/CHANGELOG.md updated
```

**Example — multi-scope:**
```
PR body: feat(nati, plugins): shared auth upgrade

Result:
  → tag: nati-v1.1.0
  → tag: plugins-v2.3.0
  → nati/CHANGELOG.md updated
  → plugins/CHANGELOG.md updated
```

**Example — wildcard:**
```
PR body: feat(*): upgrade all dependencies

PLUGIN_BASE contains: nati/, plugins/, base/, docs/

Result (assuming no SCOPE_EXCLUDE_REGEX):
  → nati-v1.1.0
  → plugins-v1.1.0
  → base-v1.1.0
  → docs-v1.1.0   ← you probably don't want this! use SCOPE_EXCLUDE_REGEX
```

---

## Depth 2 — Nested Monorepo

**Use when:** services are grouped under top-level category directories.

```
repo/
  base/
    argo/       ← component (scope: base/argo)
    infra/      ← component (scope: base/infra)
  check/
    auth/       ← component (scope: check/auth)
    plugins/
      docker/   ← component (scope: check/plugins/docker)  ← depth=3, not supported
```

**PR body format:** `type(group/service): message`

Scope = TWO levels: `top-folder/sub-folder`.

```
feat(base/argo): upgrade helm chart
fix(check/auth): resolve token expiry
feat(base/*): upgrade all base components    ← wildcard within a group
```

> ⚠️ `feat(*): msg` is **invalid at depth=2** — you must always specify the group prefix.
> Use `feat(base/*): msg` or `feat(check/*): msg` instead.

**Example — explicit scope:**
```
PR body: feat(base/argo): upgrade helm chart

Result:
  → tag: base-argo-v1.1.0
  → base/argo/CHANGELOG.md updated
```

**Example — group wildcard:**
```
PR body: feat(base/*): major refactor

base/ contains: argo/, infra/

Result:
  → base-argo-v2.0.0
  → base-infra-v1.3.0
  → base/argo/CHANGELOG.md updated
  → base/infra/CHANGELOG.md updated
```

**Example — invalid wildcard:**
```
PR body: feat(*): upgrade everything

SCOPE_DEPTH=2 → ERROR: feat(*) is invalid at SCOPE_DEPTH=2
Use feat(base/*) or feat(check/*) instead.
Nothing is released.
```

---

## Wildcard `*`

The wildcard `*` automatically discovers and releases all components in a group. It respects `SCOPE_EXCLUDE_REGEX` to skip unwanted folders.

| Depth | Wildcard form | What it discovers |
|-------|--------------|-------------------|
| 1 | `feat(*): msg` | All direct subdirs of `PLUGIN_BASE` |
| 2 | `feat(base/*): msg` | All subdirs of `PLUGIN_BASE/base/` |
| 2 | `feat(*): msg` | ❌ Invalid — must specify group prefix |

The `*` **only expands directories that exist on disk** at pipeline time. If you add a new service folder, it's automatically included in the next `feat(*): msg` PR.

---

## SCOPE_EXCLUDE_REGEX

### When to use it

Your repo likely has folders that are **not microservices** — things like `docs/`, `shared/`, `scripts/`, `.github/`. When a developer writes `feat(*): upgrade all`, you don't want version tags created for those folders.

`SCOPE_EXCLUDE_REGEX` is a Python regex applied to every scope — **both wildcard-expanded and explicit**. If a scope matches the regex, it is silently skipped and no tag is created for it.

### Monorepo example — excluding non-service folders

```
repo/
  auth/          ← service ✅
  payments/      ← service ✅
  notifications/ ← service ✅
  docs/          ← NOT a service ❌
  shared/        ← NOT a service ❌
  scripts/       ← NOT a service ❌
```

Set:
```yaml
SCOPE_EXCLUDE_REGEX: "^docs$|^shared$|^scripts$"
```

Now:
```
PR body: feat(*): upgrade all dependencies

Result:
  auth-v1.1.0       ✅
  payments-v1.1.0   ✅
  notifications-v1.1.0 ✅
  docs              ❌ skipped (matches regex)
  shared            ❌ skipped (matches regex)
  scripts           ❌ skipped (matches regex)
```

### Nested monorepo example — excluding an infra group

```yaml
SCOPE_EXCLUDE_REGEX: "^base/infra"
```

```
PR body: feat(base/*): upgrade base components

base/ contains: argo/, infra/, auth/

Result:
  base-argo-v1.1.0   ✅
  base-auth-v1.1.0   ✅
  base/infra          ❌ skipped (matches ^base/infra)
```

### Explicit scope is also filtered

The regex applies even when the scope is written directly — not just during `*` expansion:

```yaml
SCOPE_EXCLUDE_REGEX: "^docs$"
```

```
PR body: feat(docs): update API reference

Result:
  >>> SKIP: scope 'docs' excluded by SCOPE_EXCLUDE_REGEX
  Nothing is released.
```

---

## Breaking changes and priority deduplication

### Bump priority

When the same PR body contains multiple commit lines for the **same scope**, only the **highest-priority** one is processed:

| Type | Priority | Bump |
|------|----------|------|
| `breaking(...)` or `feat(...)!` | 3 | Major |
| `feat(...)` | 2 | Minor |
| `fix(...)`, `chore(...)`, others | 1 | Patch |

### Mixed message example — `breaking(*) + feat(nati)`

```
PR body:
  breaking(*): remove deprecated API endpoints
  feat(nati): add new dashboard page
```

**Step-by-step:**

1. `breaking(*)` expands to all subdirs: `breaking(nati)`, `breaking(auth)`, `breaking(payments)`
2. `feat(nati)` is explicit for nati
3. **Deduplication on nati:**
   - `breaking(nati)` has priority 3
   - `feat(nati)` has priority 2
   - → `breaking(nati)` wins
4. Final work:
   - `nati` → **major bump** (breaking wins, not feat)
   - `auth` → **major bump** (breaking)
   - `payments` → **major bump** (breaking)

```
Result:
  nati-v2.0.0       ← breaking wins over feat
  auth-v2.0.0
  payments-v2.0.0
```

### Complex example — nested monorepo with mixed types and exclude

```yaml
PLUGIN_BASE: "."
SCOPE_DEPTH: "2"
SCOPE_EXCLUDE_REGEX: "^base/legacy"
```

```
PR body:
  feat(base/*): upgrade all base services
  fix(check/auth): patch token refresh bug
  feat(base/legacy)!: breaking refactor    ← explicitly excluded by regex
```

**Processing:**

1. `feat(base/*)` expands → `feat(base/argo)`, `feat(base/infra)`, `feat(base/legacy)` → `base/legacy` excluded by regex → keeps `feat(base/argo)` and `feat(base/infra)`
2. `fix(check/auth)` — explicit, no match → kept
3. `feat(base/legacy)!` — scope `base/legacy` matches regex → **skipped**
4. No deduplication needed (all scopes are distinct)

```
Result:
  base-argo-v1.1.0    ← minor bump from feat
  base-infra-v1.1.0   ← minor bump from feat
  check-auth-v1.0.1   ← patch bump from fix
  base/legacy         ← skipped (SCOPE_EXCLUDE_REGEX)
```

---

## Running locally

```bash
# Standard run
PR_BODY="feat(nati): add dashboard" PLUGIN_BASE="." python3 release.py

# Polyrepo
PR_BODY="feat: new feature" PLUGIN_BASE="." SCOPE_DEPTH=0 python3 release.py

# Wildcard with exclusion
PR_BODY="feat(*): upgrade all" PLUGIN_BASE="." SCOPE_DEPTH=1 \
  SCOPE_EXCLUDE_REGEX="^docs$|^shared$" python3 release.py

# Nested monorepo, group wildcard
PR_BODY="feat(base/*): refactor base" PLUGIN_BASE="." SCOPE_DEPTH=2 python3 release.py

# Capture created tags for downstream steps (e.g. kaniko-monorepo-cliff)
PR_BODY="feat(nati): upgrade" PLUGIN_BASE="." OUTPUT_TAGS_FILE="new_tags.txt" python3 release.py
```

## Running tests

```bash
python3 test_release.py
```
