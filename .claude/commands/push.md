Run the following steps in order inside the `semantic/` directory:

1. Ensure the git remote URL has credentials embedded:
   ```
   git remote set-url origin http://netanelzucaim:Zn12345Zn12345@localhost:3000/netanelzucaim/semantic.git
   ```

2. Pull latest changes from remote with rebase (stash any uncommitted changes first):
   ```
   git stash; git pull --rebase origin main; git stash pop 2>/dev/null || true
   ```


3. Stage all changes and commit with message "update":
   ```
   git add -A && git commit -m "update" || echo "nothing to commit"
   ```

4. Push local commits to main:
   ```
   git push origin main
   ```


After each step, report the output to the user. If any step fails, stop and explain the error.


