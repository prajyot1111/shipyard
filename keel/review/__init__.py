"""The review core and the pre-gate pipeline a repo house runs before its outcome gate.

One core serves a house's self review (today) and a review card's peer review (later): the
two agents (`agents`), the finding schema and the verifier's rules (`findings`), the
standards loader (`standards`), and the risk score (`risk`). Around it, the house's
pipeline: the brief's section (`brief`), the prepare and answer commands (`prep`, run as
`bin/keel-review`), the harness's stamp (`stamp`, run as `bin/keel-review-stamp`), the Stop
hook's gate (`gate`), the checks at `kb stage review` (`stagecheck`), and the house's own
test run the stamp records (`testrun`).
"""
