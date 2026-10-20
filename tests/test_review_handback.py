"""An agent's answer handed back through SubagentHandback counts (c-525, 2026-09-26).

In this harness keel-reviewer and keel-verifier hand their answer back with a
`SubagentHandback` call (prose, then the JSON array) and end with a prose summary. The stamp
read only `last_assistant_message`, so c-518, c-519 and c-520 lost rounds until each agent
was asked to repeat the bare array, and c-521 blocked on a review it had done. The hook now
takes the newest handback that carries an answer when the last message carries none.
"""

import json
from pathlib import Path

from keel.review import agents, prep, stamp
from tests.test_review_gate import HIGH, StopHookCase

PROSE = "I reviewed the change. Two things are worth a look, detailed in my handback."


def transcript(directory: Path, agent_id: str, handed: str) -> Path:
    session = directory / f"session-{agent_id}.jsonl"
    session.write_text("")
    path = session.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "SubagentHandback", "input": {"message": handed}}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": PROSE}]}}]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return session


class HandbackTest(StopHookCase):
    def finish(self, card_id, worktree, agent, handed, agent_id):
        session = transcript(Path(self.tmp.name), agent_id, handed) if handed else None
        return stamp.stamp(self.cfg, card_id, {
            "hook_event_name": "SubagentStop", "agent_type": agent, "cwd": str(worktree),
            "session_id": "s-1", "agent_id": agent_id, "last_assistant_message": PROSE,
            **({"transcript_path": str(session)} if session else {})})

    def test_a_review_handed_back_is_a_round_and_the_verifier_s_completes_it(self):
        card_id, worktree = self.at_review()
        prep.prepare(self.cfg.card_dir(card_id), "main", [worktree])
        self.finish(card_id, worktree, agents.REVIEWER,
                    "One finding, below.\n\n" + json.dumps([HIGH], indent=2), "a1")
        [entry] = stamp.read_rounds(self.cfg.card_dir(card_id))
        self.assertFalse(entry.get("unparsed"), entry.get("said"))
        self.assertEqual(len(entry["findings"]), 1)
        self.finish(card_id, worktree, agents.VERIFIER,
                    "It holds.\n\n" + json.dumps([{"id": "r1.F1", "verify": "kept", "reason": "it does"}]), "a2")
        self.assertTrue(stamp.read_rounds(self.cfg.card_dir(card_id))[-1]["complete"])

    def test_prose_with_no_answer_anywhere_still_counts_for_nothing(self):
        card_id, worktree = self.at_review()
        prep.prepare(self.cfg.card_dir(card_id), "main", [worktree])
        self.finish(card_id, worktree, agents.REVIEWER, None, "a3")
        self.assertTrue(stamp.read_rounds(self.cfg.card_dir(card_id))[-1].get("unparsed"))

    def test_the_newest_handback_with_an_answer_wins(self):
        payload = {"last_assistant_message": PROSE, "agent_id": "a4",
                   "transcript_path": str(transcript(Path(self.tmp.name), "a4", "[]"))}
        self.assertEqual(stamp.with_answer(payload)["last_assistant_message"], "[]")


if __name__ == "__main__":
    import unittest
    unittest.main()
