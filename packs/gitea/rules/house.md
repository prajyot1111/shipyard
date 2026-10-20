## Your house: a repo on Gitea

You work in `{worktree}` on branch `{branch}`, cut from `{remote}/{base}`.{siblings} The
repo lives on Gitea, and this branch is yours: commit on it, and it is the only branch
you ever push. Your pull request opens into `{base}`, the branch this card started from.

git here is signed in to Gitea as the person you work for. Use it for your own branch:
`git fetch`, `git push -u {remote} {branch}`. Everything else that reaches Gitea goes
through the commands this brief names, or is not yours at all:

- **Merging** is done in Gitea by a person: a teammate or the user. Never merge a pull
  request, by any command.
- **Opening a pull request** is this pack's `pr <id> --draft`, and it opens a DRAFT: its
  title starts with `WIP:`, which is what a draft is in Gitea. Never open one by hand and
  never take the mark off. **Marking it ready** is Approve outcome's.
- **Comments and replies** are posted by Ship from the verdicts you record. What reviewers
  said arrives in your batches: you never need to ask Gitea for it. Never comment, review,
  edit, close or reopen a pull request by hand.
- **`{base}` and every other shared branch** are never yours to push, and no push is ever
  forced, deleted or aimed at more than your one branch.
- **The sign-in** is not yours to read or change: never run `git credential`, and never
  call Gitea's API yourself (`curl`, `wget`), and never run Gitea's `tea`. Read with git:
  `git log`, `git diff` and `git show` in your worktree.

Keel reads each command before it runs, as a shell would, and refuses the ones that are
not yours: a `git push` with a force, delete, mirror, all, tags or prune flag, with `:`,
`+` or `*` in the name, or of more than one name; `git credential` and git's credential helpers; every `tea` command; `curl` or `wget` to an address
holding `/api/v1`; and this pack's own `publish` and `pr --ready`. It reads them wherever
they sit in the line (after `;` or `|`, inside `bash -c`, `$( )` or `xargs`). A commit
message, a path or a search that only mentions a command is fine. The refusal says which
command it was and what to do instead.

It is a fence, not a wall. It does not read a script file you write and run, an alias, a
variable that holds a whole command, a command piped into a shell, `find -exec` or another
program that runs git or curl, or an address the shell builds whole. What it would have
refused is still not yours to do. Write a command out plainly.
