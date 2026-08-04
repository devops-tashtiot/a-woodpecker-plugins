import json, os, sys
from urllib.request import urlopen, Request

token = os.environ["GITEA_TOKEN"]
url   = os.environ["GITEA_URL"]
repo  = os.environ["CI_REPO"]
event = os.environ.get("CI_PIPELINE_EVENT", "manual")

print(f">>> Event: {event}")
print(f">>> Repo:  {repo}")
print(f">>> Gitea: {url}")

if event == "pull_request":
    pr_number = os.environ["CI_COMMIT_PULL_REQUEST"]
    api_url = f"{url}/api/v1/repos/{repo}/pulls/{pr_number}"
    print(f">>> Fetching PR #{pr_number} from {api_url}")
    req = Request(api_url, headers={"Authorization": f"token {token}"})
    pr = json.loads(urlopen(req).read())
    print(f">>> Current PR #{pr['number']} — title: {pr.get('title', '')}")
    print(f">>>   state={pr.get('state')} merged={pr.get('merged')} base={pr.get('base', {}).get('ref', '')} head={pr.get('head', {}).get('ref', '')}")
else:
    api_url = f"{url}/api/v1/repos/{repo}/pulls?state=closed&limit=200"
    print(f">>> Fetching closed PRs from {api_url}")
    req = Request(api_url, headers={"Authorization": f"token {token}"})
    prs = json.loads(urlopen(req).read())
    print(f">>> Found {len(prs)} closed PR(s)")
    if not prs:
        print(">>> No closed PRs found — stopping pipeline")
        sys.exit(1)
    prs.sort(key=lambda p: p.get("merged_at") or p.get("updated_at") or "", reverse=True)
    pr     = prs[0]
    merged = pr.get("merged", False)
    base   = pr.get("base", {}).get("ref", "")
    print(f">>> Latest closed PR #{pr['number']} — title: {pr.get('title', '')} merged={merged}, base={base}")
    print(f">>>   merged_at={pr.get('merged_at')} updated_at={pr.get('updated_at')}")
    if not merged or base != "main":
        print(">>> Last PR was not merged into main — stopping pipeline")
        sys.exit(1)

body = pr.get("body", "")
print(f">>> Body length: {len(body)} chars")
open("pr_body.txt", "w").write(body)
print(">>> PR Body:\n" + body)

