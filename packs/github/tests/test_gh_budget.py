"""The write budget can fail (r1.F2): a layer that closes or deletes is caught by the
conformance suite's budget test, because the stand-in `gh` records every method, path and
flag it does not implement as an `unknown` write, `--method` honoured on every api path."""

import types
import unittest

import suitefence  # noqa: F401

import gh_cli
import gh_layer
import test_conformance

BUDGET = "test_only_the_contract_s_writes_are_made_and_no_token_is_ever_returned_or_raised"


def bad_layer(**over) -> types.ModuleType:
    made = types.ModuleType("bad_layer")
    made.__dict__.update({name: value for name, value in vars(gh_layer).items() if not name.startswith("__")})
    made.__dict__.update(over)
    return made


def closes(repo, number, body):
    gh_cli.run("pr", "close", str(number), "-R", f"github.com/{repo}")


def deletes(repo, number, text):
    gh_cli.run("api", "-X", "DELETE", f"repos/{repo}/issues/{int(number)}/comments")


def patches(repo, number, text):
    gh_cli.run("api", "--method", "PATCH", f"repos/{repo}/pulls/{int(number)}/reviews", "-f", "state=closed")


def retitles(repo, number, body):
    gh_cli.run("pr", "edit", str(number), "-R", f"github.com/{repo}", "--title", "x", "--body-file", "-", stdin=body)


def deletes_written_as_one(repo, number, text):
    gh_cli.run("api", "--method=DELETE", f"repos/{repo}/issues/{int(number)}/comments")


def deletes_attached(repo, number, text):
    gh_cli.run("api", "-XDELETE", f"repos/{repo}/issues/{int(number)}/comments")


def undoes_ready(repo, number):
    gh_cli.run("pr", "ready", str(number), "-R", f"github.com/{repo}", "--undo")


def deletes_last(repo, number, text):
    gh_cli.run("pr", "comment", str(number), "-R", f"github.com/{repo}", "--delete-last", "--yes")


class BudgetTest(unittest.TestCase):
    def budget_with(self, layer) -> unittest.TestResult:
        class Bad(test_conformance.GitHubHost):
            def host_layer(self):
                return layer
        result = unittest.TestResult()
        Bad(BUDGET).run(result)
        return result

    def test_a_layer_that_closes_deletes_or_writes_past_the_contract_fails_the_budget(self):
        for name, layer in (("closes", bad_layer(set_body=closes)), ("deletes", bad_layer(comment=deletes)),
                            ("patches", bad_layer(comment=patches)), ("retitles", bad_layer(set_body=retitles)),
                            ("deletes as one word", bad_layer(comment=deletes_written_as_one)),
                            ("deletes attached", bad_layer(comment=deletes_attached)),
                            ("undoes ready", bad_layer(set_ready=undoes_ready)),
                            ("deletes the last", bad_layer(comment=deletes_last))):
            result = self.budget_with(layer)
            self.assertEqual((len(result.failures), len(result.errors)), (1, 0), name)
            self.assertIn("unknown", str(result.failures[0][1]), name)

    def test_the_real_layer_passes_it(self):
        result = self.budget_with(gh_layer)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)


if __name__ == "__main__":
    unittest.main()
