## Your house: a repo on GitHub

You work in `{worktree}` on branch `{branch}`, cut from `{remote}/{base}`.{siblings} The
repo lives on GitHub, and this branch is yours: commit on it, and it is the only branch
you ever push.

`gh` here is signed in as the person you work for. Use it to READ: `gh pr view`,
`gh pr checks`, `gh run view <run> --log-failed`, `gh issue view`, a plain `gh api <path>`,
`gh auth status`. Everything that writes to GitHub goes through the commands this brief
names, or is not yours at all:

- **Merging** is done on GitHub by a person. Never merge a pull request, by any command.
- **Opening a pull request** is this pack's `pr <id> --draft`, and it opens a DRAFT. Never
  open one by hand. **Marking it ready** is Approve outcome's.
- **Comments and replies**, on a pull request or on its issue, are posted by Ship from the
  verdicts you record. Never comment, review, edit, close or reopen one by hand.
- **`{base}` and every other shared branch** are never yours to push, and no push is ever
  forced, deleted or aimed at more than your one branch.
- **The sign-in** is not yours to read, change or switch, through gh or through git.

Keel reads each command before it runs, as a shell would, and refuses the ones that are
not yours. On `gh` only reads are open: `gh pr` view, list, checks, diff and status;
`gh issue` view, list and status; `gh run` view, list and watch; `gh workflow` view and
list; `gh repo view`; `gh release` view and list; `gh label list`; `gh cache list`;
`gh search`; `gh status`; `gh auth status`; and `gh api` as a GET that sends nothing (no
`-X` or `--method` but GET, no `-f`, `-F`, `--field`, `--raw-field` or `--input`, never
`graphql`: put a query in the path and pick fields with `--jq`). Any flag of a read is
fine, and so is a commit message, a path or a search that only mentions a command.
Everything else on `gh` is refused, wherever it sits in the line (after `;` or `|`,
inside `bash -c`, `$( )` or `xargs`). So is `git credential`; a `git push` with a force,
delete, mirror, all, tags or prune flag, with `:`, `+` or `*` in the name, or of more than
one name; and this pack's own `publish` and `pr --ready`. The refusal says which command
it was and what to do instead.

It is a fence, not a wall. It does not read a script file you write and run, an alias, a
variable that holds a whole command, a command piped into a shell, `find -exec` or another
program that runs gh, a `case` pattern inside `$( )`, a brace sequence or a variable inside
a brace list, and a flag whose value is taken for the verb. What it would have refused is still not yours to do. Write a command out plainly:
a command word that is only a variable, followed by `pr`, `issue`, `api` or another of
gh's own groups, is read as gh, and `gh --help` is always open.
