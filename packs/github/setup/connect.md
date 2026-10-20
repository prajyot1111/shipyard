When you approve a card in this space, Shipyard marks its pull request ready as you and watches
it for comments and failing checks. You merge it on GitHub: Shipyard never merges and never
pushes a shared branch.

Shipyard talks to GitHub through `gh`, GitHub's own command line tool, which keeps your sign-in.
Shipyard never reads or stores it. Four checks, each with its fix:

1. **gh is installed.** On macOS: `brew install gh`. On Linux: `sudo apt install gh` or
   `sudo dnf install gh`. Shipyard never installs it for you.
2. **You are signed in.** Run `gh auth login` in a terminal. Choose GitHub.com, then HTTPS,
   then sign in with your browser. This one is always yours to run.
3. **Each repo's address is a github.com one.** A repo that lives somewhere else cannot use
   this connection; keep its work on this machine and push when you say.
4. **Your account may push to each repo.** Seeing a repo is not enough: GitHub has to give
   your account write access to it. If you are signed in as the wrong account, switch with
   `gh auth switch`; if it is the right one, ask the repo's owner for write access.

To see which account, which repo and which address a failing check means, run `./ready` in
the pack's folder: it prints the four checks with the exact reason and fix for each.

If a push later asks for a password, git is not using gh's sign-in yet: run
`gh auth setup-git` once (a local git setting, no secret).
