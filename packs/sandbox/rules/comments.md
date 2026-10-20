# How to judge review on your pull request

1. Understand the change first: `git diff origin/<base>...HEAD` in each worktree, and the
   code outside the diff a comment refers to.
2. Read each thread as a conversation: who spoke last, and whether it waits on you.
3. For each item: one line saying what the reviewer asks; a verdict, Valid, Not valid or
   Valid but deferred; the reasoning, checked against the code and not the comment's
   framing. Blocking and correctness first, nits last.
4. Change code only for a valid item: say why it is needed and why it does not regress,
   match the file's style, add a test when it carries logic, and run the tests it reaches
   (`python3 -m unittest`). Otherwise reply: specific, courteous, acknowledging the point,
   saying why; a deferred item says it is a follow-up.
5. A failed check: read it, reproduce it, fix only a real failure of this change.
6. Many items: judge them with subagents in parallel; they advise, you own the verdict.
   Report exactly what you ran. Never resolve a thread: the reviewer does.
