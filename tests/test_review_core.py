"""The review core (HP-1): one reviewer, one verifier, one finding schema, one standards loader.

The same core serves a house's self review today and a review card's peer review later, so
what it promises is pinned here rather than in prose: the two agents carry the adversarial
stance and the verification rules, a finding survives the verifier unless the verifier
brings evidence from the code, a high finding the verifier disputes is never dropped, and
the schema round-trips.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from keel.review import agents, findings, risk, standards
from tests.helpers import make_repo


def sh(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True).stdout


def finding(fid="F1", severity="high", axis="spec", evidence="keel/x.py:3 returns None", **kw):
    raw = {"id": fid, "axis": axis, "severity": severity, "path": "keel/x.py", "line": 3,
           "claim": "the empty case returns None", "evidence": evidence,
           "suggestion": "return an empty list"}
    raw.update(kw)
    return raw


class AgentsTest(unittest.TestCase):
    def setUp(self):
        self.defined = json.loads(agents.agents_json())

    def test_both_agents_are_read_only_on_the_house_s_model(self):
        self.assertEqual(set(self.defined), {agents.REVIEWER, agents.VERIFIER})
        for agent in self.defined.values():
            self.assertEqual(agent["tools"], ["Read", "Grep", "Glob"])
            self.assertEqual(agent["model"], "inherit")


class SchemaTest(unittest.TestCase):
    def test_a_finding_round_trips_through_json(self):
        one = findings.normalise(finding(), round_no=1)
        again = findings.from_json(findings.to_json([one]))
        self.assertEqual(again, [one])
        self.assertEqual(set(one), set(findings.FIELDS))
        self.assertIn("public_comment", one)        # the slot peer review will fill
        self.assertIsNone(one["public_comment"])

    def test_ids_are_made_unique_per_round(self):
        self.assertEqual(findings.normalise(finding(), round_no=2)["id"], "r2.F1")

    def test_an_answer_is_read_from_a_fenced_json_block(self):
        text = "Here they are.\n\n```json\n" + json.dumps([finding()]) + "\n```\n"
        self.assertEqual(findings.parse_answer(text)[0]["id"], "F1")
        self.assertEqual(findings.parse_answer("[]"), [])
        self.assertIsNone(findings.parse_answer("no findings, it looks fine"))

    def test_bad_values_are_mended_not_trusted(self):
        odd = findings.normalise(finding(severity="blocker", axis="style", line="12"), 1)
        self.assertEqual(odd["severity"], "medium")
        self.assertEqual(odd["axis"], "standards")
        self.assertEqual(odd["line"], 12)
        self.assertEqual(odd["verify"], "unverified")


class VerifierRulesTest(unittest.TestCase):
    def verdict(self, found, verify, reason="", evidence=""):
        return findings.apply_verdicts([found], [{"id": found["id"], "verify": verify,
                                                  "reason": reason, "evidence": evidence}])[0]

    def test_a_refutation_without_evidence_from_the_code_cannot_drop_a_finding(self):
        low = findings.normalise(finding(severity="low"), 1)
        after = self.verdict(low, "refuted", reason="I do not think so")
        self.assertEqual(after["verify"], "unverified")
        self.assertTrue(findings.survives(after))

    def test_a_refutation_with_evidence_drops_a_medium_finding(self):
        medium = findings.normalise(finding(severity="medium"), 1)
        after = self.verdict(medium, "refuted", reason="handled upstream",
                             evidence="keel/y.py:10 checks the empty case first")
        self.assertEqual(after["verify"], "refuted")
        self.assertFalse(findings.survives(after))

    def test_a_disputed_high_finding_survives_with_both_sides(self):
        high = findings.normalise(finding(severity="high"), 1)
        after = self.verdict(high, "refuted", reason="handled upstream",
                             evidence="keel/y.py:10 checks the empty case first")
        self.assertEqual(after["verify"], "disputed")
        self.assertTrue(findings.survives(after))
        self.assertEqual(after["evidence"], "keel/x.py:3 returns None")
        self.assertIn("keel/y.py:10", after["verify_evidence"])

    def test_no_verdict_is_undecided_and_kept_as_unverified(self):
        high = findings.normalise(finding(), 1)
        after = findings.apply_verdicts([high], [])[0]
        self.assertEqual(after["verify"], "unverified")
        self.assertTrue(findings.survives(after))

    def test_a_kept_finding_stays_kept(self):
        after = self.verdict(findings.normalise(finding(), 1), "kept", reason="reproduced")
        self.assertEqual(after["verify"], "kept")


class RenderTest(unittest.TestCase):
    def test_spec_and_standards_are_two_groups(self):
        rows = [findings.normalise(finding("F1", axis="standards", severity="low"), 1),
                findings.normalise(finding("F2", axis="spec", severity="medium"), 1)]
        text = findings.render_round({"round": 1, "head": "abc1234def", "findings": rows,
                                      "risk": {"level": "medium", "why": "a spec finding"}})
        self.assertLess(text.index("Spec"), text.index("Standards"))
        self.assertIn("r1.F2", text)
        self.assertIn("medium", text)
        self.assertNotIn(chr(0x2014), text)


class StandardsTest(unittest.TestCase):
    CLAUDE = ("# CLAUDE.md\n\n## Overview\n\nNot a rule.\n\n```bash\n# Initial setup\nmake\n```\n\n"
              "## Coding Standards\n\n- Imports at the top.\n\n### Models\n\n- Save with save().\n\n"
              "## Code Review Checklist\n\n- [ ] Every endpoint is gated.\n\n## Notes\n\nNope.\n")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_the_checklist_sections_of_the_repo_s_own_file(self):
        picked = standards.sections(self.CLAUDE)
        self.assertIn("Imports at the top", picked)
        self.assertIn("Save with save()", picked)          # a subsection comes with it
        self.assertIn("Every endpoint is gated", picked)
        self.assertNotIn("Not a rule", picked)
        self.assertNotIn("Nope", picked)
        self.assertNotIn("make", picked)                     # a fenced `#` is not a heading

    def test_only_the_repos_the_diff_touches_are_read_and_the_test_rule_always(self):
        touched = make_repo(self.dir / "one")
        (touched / "CLAUDE.md").write_text(self.CLAUDE)
        untouched = make_repo(self.dir / "two")
        (untouched / "CLAUDE.md").write_text(self.CLAUDE.replace("Imports", "Untouched"))
        text = standards.load({"one": touched})
        self.assertIn("Imports at the top", text)
        self.assertNotIn("Untouched", text)
        self.assertIn(standards.TEST_QUALITY_TITLE, text)

    def test_a_repo_with_no_checklist_still_gets_the_test_rule(self):
        bare = make_repo(self.dir / "bare")
        text = standards.load({"bare": bare})
        self.assertIn("bare", text)
        self.assertIn(standards.TEST_QUALITY_TITLE, text)


class RiskTest(unittest.TestCase):
    DIFF = ("# repo: one\n"
            "diff --git a/app/migrations/versions/1.py b/app/migrations/versions/1.py\n"
            "diff --git a/app/x.py b/app/x.py\n")

    def test_the_touched_paths_and_repos_are_read_from_the_prepared_diff(self):
        seen = risk.touched(self.DIFF + "# repo: two\ndiff --git a/src/a.js b/src/a.js\n")
        self.assertEqual(seen["repos"], ["one", "two"])
        self.assertIn("app/x.py", seen["paths"])

    def test_a_surviving_high_finding_is_high(self):
        high = findings.normalise(finding(), 1)
        self.assertEqual(risk.score([high], risk.touched(""))["level"], "high")

    def test_a_refuted_finding_does_not_count(self):
        gone = dict(findings.normalise(finding(severity="medium"), 1), verify="refuted")
        self.assertEqual(risk.score([gone], risk.touched("diff --git a/x b/x\n"))["level"], "low")

    def test_a_migration_is_medium_and_with_auth_it_is_high(self):
        self.assertEqual(risk.score([], risk.touched(self.DIFF))["level"], "medium")
        more = self.DIFF + "diff --git a/app/rbac_rules.json b/app/rbac_rules.json\n"
        scored = risk.score([], risk.touched(more))
        self.assertEqual(scored["level"], "high")
        self.assertIn("migration", scored["why"])

    def test_two_repos_are_cross_service(self):
        two = self.DIFF.replace("migrations/versions/1.py", "y.py") + "# repo: two\ndiff --git a/a b/a\n"
        scored = risk.score([], risk.touched(two))
        self.assertEqual(scored["level"], "medium")
        self.assertIn("cross", scored["why"])


if __name__ == "__main__":
    unittest.main()
