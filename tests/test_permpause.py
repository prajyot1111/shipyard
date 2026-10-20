"""permpause: a house auto mode paused on a permission prompt is blocked with what was denied.

The box, 2026-09-25, c-521 (r-1): auto mode's classifier denied `git reset --hard`, then two
read-only `git show | grep`, and past its denial limit the bg session waited on a permission
prompt nobody sees. The card sat at `planning` unblocked while the drain counted it as a
live house for 30+ minutes. The fixtures below are that session's shape: the listing row as
2.1.283 prints it, the Notification hook the card recorded, and the transcript's last turn.
"""

import json
from unittest import mock

from keel import drain, pausewake, permpause
from tests.helpers import SESSION, background_row
from tests.test_drain import DrainCase

DENIAL = ("Permission for this action was denied by the Claude Code auto mode classifier. "
          "Reason: [Irreversible Local Destruction]. If you have other tasks that don't depend "
          "on this action, continue working on those.")
RESET = "cd /w; git reset -q --hard keel/c-520-bo-2-bosun-requests; git rev-parse HEAD"
SHOW_1 = "git show keel/c-520:app/ui.console.js | grep -n needsTab"
SHOW_2 = "git show keel/c-520:keel/deckstate.py | grep -n console_entry"


def user(content, **extra) -> dict:
    return dict({"type": "user", "message": {"role": "user", "content": content}}, **extra)


def call(key: str, command: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": key, "name": "Bash", "input": {"command": command}}]}}


def result(key: str, text: str) -> dict:
    return user([{"type": "tool_result", "tool_use_id": key, "content": text}])


def c521_turn() -> list[dict]:
    """An older turn's denial, then the turn that paused: three denials and no reply."""
    return [user("an older prompt"), call("t0", "rm -rf build"), result("t0", DENIAL),
            user("# You are the house for one card ..."),
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Writing the plan."}]}},
            call("t1", "cat plan.md"), result("t1", "the plan"),
            user("<local-command-caveat>", isMeta=True),
            call("t2", RESET), result("t2", DENIAL),
            call("t3", SHOW_1), result("t3", DENIAL),
            call("t4", SHOW_2), result("t4", [{"type": "text", "text": DENIAL}]),
            {"type": "attachment", "attachment": {"type": "total_tokens_reminder"}},
            {"type": "cost-state", "totalCostUSD": 1.8}]


class PermissionPauseCase(DrainCase):
    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True            # nothing here is about starting a card
        self.transcript = self.dir / "c521.jsonl"
        self.write(c521_turn())

    def write(self, rows: list[dict]) -> None:
        self.transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def paused(self, status="waiting", waiting_for="permission prompt", notification=True,
               session=SESSION, **kwargs) -> str:
        """c-521 at 19:21: at planning before its plan, listed waiting, the hook recorded."""
        kwargs.setdefault("stage", "planning")
        kwargs.setdefault("autonomy", "attended")
        card_id = self.housed(session=session, **kwargs)
        row = dict(background_row(card_id, session), status=status)
        if status == "waiting" and waiting_for:
            row["waitingFor"] = waiting_for
        self.fake.rows.append(row)
        if notification:
            self.board.record_hook(card_id, "Notification", {
                "session_id": session, "transcript_path": str(self.transcript),
                "hook_event_name": "Notification", "message": "Claude needs your permission",
                "notification_type": "permission_prompt"})
        return card_id

    def reason(self, card_id: str) -> str | None:
        return self.board.get(card_id)["blocked_reason"]


class BlockTest(PermissionPauseCase):
    def test_c521_is_blocked_naming_the_denied_commands(self):
        card_id = self.paused()
        summary = self.once()
        self.assertEqual(summary["denied"], 1)
        reason = self.reason(card_id)
        self.assertIn("paused this house on a permission prompt", reason)
        self.assertIn("waiting for: permission prompt", reason)
        for command in (RESET, SHOW_1, SHOW_2):
            self.assertIn(f"- Bash: {command} [Irreversible Local Destruction]", reason)
        self.assertNotIn("rm -rf build", reason, "an older turn's denial is not this pause")
        self.assertNotIn("cat plan.md", reason, "an allowed command is not a denial")
        card = self.board.get(card_id)
        self.assertTrue(card["derived"]["needs_you"])
        self.assertIn(card_id, [c["id"] for c in self.board.needs_you()])
        block = [e for e in self.board.events(card_id) if e["kind"] == "block"][-1]
        self.assertEqual((block["actor"], block["data"]), ("drain", {"paused": "permission"}))
        self.assertIn(f"blocked {card_id}: auto mode paused it", self.log_text())
        self.assertIn("denied=1", drain.summary_line(summary))
        self.assertEqual(self.fake.resumes, [], "a paused house is blocked, never put back")

    def test_the_listing_alone_is_enough(self):
        card_id = self.paused(notification=False)
        self.board.record_hook(card_id, "Stop", {"session_id": "0ld00000-0000-4000-8000-000000000000",
                                                 "transcript_path": "/old.jsonl"})
        self.once()
        reason = self.reason(card_id)
        self.assertIn("waiting for: permission prompt", reason)
        self.assertIn("did not say which commands", reason, "an older session's transcript is not read")

    def test_the_hook_alone_is_enough_when_the_listing_says_idle(self):
        card_id = self.paused(status="idle", stage="building", autonomy="autonomous")
        self.once()
        self.assertIn(f"- Bash: {SHOW_2}", self.reason(card_id))

    def test_a_pending_call_is_named(self):
        self.write(c521_turn() + [call("t5", "git stash drop")])
        card_id = self.paused()
        self.once()
        self.assertIn("Waiting on: Bash: git stash drop", self.reason(card_id))

    def test_a_busy_house_is_working(self):
        card_id = self.paused(status="busy")
        self.assertNotIn("denied", self.once())
        self.assertIsNone(self.reason(card_id))

    def test_an_idle_house_whose_turn_ended_is_the_stop_path(self):
        card_id = self.paused(status="idle", stage="building", autonomy="autonomous")
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION})
        self.once()
        self.assertIsNone(self.reason(card_id))

    def test_an_idle_prompt_is_not_a_permission_prompt(self):
        card_id = self.paused(status="idle", notification=False)
        self.board.record_hook(card_id, "Notification", {"session_id": SESSION,
                                                         "notification_type": "idle_prompt"})
        self.once()
        self.assertIsNone(self.reason(card_id))

    def test_a_block_already_there_is_his(self):
        card_id = self.paused()
        self.board.block(card_id, "I need the credentials", "house")
        self.once()
        self.assertEqual(self.reason(card_id), "I need the credentials")

    def test_a_card_at_his_gate_is_blocked_too(self):
        """c-584: at any stage with a live session. Before, only a card holding a slot
        (building, or planning before its plan) was looked at."""
        card_id = self.paused(plan_ref="p.md")
        self.once()
        self.assertIn("paused this house on a permission prompt", self.reason(card_id))


    def test_a_card_whose_session_is_not_listed_is_left_alone(self):
        card_id = self.paused(stage="review", plan_ref="p.md")
        self.fake.rows.clear()
        self.once()
        self.assertIsNone(self.reason(card_id))


    def test_a_block_in_the_old_wording_still_reads_as_the_pause(self):
        self.assertTrue(permpause.paused_block({"blocked_reason": permpause.HEAD + " (x)."}))
        self.assertFalse(permpause.paused_block({"blocked_reason": "I need the credentials"}))

    def test_a_tracking_card_is_left_alone(self):
        card_id = self.tracking(status="waiting")
        self.once()
        self.assertIsNone(self.reason(card_id))

    def test_a_filesystem_permission_denied_is_not_a_denial(self):
        self.write(c521_turn() + [call("t6", "ls /root"),
                                  result("t6", "ls: cannot open directory '/root': Permission denied")])
        card_id = self.paused()
        self.once()
        self.assertNotIn("ls /root", self.reason(card_id))

    def test_another_dialog_is_not_a_permission_pause(self):
        card_id = self.paused(waiting_for="input needed", notification=False)
        self.once()
        self.assertIsNone(self.reason(card_id))

    def test_an_idle_prompt_after_the_permission_prompt_leaves_the_hook_signal_quiet(self):
        """Signal B reads the NEWEST Notification of the turn; the listing's `waiting` is
        what still says it (signal A)."""
        card_id = self.paused(status="idle", stage="building", autonomy="autonomous")
        self.board.record_hook(card_id, "Notification", {"session_id": SESSION,
                                                         "notification_type": "idle_prompt"})
        self.once()
        self.assertIsNone(self.reason(card_id))
        for row in self.fake.rows:
            row.update(status="waiting", waitingFor="permission prompt")
        self.once()
        self.assertIsNotNone(self.reason(card_id))

    def test_a_secret_in_a_denied_command_never_reaches_the_board(self):
        self.write([user("go"),
                    call("s1", "curl -H 'Authorization: Bearer abc.def' https://x?token=s3cr3t"),
                    result("s1", DENIAL),
                    call("s2", "API_KEY=hunter2 ./deploy --password 'pw1'"), result("s2", DENIAL)])
        card_id = self.paused()
        self.once()
        reason = self.reason(card_id)
        for secret in ("abc.def", "s3cr3t", "hunter2", "pw1"):
            self.assertNotIn(secret, reason)
        self.assertIn("curl -H 'Authorization: [redacted]'", reason)
        self.assertIn("API_KEY=[redacted]", reason)
        self.assertIn("--password '[redacted]'", reason)

    def test_a_compaction_summary_does_not_start_the_turn(self):
        self.write(c521_turn()[:-2] + [user("Summary of the conversation so far", isCompactSummary=True),
                                       call("t9", "git clean -fdx"), result("t9", DENIAL)])
        card_id = self.paused()
        self.once()
        reason = self.reason(card_id)
        self.assertIn(f"- Bash: {RESET}", reason)
        self.assertIn("- Bash: git clean -fdx", reason)

    def test_a_permission_rule_denial_is_one(self):
        self.write([user("go"), call("r1", "curl x"),
                    result("r1", "Permission to use Bash has been denied because of a rule.")])
        card_id = self.paused()
        self.once()
        self.assertIn("- Bash: curl x", self.reason(card_id))


class SlotTest(PermissionPauseCase):
    """The drain counted c-521 as a live house for 30+ minutes; once blocked it holds none."""

    def test_the_blocked_house_holds_no_slot_until_it_works_again(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.assertEqual(self.once()["houses"], 0, "blocked in this pass, counted after it")
        self.assertEqual(self.once()["houses"], 0)
        for row in self.fake.rows:
            row["status"] = "busy"
        self.assertEqual(self.once()["houses"], 1, "working again, and its block cleared")
        self.assertIsNone(self.reason(card_id))

    def test_a_superseded_session_busy_does_not_give_it_a_slot(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.once()
        self.fake.rows.append(dict(background_row(card_id, "0ld00000-0000-4000-8000-000000000000"),
                                   status="busy"))
        self.assertEqual(self.once()["houses"], 0)

    def test_another_block_at_building_still_holds_one(self):
        card_id = self.housed()
        self.fake.rows.append(background_row(card_id, SESSION))
        self.board.block(card_id, "I need the credentials", "house")
        self.assertEqual(self.once()["houses"], 1)


class RecoverTest(PermissionPauseCase):
    """D1: the fallback prompt can deny by itself (c-521's third command waited 19:17:37 to
    19:20:14), and a house that carried on must not sit in his needs-you."""

    def busy(self, card_id: str) -> None:
        for row in self.fake.rows:
            if row["name"] == card_id:
                row["status"] = "busy"
                row.pop("waitingFor", None)

    def test_the_drain_clears_its_own_block_when_the_session_is_busy_again(self):
        card_id = self.paused()
        self.once()
        self.busy(card_id)
        summary = self.once()
        self.assertEqual(summary["recovered"], 1)
        self.assertIsNone(self.reason(card_id))
        self.assertIn("the drain's block is cleared", self.board.events(card_id)[-1]["text"])
        self.assertEqual(self.board.events(card_id)[-2]["kind"], "unblock")

    def test_the_old_hook_does_not_block_it_again_once_cleared(self):
        card_id = self.paused()
        self.once()
        self.busy(card_id)
        self.once()
        for row in self.fake.rows:
            row["status"] = "idle"
        self.once()
        self.assertIsNone(self.reason(card_id), "the prompt it saw was answered by the clear")

    def test_a_second_pause_blocks_again(self):
        card_id = self.paused()
        self.once()
        self.busy(card_id)
        self.once()
        for row in self.fake.rows:
            row.update(status="waiting", waitingFor="permission prompt")
        self.assertEqual(self.once()["denied"], 1)
        self.assertIsNotNone(self.reason(card_id))

    def test_a_stop_since_the_block_clears_it_though_no_pass_saw_it_busy(self):
        """The prompt denied by itself and the turn went on and ended between two passes."""
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.once()
        self.board.record_hook(card_id, "Stop", {"session_id": SESSION})
        for row in self.fake.rows:
            row.update(status="idle")
            row.pop("waitingFor", None)
        self.assertEqual(self.once()["recovered"], 1)
        self.assertIsNone(self.reason(card_id))

    def test_a_stop_from_another_session_is_not_this_one(self):
        card_id = self.paused()
        self.once()
        self.board.record_hook(card_id, "Stop", {"session_id": "0ld00000-0000-4000-8000-000000000000"})
        self.assertNotIn("recovered", self.once())
        self.assertIsNotNone(self.reason(card_id))

    def test_a_block_replaced_in_between_is_not_noted_as_cleared(self):
        card_id = self.paused()
        self.once()
        self.busy(card_id)
        card = self.board.get(card_id)
        self.board.block(card_id, "his own words", "human")
        self.assertFalse(permpause.clear(self.board, card))
        self.assertEqual(self.reason(card_id), "his own words")
        self.assertNotIn("cleared", self.board.events(card_id)[-1]["text"] or "")

    def test_a_block_that_is_not_the_drains_is_never_cleared(self):
        card_id = self.paused()
        self.once()
        self.board.block(card_id, "his own words", "human")
        self.busy(card_id)
        self.assertNotIn("recovered", self.once())
        self.assertEqual(self.reason(card_id), "his own words")

    def test_a_new_session_is_not_the_one_that_paused(self):
        card_id = self.paused()
        self.once()
        other = "22222222-0000-4000-8000-000000000022"
        self.board.set_session(card_id, other, "drain", bg_id=other[:8])
        self.fake.rows.append(dict(background_row(card_id, other), status="busy"))
        self.once()
        self.assertIsNotNone(self.reason(card_id))


class WakeTest(PermissionPauseCase):
    """A pause wakes Bosun on ANY card (c-584, `keel/pausewake.py`); nothing else does since
    driving was retired (c-593)."""

    def wakes(self, card_id):
        return [row for row in pausewake.wakes(self.board) if row["card"] == card_id]

    def test_bosun_is_woken_for_any_card_with_only_the_id_and_the_pause_named(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.once()
        found = self.wakes(card_id)
        self.assertEqual([row["state"] for row in found], ["paused"])
        prompt = pausewake.wake_prompt(found)
        self.assertIn(f"{card_id} (auto mode paused its house on a permission prompt)", prompt)
        self.assertNotIn(self.board.get(card_id)["title"], prompt)


    def test_another_block_wakes_nothing(self):
        card_id = self.housed(stage="building", autonomy="autonomous")
        self.board.block(card_id, "I need the credentials", "house")
        self.assertEqual(self.wakes(card_id), [])
        self.board.block(card_id, "house exited twice", "drain", mark="failed-resume")
        self.assertEqual(self.wakes(card_id), [], "a failed resume no longer wakes Bosun")

    def test_a_pause_wakes_once_and_a_new_one_again(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.once()
        found = self.wakes(card_id)
        pausewake.woke(self.board, [f"{card_id}@{found[0]['event']}"], "drain")
        self.assertEqual(self.wakes(card_id), [], "one pause wakes Bosun once")
        self.board.block(card_id, permpause.reason("permission prompt",
                                                   {"denied": [], "pending": None}),
                         "drain", mark=permpause.MARK)
        self.assertEqual([row["state"] for row in self.wakes(card_id)], ["paused"])

    def test_only_the_drain_records_a_wake(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        with self.assertRaises(Exception) as caught:
            pausewake.woke(self.board, [f"{card_id}@1"], "bosun")
        self.assertIn("the drain's record", str(caught.exception))

    def test_a_work_card_paused_wakes_bosun_too(self):
        card_id = self.board.create("work", "a work card", autonomy="autonomous")
        self.board.stage(card_id, "assigned", "human")
        self.board.stage(card_id, "building", "drain")
        self.board.block(card_id, permpause.reason("permission prompt",
                                                   {"denied": [], "pending": None}),
                         "drain", mark=permpause.MARK)
        self.assertEqual([row["state"] for row in self.wakes(card_id)], ["paused"])

    def test_the_drain_wakes_an_idle_bosun_once_and_records_it(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.once()
        told = []
        with mock.patch.object(drain.consolewake, "can_wake", return_value=True), \
                mock.patch.object(drain.consolewake, "wake",
                                  side_effect=lambda cfg, prompt, what: told.append(prompt) or {"session_id": "s"}), \
                mock.patch.object(drain, "log"):
            drain.pause_upkeep(self.cfg, self.board)
            drain.pause_upkeep(self.cfg, self.board)
        self.assertEqual(len(told), 1, "the second pass finds nothing new")
        self.assertIn(card_id, told[0])
        self.assertEqual([e["kind"] for e in self.board.events(card_id)][-1], "wake")

    def test_a_wake_that_did_not_happen_or_may_have_records_nothing(self):
        card_id = self.paused(stage="building", autonomy="autonomous")
        self.once()
        unclear = drain.relay.RelayUnclear("the relay took longer than 120s, so it may have sent")
        with mock.patch.object(drain.consolewake, "can_wake", return_value=True), \
                mock.patch.object(drain.consolewake, "wake", side_effect=unclear), \
                mock.patch.object(drain, "failed_step") as failed:
            drain.pause_upkeep(self.cfg, self.board)
        self.assertEqual(failed.call_args.args[2], "pause wake")
        with mock.patch.object(drain.consolewake, "can_wake", return_value=True), \
                mock.patch.object(drain.consolewake, "wake", return_value=None):
            drain.pause_upkeep(self.cfg, self.board)
        self.assertEqual([row["card"] for row in self.wakes(card_id)], [card_id])

    def test_one_wake_a_pass_the_answers_first(self):
        with mock.patch.object(drain, "answers_upkeep", return_value=True), \
                mock.patch.object(drain, "pause_upkeep") as paused:
            drain.wake_upkeep(self.cfg, self.board)
        paused.assert_not_called()
        with mock.patch.object(drain, "answers_upkeep", return_value=False), \
                mock.patch.object(drain, "pause_upkeep") as paused:
            drain.wake_upkeep(self.cfg, self.board)
        paused.assert_called_once()


class DenialsTest(PermissionPauseCase):

    def test_at_most_five_are_named_newest_last(self):
        rows = [user("go")]
        for n in range(8):
            rows += [call(f"k{n}", f"cmd {n}"), result(f"k{n}", DENIAL)]
        self.write(rows)
        found = permpause.denials(self.transcript)["denied"]
        self.assertEqual(len(found), 5)
        self.assertTrue(found[-1].startswith("Bash: cmd 7"))
