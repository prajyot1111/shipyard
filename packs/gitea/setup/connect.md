A card's change in this space becomes a pull request on your Gitea, from the card's own
branch into the branch the card started from. It opens as a draft (in Gitea that is a title
starting `WIP:`). When you approve the card, Shipyard takes the mark off as you and watches the
pull request for comments, reviews and failing checks. A teammate reviews it in Gitea, and
you or a teammate merge it there: Shipyard never merges and never pushes a shared branch.

Shipyard talks to Gitea's API at the address each repo is cloned from, with the sign-in git
already keeps for that address. It asks git for it when it needs it and never stores, prints
or logs it. Five checks, each with its fix:

1. **git is installed.** On macOS: `xcode-select --install`. On Linux: `sudo apt install git`
   or `sudo dnf install git`. Shipyard never installs it for you.
2. **Each repo's address is an http or https one.** That is where Gitea's API is found. A
   repo cloned over ssh, or one that does not live on a Gitea, cannot use this connection;
   keep its work on this machine and push when you say.
3. **git is signed in.** In the repo's folder, run `git fetch`. If git asks, give your Gitea
   user name and password, or an access token made in Gitea under Settings, Applications, in
   place of the password. This one is always yours to run.
4. **The sign-in may do what the connection does.** A password may. An access token may do
   only what it was made for: one made only for pushing can open a pull request, but Gitea
   will not let it read or answer your teammates' comments, or say whose it is. Make a token
   in Gitea (Settings, Applications) allowed `write:repository`, `write:issue` and
   `read:user`, and give it to git in place of the old one.
5. **Your account may push to each repo.** Seeing a repo is not enough: your account needs
   write access to it in Gitea. Ask the repo's owner.

To see which account, which repo and which address a failing check means, run `./ready` in
the pack's folder: it prints the five checks with the exact reason and fix for each, with
the lines to copy.

Pull requests that wait on your review can come to you as review cards. That is off until
you turn it on.
