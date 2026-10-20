"""The write budget can fail (r1.F2): a layer that closes or deletes is caught by the
conformance suite's budget test, because the stand-in records every method and every edit
it does not implement as an `unknown` write."""

import types
import unittest

import suitefence  # noqa: F401

import gt_layer
import test_conformance

BUDGET = "test_only_the_contract_s_writes_are_made_and_no_token_is_ever_returned_or_raised"


def bad_layer(**over) -> types.ModuleType:
    made = types.ModuleType("bad_layer")
    made.__dict__.update({name: value for name, value in vars(gt_layer).items() if not name.startswith("__")})
    made.__dict__.update(over)
    return made


def closes(repo, number, body):
    gt_layer.ask(repo, "PATCH", f"pulls/{int(number)}", body={"state": "closed"})


def deletes(repo, number, text):
    gt_layer.ask(repo, "DELETE", f"issues/{int(number)}/comments/1")


def puts(repo, number, text):
    gt_layer.ask(repo, "PUT", f"pulls/{int(number)}/merge")


def retitles(repo, number, body):
    gt_layer.ask(repo, "PATCH", f"pulls/{int(number)}", body={"title": "Something else"})


def assigns(repo, title, branch, base, body, draft=True, cwd=None):
    made = gt_layer.ask(repo, "POST", "pulls", body={"head": branch, "base": base, "title": "WIP: " + title,
                                                     "body": body, "assignees": ["ana"]})
    return gt_layer.shaped(made, repo)


class BudgetTest(unittest.TestCase):
    def budget_with(self, layer) -> unittest.TestResult:
        class Bad(test_conformance.GiteaHost):
            def host_layer(self):
                return layer
        result = unittest.TestResult()
        Bad(BUDGET).run(result)
        return result

    def test_a_layer_that_closes_deletes_or_merges_fails_the_budget(self):
        for name, layer in (("closes", bad_layer(set_body=closes)), ("deletes", bad_layer(comment=deletes)),
                            ("merges", bad_layer(comment=puts)), ("retitles", bad_layer(set_body=retitles)),
                            ("assigns", bad_layer(open_pr=assigns))):
            result = self.budget_with(layer)
            # the budget's write list names the `unknown`; a refused open is the test's error instead
            (said,) = [text for _, text in result.failures + result.errors]
            self.assertTrue("unknown" in said or "the stand-in has no answer" in said, (name, said))

    def test_the_real_layer_passes_it(self):
        result = self.budget_with(gt_layer)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)


if __name__ == "__main__":
    unittest.main()
