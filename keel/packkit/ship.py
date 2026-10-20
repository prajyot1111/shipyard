"""Ship on a card at shipping (`publish <id> --answer`): push the house's commits to the
card's OWN branch, mark a change still a draft ready, then post the replies kept.

Keel hands `{"ship": true, "replies": [{handle, text}], "lease": {repo: sha}}` on stdin.
Everything is checked before anything leaves, for EVERY repo of the card before the first
push, in this order: every reply's handle names one of the card's changes; when there are
replies, the host says which account is signed in (that is whose markers count, below);
every change the Ship would touch is read from the host and is still OPEN, from the card's
own branch, and a branch of the repository itself (one merged, closed, from another branch,
from a fork, or in a state the host does not name refuses the whole); every branch is the
card's own (`shared.py`) and its worktree is on it; and the branch is still on the remote
(one deleted after a merge is a refusal, never made again, and a remote that cannot be asked
is a refusal too). The push goes first after that: a reply saying "fixed" must never land
before the fix. A push that fails names its repo and the repos already pushed.

**The push is a plain fast-forward, or it is not made.** Each worktree is looked at against
its branch on the remote, asked at that moment (`standing`): `forward` is pushed with no
force flag of any kind, `skip` (the remote holds HEAD and more) pushes nothing, `diverged`
refuses the whole Ship before any push, and `unknown` (the look failed) is pushed plain
too, so the remote refuses anything that is not a fast-forward. The `lease` Keel hands is
never used: no pack on the kit forces a push, leased or not.

**A reply is known by the handle it answers, never by its words.** Each reply posted
carries a hidden marker (`marker`: an HTML comment naming the handle and a digest of the
words, which a host does not draw). A retry after a failure halfway finds the markers of
what landed, written by the SIGNED-IN account (the one that posts them, whoever opened the
change), and posts only the rest; the same words to another item, in this Ship or a later
round, are posted. A reply to a line comment (`cl<n>`) goes under that comment's
`reply_to` (the layer says where a reply to it goes); every other reply (to a general
comment `cg<n>`, a review's words `cr<n>`, a review, a failed check) is a general comment.
The kind is the handle's, so a number shared between the host's id spaces sends nothing
astray.
"""

import hashlib
import re
import shutil

from keel.packkit import card as gc
from keel.packkit import cli, pack, shared
from keel.packkit.errors import HostError
from keel.packkit.layer import GENERAL, LINES, UNKNOWN

PUSH_SECONDS = 180
FETCH_SECONDS = 45      # shorter than the push: a remote that hangs leaves the push its time
DIVERGED = ("the {repo} worktree has diverged from {branch} on the remote ({ahead} ahead, {behind} "
            "behind): that branch was rewritten or pushed to outside Shipyard, so nothing was pushed and "
            "no reply was posted. Bring the worktree in line first (the card shows the commands)")
NOT_OPEN = ("{change} #{pr} of {slug} is {state} {on}, so nothing was pushed and no reply was "
            "posted: a {change} that is no longer open is not written to")
GONE = ("{branch} is no longer on the remote of {repo} (deleted, as after a merge), so nothing was "
        "pushed and no reply was posted: this pack does not make a deleted branch again")
SAID = {"merged": "merged", "declined": "closed"}
NOT_THIS_BRANCH = ("{change} #{pr} of {slug} is from the branch {theirs}, not this card's {ours}, so "
                   "nothing was pushed and no reply was posted")
NOT_OWN = ("{change} #{pr} of {slug} is not from a branch of {slug} itself ({host} does not say its "
           "head is the repository's own), so nothing was pushed and no reply was posted")
DEAF = ("the remote of {repo} could not be asked whether {branch} is still there ({why}), so nothing was "
        "pushed and no reply was posted; try again")
NO_PASSWORD = re.compile(r"terminal prompts disabled|could not read username|authentication failed|"
                         r"permission denied \(publickey\)", re.I)
LINE = re.compile(r"^cl(\d+)$")
MARK = "<!-- keel:reply {handle} {digest} -->"


def git_said(done) -> str:
    """git's own last word on a failure, as one sentence."""
    text = (done.stderr.strip() or done.stdout.strip()).splitlines()
    return cli.sentence(text[-1] if text else "")


def entries_of(card: dict) -> list[dict]:
    entries = gc.prs_of(card)
    if not entries:
        raise HostError(f"card {card['id']} has no {pack.words().change} (options.pr or options.prs)")
    return entries


def target(entries: list[dict], handle: str) -> tuple[dict, str]:
    """The change a reply goes to and its handle there: `<repo>.<handle>` names one of the
    card's other changes, no dot the primary's; a dotted one naming none is refused."""
    repo, dot, local = handle.partition(".")
    if not dot:
        return entries[0], handle
    for entry in entries[1:]:
        if entry["repo"] == repo:
            return entry, local
    raise HostError(f"the reply {handle} names {repo}, which is not one of this card's other "
                    f"{pack.words().changes}; nothing was pushed or posted")


# ----- before anything leaves -----

def still_open(entries: list[dict], repos: dict) -> dict:
    """Every change the Ship would touch, read from the host now: `{repo: change}`. Each
    must be open (a state the host does not name is not open), from the card's own branch
    (the push is by branch name, the check by number: they must be one change) and from the
    repository itself; any other refuses the whole Ship."""
    found, w = {}, pack.words().fill()
    for entry in entries:
        repo = repos[entry["repo"]]
        found[entry["repo"]] = now = pack.layer().get(repo, entry["pr"])
        if now["state"] == UNKNOWN:
            raise gc.unknown_state(repo, entry["pr"])
        if now["state"] != "open":
            raise HostError(NOT_OPEN.format(pr=entry["pr"], slug=repo, state=SAID[now["state"]], **w))
        if now["branch"] != entry["branch"]:
            raise HostError(NOT_THIS_BRANCH.format(pr=entry["pr"], slug=repo, theirs=now["branch"],
                                                   ours=entry["branch"], **w))
        if not now["own"]:
            raise HostError(NOT_OWN.format(pr=entry["pr"], slug=repo, **w))
    return found


def trees_of(card: dict, entries: list[dict]) -> list[tuple[dict, object]]:
    """(change, worktree) for each, every one checked before any push: its branch is the
    card's own (never a shared one), the worktree is on it, and the branch is still on the
    remote. The primary must have a worktree."""
    trees = []
    for entry in entries:
        shared.refuse(card, entry["repo"], entry["branch"])
        tree = gc.worktree_of(card, entry["repo"])
        if tree is None or not (tree / ".git").exists():
            if entry["primary"]:
                raise HostError(f"card {card['id']} has no worktree to push from")
            continue
        here = gc.git(tree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if here != entry["branch"]:
            raise HostError(f"the {entry['repo']} worktree is on {here or 'no branch'}, not "
                            f"{entry['branch']}; nothing was pushed")
        trees.append((entry, tree))
    for entry, _ in trees:
        still_there(card, entry)
    return trees


def still_there(card: dict, entry: dict) -> None:
    """Refuse unless the remote says, now, that it still has the branch. A remote that
    cannot be asked is a refusal too: a push on hope could make a deleted branch again."""
    try:
        there = gc.remote_head(card, entry["repo"], entry["branch"], timeout=FETCH_SECONDS)
    except HostError as error:
        why = str(error).split(": ", 1)[-1]
        raise HostError(DEAF.format(repo=entry["repo"], branch=entry["branch"], why=why)) from None
    if there is None:
        raise HostError(GONE.format(branch=entry["branch"], repo=entry["repo"]))


# ----- the push -----

def standing(tree, remote: str, branch: str) -> tuple[str, str | None]:
    """Where the worktree stands against its branch ON THE REMOTE, asked now: `forward` (the
    remote's head is HEAD or an ancestor of it), `skip` (the remote holds HEAD and more),
    `diverged` (neither holds the other), or `unknown` when the look failed or hung."""
    try:
        fetched = gc.fetch(tree, remote, branch, timeout=FETCH_SECONDS)
    except HostError:
        return "unknown", None
    if fetched.returncode != 0:
        return "unknown", None
    head = gc.git(tree, "rev-parse", "HEAD").stdout.strip()
    there = gc.git(tree, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}").stdout.strip()
    if not head or not there:
        return "unknown", None
    if gc.git(tree, "merge-base", "--is-ancestor", there, head).returncode == 0:
        return "forward", there
    if gc.git(tree, "merge-base", "--is-ancestor", head, there).returncode == 0:
        return "skip", there
    return "diverged", there


def uses_lfs(tree) -> bool:
    """Whether the branch's tree marks files for LFS: a `filter=lfs` attribute in any
    `.gitattributes` it tracks."""
    found = gc.git(tree, "grep", "--quiet", "--fixed-strings", "filter=lfs", "HEAD", "--",
                   ":(glob)**/.gitattributes")
    return found.returncode == 0


def lfs_push(tree, remote: str, branch: str, repo: str, heads: dict) -> None:
    """r2.D1: a kit push runs with hooks off (`card.NO_HOOKS`), so git-lfs's own pre-push hook
    does not upload the branch's LFS objects; the kit runs `git lfs push` itself first, hooks
    off too, and a failure stops the push. A repo on LFS with no git-lfs installed is refused,
    since its push would carry the pointers without their objects. Nothing at all for a repo
    not on LFS."""
    if not uses_lfs(tree):
        return
    if shutil.which("git-lfs") is None:
        raise HostError(f"git-lfs is needed to ship {repo}, which keeps files in LFS, and it is not installed, "
                        f"so nothing was pushed there and no reply was posted: install it (`brew install git-lfs` "
                        f"or your system's git-lfs package, then `git lfs install`) and Ship again"
                        + (f"; already pushed: {', '.join(heads)}" if heads else ""))
    done = gc.git(tree, "lfs", "push", remote, branch, timeout=PUSH_SECONDS)
    if done.returncode != 0:
        raise HostError(f"git lfs push of {branch} in {repo} failed, so nothing was pushed there and no reply "
                        f"was posted: {git_said(done)}" + (f"; already pushed: {', '.join(heads)}" if heads else ""))


def push(card: dict, trees: list) -> tuple[dict, list[str]]:
    """Each worktree's branch pushed plain: `({repo: head pushed}, [repos skipped])`. Every
    worktree is looked at before any is pushed, so one that diverged refuses the whole."""
    remote, heads, skipped = gc.remote_of(card), {}, []
    plans = [(entry, tree, *standing(tree, remote, entry["branch"])) for entry, tree in trees]
    for entry, tree, how, there in plans:
        if how == "diverged":
            sides = gc.git(tree, "rev-list", "--left-right", "--count", f"HEAD...{there}").stdout.split()
            ahead, behind = sides if len(sides) == 2 else ("?", "?")
            raise HostError(DIVERGED.format(repo=entry["repo"], branch=entry["branch"],
                                            ahead=ahead, behind=behind))
    for entry, tree, how, _ in plans:
        if how == "skip":
            skipped.append(entry["repo"])
            continue
        branch = entry["branch"]
        lfs_push(tree, remote, branch, entry["repo"], heads)
        pushed = gc.git(tree, "push", remote, f"refs/heads/{branch}:refs/heads/{branch}", timeout=PUSH_SECONDS)
        if pushed.returncode != 0:
            said = pushed.stderr + pushed.stdout
            raise HostError(f"git push of {branch} in {entry['repo']} failed, so no reply was posted: "
                            f"{git_said(pushed)}" + (pack.host().said("sign_git_in") if NO_PASSWORD.search(said)
                                                     else "")
                            + (f"; already pushed: {', '.join(heads)}" if heads else ""))
        heads[entry["repo"]] = gc.git(tree, "rev-parse", "HEAD").stdout.strip()
    return heads, skipped


# ----- ready, and the replies -----

def mark_ready(card: dict, entries: list[dict], read: dict) -> list[str]:
    """Each change the read showed still a draft, marked ready; the repos marked."""
    flipped = []
    for entry in entries:
        if read[entry["repo"]]["draft"]:
            pack.layer().set_ready(gc.host_repo(card, entry["repo"]), entry["pr"])
            flipped.append(entry["repo"])
    return flipped


def marker(handle: str, text: str) -> str:
    """The hidden line a reply ends with: the handle it answers and a digest of its words
    (as Keel's own record of a posted reply is a handle and a digest)."""
    digest = hashlib.sha256(text.strip().encode()).hexdigest()[:12]
    return MARK.format(handle=handle, digest=digest)


def signed_in_as(repos: dict) -> dict:
    """{repo: the account signed in on that repo's host}: the one that posts the replies, so
    the one whose markers say what already landed. Asked once per host address; refused
    when the host cannot say."""
    names, asked, host = {}, {}, pack.host()
    for key, repo in repos.items():
        if repo.base not in asked:
            try:
                asked[repo.base] = pack.layer().account(repo)
            except HostError as error:
                raise HostError(host.said("no_account", why=error)) from None
            if not asked[repo.base]:
                raise HostError(host.said("no_account", why="it named none"))
        names[key] = asked[repo.base]
    return names


class Thread:
    """One change's conversation as the replies need it: where a reply to each line comment
    goes, and the markers of the replies the signed-in account (`me`) already posted. A
    comment with no author is nobody's."""

    def __init__(self, slug, number: int, me: str):
        self.slug, self.number = slug, int(number)
        said = pack.layer().said(slug, number, parts=(LINES, GENERAL))
        lines = said.get(LINES) or []
        self.root = {int(c["id"]): int(c.get("reply_to") or c["id"]) for c in lines}
        mine = [c.get("body") or "" for c in [*lines, *(said.get(GENERAL) or [])] if me and c.get("author") == me]
        self.said = "\n".join(mine)

    def post(self, local: str, text: str) -> bool:
        """Post one reply unless its marker is already on the change; True when it was
        posted now."""
        mark = marker(local, text)
        if mark in self.said:
            return False
        line = LINE.match(local)
        under = self.root.get(int(line.group(1))) if line else None
        body = f"{text}\n\n{mark}"
        if under is None:
            pack.layer().comment(self.slug, self.number, body)
        else:
            pack.layer().reply(self.slug, self.number, under, body)
        self.said += "\n" + mark
        return True


def post(card: dict, entries: list[dict], replies: list[dict], me: dict) -> tuple[list[str], list[dict]]:
    """Each reply once: the handles newly posted, and every reply that is on the host when
    this returns (posted now, or found there by its marker) as {handle, text}, which Keel
    keeps so a second Ship hands none of them again."""
    threads, posted, sent = {}, [], []
    for reply in replies:
        handle, text = str(reply.get("handle") or ""), str(reply.get("text") or "").strip()
        if not text:
            continue
        entry, local = target(entries, handle)
        key = (entry["repo"], entry["pr"])
        if key not in threads:
            threads[key] = Thread(gc.host_repo(card, entry["repo"]), entry["pr"], me.get(entry["repo"], ""))
        if threads[key].post(local, text):
            posted.append(handle)
        sent.append({"handle": handle, "text": text})
    return posted, sent


def ship(card: dict, answer: dict) -> dict:
    """Handles, changes, branches and worktrees checked; then push, ready, post."""
    gc.refuse_no_pr(card)
    entries = entries_of(card)
    replies = list(answer.get("replies") or [])
    for reply in replies:
        target(entries, str(reply.get("handle") or ""))
    repos = {entry["repo"]: gc.host_repo(card, entry["repo"]) for entry in entries}
    me = signed_in_as(repos) if any(str(reply.get("text") or "").strip() for reply in replies) else {}
    read = still_open(entries, repos)
    heads, skipped = push(card, trees_of(card, entries))
    ready = mark_ready(card, entries, read)
    posted, sent = post(card, entries, replies, me)
    return {"shipping": True, "shipped": True, "pr": int(entries[0]["pr"]), "pushed": heads,
            "skipped": skipped, "ready": ready, "posted": posted, "sent": sent}
