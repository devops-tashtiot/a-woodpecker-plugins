# Bugs and fixes — design history

Real bugs found and fixed in `master-versions`, each written up in full: what broke, why,
every alternative considered (and why it was rejected), the fix that shipped, and what changed.
Combines the former `INCIDENT_PULL_REQUEST_CLOSED_TRAP.md`, `HOTFIX_TAG_RESOLUTION.md`, and
`BUMP_SUBJECT_RESOLUTION.md` into one file.

## Contents

1. [The `pull_request_closed` trap — wrong event triggered releases on declined/deleted PRs](#1-the-pull_request_closed-trap--wrong-event-triggered-releases-on-declineddeleted-prs)
2. [Branch-correct tag resolution — hotfix builds resolved against the wrong tag](#2-branch-correct-tag-resolution--hotfix-builds-resolved-against-the-wrong-tag)
3. [Bump-subject resolution — multiline commits silently downgraded to a patch bump](#3-bump-subject-resolution--multiline-commits-silently-downgraded-to-a-patch-bump)
4. [Persisted auth header — a partial clone's implicit lazy-fetch during the PR target-branch checkout needs credentials too](#4-persisted-auth-header--a-partial-clones-implicit-lazy-fetch-during-the-pr-target-branch-checkout-needs-credentials-too)
5. [Known limitation (unfixed) — a component path containing its own X.Y.Z-shaped segment silently caps every bump at patch](#5-known-limitation-unfixed--a-component-path-containing-its-own-xyz-shaped-segment-silently-caps-every-bump-at-patch)

---

## 1. The `pull_request_closed` trap — wrong event triggered releases on declined/deleted PRs

### The problem

The CI pipeline ran full validation and changelog generation on every pull request lifecycle
event — merge, decline, delete — and attempted to push to `master` on all of them. Only a merge
was supposed to produce a changelog. Declined and deleted PRs were waste at best, and at worst
corrupted the changelog with stale data.

The cause was a single line in the old pipeline config:

```yaml
when:
  - target: master
    event: [pull_request, pull_request_closed]
```

### How it played out

In Woodpecker, `pull_request` fires when a PR is opened or updated. `pull_request_closed` fires
when a PR is closed — but "closed" covers three scenarios:

| Scenario | What happened | Should the pipeline push changelogs? |
|---|---|---|
| PR merged | The PR was merged into `master` | Yes |
| PR declined | The PR was declined (Bitbucket-specific — declined, not merged) | No |
| PR deleted | The PR was closed without merging | No |

With `event: [pull_request, pull_request_closed]`, all of these hit the pipeline, and the git
push step was gated with `when: - event: pull_request_closed` to only run on close — but since
`pull_request_closed` also fires on decline and delete, the pipeline attempted to push changelogs
for PRs that never merged.

**Two classes of damage:**

- **Waste and tag pollution.** On declined and deleted PRs, the pipeline fetched the PR
  description, ran `master-versions`, generated changelogs, created new version tags, and pushed
  both. Beyond burning CI resources, this left stale tags for versions that never shipped sitting
  alongside legitimate release tags — scanning tags to find the latest release would surface
  features that were rejected.
- **Noise.** Even when the push didn't go through (e.g. a declined PR's stale description failed
  a compare step), the run showed up in the CI dashboard as a successful validation run for a
  dead PR, making it harder to track which runs were meaningful.

### The fix

Separated concerns into two pipelines, replacing the broad `pull_request_closed` trigger with
specific, correct triggers:

**`pull_request.yaml`** — validation only, no push:

```yaml
when:
  - event: pull_request
    evaluate: 'CI_COMMIT_TARGET_BRANCH == "master"'
```

No `pull_request_closed`, no git push step at all — this pipeline's sole job is validating that
the PR description matches the changed files. A declined or deleted PR can still trigger a
`pull_request` update before it closes, which is fine — the pipeline runs validation and stops.

**`publish_version.yaml`** — changelog generation and push, only on confirmed merges:

```yaml
when:
  - event: push
    branch: master
    evaluate: 'CI_COMMIT_MESSAGE contains "Merge pull request"'
  - event: manual
    branch: ["feat/*", "hotfix/*", "bugfix/*", "fix/*"]
```

`event: push` on `master`, guarded by the commit message containing "Merge pull request" — the
merge commit Bitbucket creates when a PR is merged. It only fires on an actual merge: declined
PRs don't push to `master`, deleted PRs don't push to `master`, so this trigger never fires for
either. The `manual` trigger on feature branches covers releases that don't go through a PR to
`master` at all (this is the same shape `publish.yml`'s `event: manual` still uses today).

| Scenario | Old pipeline | New pipeline |
|---|---|---|
| PR opened/updated | Validation runs | Validation runs |
| PR merged | Validation + push (correct) | Push on master (correct, via separate pipeline) |
| PR declined | Validation + attempt to push (wrong) | No push — no push event on master |
| PR deleted | Validation + attempt to push (wrong) | No push — no push event on master |

### Why `push` + message evaluation is better than `pull_request_closed`

- **Semantically correct.** A push to `master` containing "Merge pull request" *is* the merge
  commit — no ambiguity about whether the PR was merged, declined, or deleted.
- **Not tied to pull request semantics.** The pipeline doesn't need to know about PRs at all; it
  just sees a commit on `master` and processes it.
- **Cleanly splits validation from publish.** One pipeline validates, the other publishes. Each
  does one thing.

### The custom merge commit message

The `evaluate: 'CI_COMMIT_MESSAGE contains "Merge pull request"'` guard only works because
Bitbucket is configured with a custom PR merge commit message template — the default message is
just `Merge pull request #123 from feature-branch`, which gives no way to extract the PR body
after the merge. The template used (see README §7A for the exact current version and setup
steps):

```
Merge pull request #${id} from ${fromRefName}

METADATA
Title: ${title}
Target: ${toRepoSlug} (${toRefName})
Source: ${fromRepoSlug} (${fromRefName})

DESCRIPTION
${description}
```

Max commit summaries was also set to `0`, so squashed/merged source-branch commit summaries don't
bloat the merge commit message. This template serves two purposes: the first line always starting
with `Merge pull request` is what the `evaluate:` guard checks (a direct push to `master` won't
match it, so the pipeline won't fire on it), and the `DESCRIPTION` section carries the PR body
through to `git log -1 --pretty=%B` on the push event, where `_retrieve_push_message()` in
`release.py` extracts it (see `DETAILEDREADME.md` §6 for exactly how that extraction works, and
its own edge case).

### Takeaways

- `pull_request_closed` does not mean "merged" — it means the PR is closed, which could be a
  decline, a delete, or a merge. For "on merge," use a `push` event on the target branch instead.
- Add a message-level guard: evaluating `CI_COMMIT_MESSAGE contains "Merge pull request"` ensures
  the push is actually a merge commit, not a direct push to the branch.
- Separate validation and publish pipelines. A validation pipeline should never have the ability
  to push — this eliminates the entire class of "pushed when it shouldn't have" bugs.

---

## 2. Branch-correct tag resolution — hotfix builds resolved against the wrong tag

### The problem

`release.py` found "the latest tag" for a component with:

```python
git tag -l '{tag_glob}' --sort=-version:refname
```

This picks the **globally highest semver tag** matching the component's glob (e.g.
`nati-v[0-9]*`), with zero regard for git ancestry or which branch is actually being built.
git-cliff's own `--bump --bumped-version` call did the exact same thing independently: it scans
every local tag ref matching `--tag-pattern` and takes the max.

That breaks the moment a component has more than one active line of history. Concretely: a
component has `nati-v1.0.0` and `nati-v2.0.0` on `master`. A hotfix branch is cut from
`nati-v1.0.0` to fix a bug found in that release. The fix should be tagged `nati-v1.0.1`. Instead,
both the script and git-cliff resolve against `nati-v2.0.0` — the highest tag *anywhere in the
repo* — and produce `nati-v2.0.1`, a version that has nothing to do with the branch actually
being released.

### Solutions considered, and why each was rejected

**1. Ancestry-aware lookup: `git describe` + git-cliff's `--use-branch-tags`.**
`git describe --tags --abbrev=0 --match '<glob>' <ref>` correctly walks commit ancestry and finds
the nearest tag reachable from a given ref — verified directly, giving `1.0.0` on the hotfix
branch and `2.0.0` on `master`, as expected. git-cliff has a matching flag, `--use-branch-tags`
("include only the tags that belong to the current branch"), which made its own internal bump
search ancestry-aware too.

Rejected at the time for two reasons, both confirmed empirically — **though both were later
resolved and no longer block this approach (see the note at the end of this section):**
- *Cost.* Ancestry-aware resolution needs real commit history. A shallow (`depth: 1`) clone
  severs the parent link at the fetch boundary — `git describe` failed outright ("no tags can
  describe...") even with every tag ref present locally, because the shallow boundary marks the
  checked-out commit as having no parents at all. Fixing that seemed to require either a full
  `depth: 0` clone (a real, recurring cost on every pipeline run) or a bounded
  `--deepen`/`--unshallow` retry loop (extra moving parts).
- `--use-branch-tags` can't be redirected — it only looks at whatever is *actually checked out*
  (`HEAD`). For a PR build, the commit under test is the PR's own branch, not the target/base
  branch ancestry should be checked against.

**2. Narrow the tag pattern itself** (e.g. `^nati-v1\.0\.[0-9]+$` instead of the full unrestricted
glob). Cheap, no ancestry needed. **Rejected — breaks `breaking` commits.** git-cliff validates
that the *computed next version* also matches `--tag-pattern`. A commit crossing the narrowed
pattern's boundary (e.g. `1.0.0 → 2.0.0`) fails outright with a git-cliff pattern-mismatch error,
regardless of how the narrowed pattern was derived. This affects the entire family of "shrink the
regex" approaches: the same pattern is used both to *find* the base tag and to *validate* the
result, and those two jobs need different amounts of permissiveness.

**3. Blanket `--tags` fetch, then temporarily delete/restore the "wrong" tag** around the
git-cliff calls. **Rejected as unnecessary complexity** once approach 4 showed the same result
without ever fetching the wrong tag in the first place.

**4. Selectively fetch only "reachable" tags** via `git ls-remote` + `git cat-file -e` (ask the
remote for tag→SHA pairs, then locally check which commits are already present from a targeted
branch fetch). Worked in testing, but **set aside for the extra `ls-remote` network round-trip and
bespoke reconciliation logic** — which led to re-examining whether git already does this same
check natively.

**5. `git rev-list --tags --max-count=1`** (find the most recently-*committed* tagged commit).
**Rejected — answers a different question and isn't reliably scoped.** Considers every tag in the
repo, not just the current branch's ancestry; picked a commit from a completely unrelated line of
history simply because it had the latest commit timestamp, repo-wide. Even after scoping to one
component's tags, it still failed when a tag sat directly on the commit being described —
`rev-list` picked an older, unrelated tag instead, because it orders by commit date, not graph
distance. `git describe` doesn't have this failure mode; it only looks at parent/child edges.

### The solution that shipped

Two things, working together:

**Resolve which branch's tags to trust, per run** (`CI_PIPELINE_EVENT`, `CI_COMMIT_BRANCH`,
`CI_COMMIT_TARGET_BRANCH` — all read automatically, never user-set):
- Pull-request event → the **target** branch (`CI_COMMIT_TARGET_BRANCH`) — "what would this look
  like once merged." `CI_COMMIT_BRANCH` equals the target branch for PR events, *not* the PR's
  own source branch, so the target must be read explicitly.
- Otherwise (direct push, manual trigger) → `CI_COMMIT_BRANCH` itself — the actual hotfix-branch
  case.
- Falls back to `HEAD` if neither is set (e.g. a bare local run outside Woodpecker).

**Fetch that branch into an explicit ref, with no `--tags`/`--no-tags` flag on the fetch itself,**
and let git's built-in tag auto-follow decide which tags attach:

```python
run_command("git config --unset-all remote.origin.tagOpt")
...
run_command(f"git fetch origin {resolve_branch}:refs/remotes/origin/{resolve_branch}")
```

Git's auto-follow rule: a tag attaches **only if** the commit it points to is already present
locally as a *result of this fetch*. It never reaches for a commit just because a tag happens to
be named after it — unlike `--tags` (fetch every tag, downloading whatever's needed) or
`--no-tags` (fetch none, even for commits already present). A tag from an unrelated branch can
therefore never attach, with no custom filtering code at all.

Two details that took real testing, not just reasoning:
- **The clone step's own `tags:` setting can silently defeat this.** `plugin-git` runs
  `git fetch --tags`/`--no-tags` as part of the clone itself — confirmed by reading its source.
  With `tags: true` on the clone, every tag lands before `release.py` ever runs, and nothing
  downstream removes an already-present tag. `release.py` resets `remote.origin.tagOpt`
  defensively at startup for this reason, since `tags: false` persists as `--no-tags` on the
  remote and would otherwise also block the script's own later fetch.
- **Having the commit data locally isn't enough — the fetch has to actually happen.** A full
  (`depth: 0`) clone alone doesn't trigger auto-follow for a branch already checked out; a plain
  re-fetch of a branch git already tracks is a no-op that skips auto-follow entirely, even though
  the commit data was already present. Fetching into an **explicit**
  `refs/remotes/origin/<branch>` destination forces a real negotiation, which correctly triggers
  auto-follow whether the branch is brand-new (the PR/target case) or already checked out (the
  direct-branch case) — both are unified into the same fetch call.

**Update — the shallow-clone cost objection to approach 1 no longer applies.** `release.py` now
detects a shallow workspace itself (`git rev-parse --is-shallow-repository`) and folds
`--unshallow` into this same fetch when needed, self-healing *any* clone depth or `partial`
setting before tag resolution runs — see `DETAILEDREADME.md` §5, verified directly against a real
`--depth=1 --filter=tree:0` clone. So `depth: 0` is kept now as a deliberate but no-longer-*required*
choice (it avoids a second network round-trip), not because a shallow clone would otherwise
break anything.

### Why `breaking` commits still work correctly

Every rejected pattern-narrowing approach broke on major-version-crossing commits because it
restricted `--tag-pattern` by version number. The shipped solution never touches `--tag-pattern`
at all — it stays the original, fully unrestricted regex
(`^nati-v[0-9]+\.[0-9]+\.[0-9]+$`) in both the bump call and the changelog call. The only thing
being controlled is **which tag refs physically exist on disk**, orthogonal to what the regex
will accept — so a `breaking` commit crossing from `1.0.0` to `2.0.0` still validates fine.

### Examples — what actually gets generated

All assume the same starting state: component `nati` has `nati-v1.0.0` tagged on `master`,
`master` later moved on and was also tagged `nati-v2.0.0`, and a `hotfix` branch was cut from the
`nati-v1.0.0` commit — so `hotfix` and `nati-v2.0.0` share no history.

**Example 1 — direct/manual build of the hotfix branch (patch fix)**
```
CI_COMMIT_BRANCH=hotfix
PLUGIN_MESSAGE: fix[nati]: patch bug found in 1.0.0
```
`resolve_branch` = `hotfix` → only `nati-v1.0.0` is fetched → `git describe` → `nati-v1.0.0` →
patch bump → **`nati-v1.0.1`**.

**Example 2 — same hotfix branch, opened as a pull request into `master`**
```
CI_PIPELINE_EVENT=pull_request
CI_COMMIT_TARGET_BRANCH=master
PLUGIN_MESSAGE: feat[nati]: small addition
```
`resolve_branch` = `master` → both `nati-v1.0.0` and `nati-v2.0.0` fetched (both are genuinely
part of `master`'s history) → `git describe` → `nati-v2.0.0` → minor bump → **`nati-v2.1.0`**.

**Example 3 — breaking change committed on the hotfix branch**
```
CI_COMMIT_BRANCH=hotfix
PLUGIN_MESSAGE: breaking[nati]: major change
```
`resolve_branch` = `hotfix` → only `nati-v1.0.0` fetched → major bump (crosses the version
boundary — `--tag-pattern` was never narrowed) → **`nati-v2.0.0`**.

**Example 4 — what the old (`git tag -l --sort`) logic would have produced for the same three
cases**

| Case | Old result | New result |
|---|---|---|
| Hotfix fix commit | `nati-v2.0.1` (wrong — bumped from master's tag) | `nati-v1.0.1` |
| PR feature commit into master | `nati-v2.1.0` (right, but only by coincidence) | `nati-v2.1.0` |
| Hotfix breaking commit | `nati-v3.0.0` (wrong — major-bumped from master's `2.0.0`) | `nati-v2.0.0` |

### Files changed

| File | Change |
|---|---|
| `plugins/master-versions/release.py` | Reset `remote.origin.tagOpt`; resolve `CI_PIPELINE_EVENT`/`CI_COMMIT_BRANCH`/`CI_COMMIT_TARGET_BRANCH` into a branch to trust; fetch it into `refs/remotes/origin/<branch>`; tag lookup switched from `git tag -l --sort=-version:refname` to `git describe --tags --abbrev=0 --match '<glob>' <resolved_ref>`. |
| `.woodpecker/*.yml` | Clone settings: `tags: true` → `tags: false`, `depth` → `0` (later found to be non-load-bearing — see the "Update" note above and `DETAILEDREADME.md` §5). |
| `plugins/master-versions/tests/test_release.py` | New `TestBranchResolution` (mocked) covering PR/non-PR branch selection and the `tagOpt` reset; new `TestHotfixBranchTagResolution` (real git + real git-cliff) reproducing the hotfix, PR, and breaking-commit scenarios end-to-end. |

---

## 3. Bump-subject resolution — multiline commits silently downgraded to a patch bump

### The problem

`release.py` calls git-cliff twice per component: once to compute the next version (`--bump
--bumped-version`), once to render the changelog (full commit text, via `--tag`). The bump call
is deliberately given only the **subject line** of each commit, not the full multi-line string —
working around a real upstream git-cliff bug, tracked at
[orhun/git-cliff#1476](https://github.com/orhun/git-cliff/issues/1476) ("`custom_major/minor_increment_regex`
ignored for multiline commits when `conventional_commits = false`"). With this repo's `cliff.toml`
(`conventional_commits = false`), git-cliff applies `custom_major_increment_regex` against what
it thinks is the commit subject — and its own subject/body split is unreliable for a multi-line
string not separated by a blank line, which is exactly how continuation lines in a PR body get
joined. Confirmed directly:

```
git-cliff --with-commit "breaking: major change\nFull description here.\nSecond line of body."
  → nati-v2.0.1   ✗ silently treated as a patch, "breaking" ignored entirely

git-cliff --with-commit "breaking: major change"   (subject only)
  → nati-v3.0.0   ✓ correct — major bump
```

Truncating to the subject line correctly works around that.

### The new problem this surfaces

A PR body can also be written with the type/location on its own line and the actual description
entirely on the *next* line:

```
feat[nati]:
natiii
```

After `[location]` stripping and continuation-joining, the resulting commit string is
`"feat:\nnatiii"` — a **bare** `"feat:"` on line one, with the real text on line two. Blindly
truncating to `splitlines()[0]` here sends git-cliff just `"feat:"` — a type with *no* description
at all — which independently also falls back to a patch bump, even though `natiii` (the real
description) was never even seen:

```
git-cliff --with-commit "feat:\nnatiii"   (full, untruncated)
  → nati-v2.1.0   ✓ correct — git-cliff handles this case fine on its own

git-cliff --with-commit "feat:"           (what plain splitlines()[0] sends)
  → nati-v2.0.1   ✗ wrong — patch, because there's no description left to recognize
```

So the two failure modes need **opposite** handling: a subject that already has real text after
the colon must have any extra lines *dropped* (the original fix); a subject that's bare must have
the next line *folded in* (not dropped) — otherwise there'd be nothing left for git-cliff to
correctly identify as `feat`.

### The fix

A small helper, `_bump_subject(commit)`, replaces the plain `c.splitlines()[0]` truncation used
only for the bump call (the changelog call is unaffected — it always gets the full, untouched
multi-line string):

```python
def _bump_subject(commit):
    lines = commit.splitlines()
    subject = lines[0]
    if re.search(r':\s*$', subject):
        for line in lines[1:]:
            if line.strip():
                return f"{subject} {line.strip()}"
    return subject
```

- If the first line has real content after the colon (`re.search(r':\s*$', subject)` is `False`)
  → returned unchanged, extra lines dropped. Matches the original fix for
  [orhun/git-cliff#1476](https://github.com/orhun/git-cliff/issues/1476).
- If the first line is bare (`type:` or `type!:` with nothing else) → the first non-blank
  continuation line is folded in, synthesizing a normal `"type: description"` subject for the
  bump call only.

### Examples

| PR body (after `[location]` stripping) | `_bump_subject(...)` result | Bump |
|---|---|---|
| `feat: add login` | `feat: add login` (unchanged) | minor |
| `feat: real subject`\n`Second line of body.` | `feat: real subject` (body dropped) | minor |
| `feat:`\n`natiii` | `feat: natiii` (folded in) | minor |
| `breaking:`\n\n\n`major change` | `breaking: major change` (blank lines skipped over) | major |
| `feat:` (nothing at all, anywhere) | `feat:` (nothing to fold in) | — |

### Files changed

| File | Change |
|---|---|
| `plugins/master-versions/release.py` | Added `_bump_subject(commit)` helper; `bump_commit_args` now uses it instead of a bare `c.splitlines()[0]`. |
| `plugins/master-versions/tests/test_release.py` | New `TestBumpSubject` (unit tests for the helper directly) and a new end-to-end case in `TestHotfixBranchTagResolution` reproducing the `feat[nati]:` + next-line-description scenario against real git-cliff. |

### Reference

Upstream bug this whole subject/body split behavior stems from:
[orhun/git-cliff#1476](https://github.com/orhun/git-cliff/issues/1476) — "`custom_major/minor_increment_regex`
ignored for multiline commits when `conventional_commits = false`." The reporter describes the
exact same root cause and the same "split into two git-cliff invocations" workaround this
codebase already uses.

---

## 4. Persisted auth header — a partial clone's implicit lazy-fetch during the PR target-branch checkout needs credentials too

### The problem

A `pull_request` build failed with:

```
>>> ERROR: could not check out target branch 'main' (fatal: could not read Username for
'https://bitbucket.devopstashtiot.page': terminal prompts disabled) — refusing to compute
versions against the wrong branch.
```

### The cause

`plugin-git`'s default clone is a `tree:0` partial clone — blob/tree objects beyond the checked-out
commit are deferred, fetched lazily by git itself only when something actually needs them (see
`DETAILEDREADME.md` §5). For a PR build, only the PR's own source branch is materialized locally.

`release.py` authenticates its *own* fetches against Bitbucket with a `PLUGIN_BITBUCKET_TOKEN`
Bearer header — but it did so as a one-shot `-c http.extraHeader=...` flag passed to each
individual `run_command()` call, e.g.:

```python
auth_opt = f'-c http.extraHeader="Authorization: Bearer {token}" ' if token else ""
run_command(f"git {auth_opt}fetch ...")
```

A `-c` flag scopes to that single git process only — it is never written to `.git/config`. So when
the PR-build path later does `git checkout --detach refs/remotes/origin/<target_branch>` (needed so
git-cliff's `--use-branch-tags` resolves against the target branch's own history, not the PR
branch's — see §2 above), and the target branch's tip commit needs blob/tree objects this partial
clone never fetched, git issues its *own* internal lazy-fetch to pull them in. That internal fetch
is a separate git process from anything `release.py` invoked directly, so it never saw the `-c`
flag — it goes out with no credentials at all, Bitbucket returns 401, and git reports it exactly as
`fatal: could not read Username for '<url>': terminal prompts disabled`.

This is a real gap the shallow-clone self-heal (§5 in `DETAILEDREADME.md`) doesn't cover: that fix
restores commit *ancestry* (`--unshallow`, for `git describe`, which never touches blob/tree
content), but does nothing about a `tree:0` filter's missing *blob/tree* content, which only
matters for the PR-only target-branch checkout — a different operation entirely.

### The fix

Persist the auth header into git config instead of passing it per-command, scoped to the origin
remote's own scheme+host (derived from `git remote get-url origin`, not hardcoded) so it covers
*any* git operation against that remote for the rest of the run — including git's own implicit
lazy-fetch:

```python
token = os.getenv("PLUGIN_BITBUCKET_TOKEN", "")
if token:
    origin_url = run_command("git remote get-url origin").stdout.strip()
    parsed = urlsplit(origin_url)
    if parsed.scheme in ("http", "https"):
        url_prefix = f"{parsed.scheme}://{parsed.netloc}/"
        run_command(f'git config --add http.{url_prefix}.extraHeader "Authorization: Bearer {token}"')
```

The explicit fetches (`release.py`'s own target-branch fetch and `--unshallow` fetch) no longer
need a `-c` flag at all — they inherit the persisted config entry, same as any other git operation
against that remote, including the target-branch checkout's implicit lazy-fetch.

### Files changed

| File | Change |
|---|---|
| `plugins/master-versions/release.py` | Replaced the per-command `-c http.extraHeader=...` flag with a persisted `git config --add http.<scheme>://<host>/.extraHeader ...` entry, set once from the token (if present); both explicit fetches simplified to drop the now-redundant flag. Also scoped the tag-inventory log (previously an unfiltered, repo-wide `git tag -l` dump) to the component's own glob and the resolved branch's ancestry, matching what resolution itself actually considers. |
| `.woodpecker/pr.yml`, `.woodpecker/publish.yml` | Repointed the `Run release` steps from the stale `netanelzucaim123/master-versions:v1.0.5` (Docker Hub, predated this refactor) to `harbor.devopstashtiot.page/plugins/master-versions:prod`, manually built and pushed from this fix. (A separate attempt to namespace this under a new `woodpecker` Harbor project was abandoned — that project silently discarded every push server-side; see the project's deletion in a later commit.) |
| `plugins/master-versions/tests/test_release.py` | `TestBranchResolution._run()` now mocks `git remote get-url origin` to return a real URL (needed for the new config-persist step); `test_2_pr_event_fetches_target_branch_no_tag_flags` asserts the persisted `git config --add ... extraHeader` call instead of the old inline `-c` flag; `test_3_non_pr_also_fetches_its_own_branch_explicitly` asserts neither the header nor a `get-url` lookup happens when no token is set. |

Verified end-to-end: this fix's own PR build (a `pull_request` run against `main`, with `plugin-git`'s default `tree:0` partial clone) is what exercises the exact target-branch-checkout path described above.

---

## 5. Known limitation (unfixed) — a component path containing its own X.Y.Z-shaped segment silently caps every bump at patch

### The problem

`base/uv/0.11.29/python-38`, `-39`, `-310`, `-311`, `-312` — five real components in this repo —
have `0.11.29` (the pinned `uv` toolchain version) as a path segment, producing tags like
`base-uv-0.11.29-python-310-v1.0.0`. Against these specific components, a `feat[...]` commit
releases as a **patch** instead of minor, and a `breaking[...]` commit also releases as a
**patch** instead of major. `fix[...]` is unaffected — it already resolves to a patch, so the bug
is invisible for that type.

### Root cause — confirmed in git-cliff itself, not in this plugin

`component_tag_pattern` (this repo's `--tag-pattern`) is correctly anchored and escaped (§ above,
`re.escape(path_slug)`) — that part works. The bug is inside git-cliff's own version-extraction:
given a previous tag string, it locates the current version by finding the *first* `X.Y.Z`-shaped
substring anywhere in the tag, not the one `--tag-pattern` is actually anchored to. `0.11.29` is
itself a valid three-part semver-shaped string, and it appears before the real `-v1.0.0` suffix —
so git-cliff locks onto `0.11.29` (major `0`) as "the version," and pre-1.0 SemVer convention
caps further escalation, silently limiting every bump to patch regardless of commit type.

This was proven directly, not inferred: forcing `--bump major` explicitly (bypassing
auto-detection) against the real tag pattern fails outright with

```
ERROR git_cliff > Changelog error: `Next version (base-uv-1.0.0) does not match the tag pattern:
^base\-uv\-0\.11\.29\-python\-310-v[0-9]+\.[0-9]+\.[0-9]+$`
```

— git-cliff computed `base-uv-1.0.0` as the "next version," i.e. it bumped `0.11.29` itself and
discarded `python-310-v1.0.0` entirely. That is git-cliff's own stated reasoning, not a guess.

**Precisely scoped, not "any embedded number":** verified with isolated single-tag repos, holding
everything else constant —

| Embedded path segment | `feat` result | `breaking` result |
|---|---|---|
| none (`control-component`) | `v1.1.0` ✅ | `v2.0.0` ✅ |
| bare number, no dots (`python-310`) | `v1.1.0` ✅ | `v2.0.0` ✅ |
| two-part `X.Y` (`python-3.10`) | `v1.1.0` ✅ | `v2.0.0` ✅ |
| full three-part `X.Y.Z` (`uv-0.11.29-python-310`) | `v1.0.1` ❌ | `v1.0.1` ❌ |

Only a complete three-part, two-dot numeric sequence triggers it — the `v` prefix is irrelevant
either way (`v0.11.29` and `0.11.29` both trigger it identically).

### Why this is being left unfixed for now

Three remediations were considered:

1. **Rename slug generation** to break the three-dot shape at the source (e.g. `0.11.29` →
   `0-11-29` in the tag name). Fixes it permanently, but changes tag naming for the 5 existing
   `base/uv/0.11.29/*` components — `git describe --match` on their current tags stops matching,
   requiring a careful one-time migration (or accepting a tag-history reset for just those 5).
2. **Reimplement bump-type decision in Python**, bypassing git-cliff's auto-detection entirely.
   More invasive, more surface area for new bugs, and risks silently diverging from git-cliff's
   own (correct, when not confused) major/minor/patch rules for every *other* component.
3. **A clean temporary tag as an indirection layer** — point an unambiguous, throwaway tag at the
   same commit, let git-cliff bump against that, map the result back onto the real prefix. Verified
   working directly (`feat` → `v1.1.0`, `breaking` → `v2.0.0` via this route). Rejected as unwanted
   added complexity for a narrow, rare case.

**Decision: leave it unfixed and handle it manually.** Only 5 components are affected, all sharing
the same `uv` pin. Until one of the above is revisited:

- A `fix[base/uv/0.11.29/...]` commit is safe — it already resolves correctly.
- A `feat[base/uv/0.11.29/...]` or `breaking[base/uv/0.11.29/...]!` commit will silently release as
  a patch. If a real minor/major release is needed for one of these five, create and push the git
  tag manually (e.g. `git tag base-uv-0.11.29-python-310-v1.1.0 && git push origin --tags`) instead
  of relying on the automated bump.
- If `uv` is ever repinned to a version that is *not* itself a clean `X.Y.Z` (unlikely, uv
  versions are always three-part), or if the directory structure changes, re-verify against the
  table above before trusting automated bumps again.
