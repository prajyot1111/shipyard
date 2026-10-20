"""The drain and a space whose login has expired (lane Q, 2026-09-24): the house's own words
(Q1), the probe before a resume is spent (Q2), holding and putting back its houses and
starting none (Q3). The end-to-end reproduction with a stand-in `claude` binary is
`tests/test_login_repro.py`; these run against the fake harness and cover the branches."""

from datetime import datetime, timedelta
from unittest import mock

from keel import authority, drain, login, loginhold, logins
from keel.board import Board, Refused
from tests.helpers import SESSION, background_row
from tests.test_drain import DrainCase

EXPIRED_TEXT = "Login expired · Please run /login"
OTHER = "eeeeeeee-0000-4000-8000-00000000000e"


class LoginCase(DrainCase):
    def setUp(self):
        super().setUp()
        self.cfg.drain_paused = True
        self.start = datetime.now().astimezone()
        # The Logins list's own checks (`keel/logins.py`) probe every due dir as well; these
        # count only the hold's probes, and the list's are tests/test_logins.py's.
        patch = mock.patch.object(drain, "logins_upkeep", return_value=0)
        patch.start()
        self.addCleanup(patch.stop)

    def at(self, minutes: int) -> datetime:
        return self.start + timedelta(minutes=minutes)

    def pass_at(self, minutes: int, **kwargs) -> dict:
        at = self.at(minutes)
        with mock.patch.object(drain, "now", return_value=at), \
                mock.patch.object(self.board, "now", return_value=at.isoformat(timespec="seconds")):
            return self.once(**kwargs)

    def quiet(self, session=SESSION, said="", **kwargs) -> str:
        """Listed, idle, its turn ended with no Stop; `said` is its transcript's last words."""
        card_id = self.housed(session=session, **kwargs)
        self.fake.rows.append(background_row(card_id, session))
        self.board.record_hook(card_id, "Notification", {
            "hook_event_name": "Notification", "notification_type": "idle_prompt",
            "session_id": session, "transcript_path": f"/t/{session}.jsonl"})
        self.fake.said = said
        return card_id

    def expire(self, answer=EXPIRED_TEXT, code=1) -> None:
        self.fake.login_answer = (answer, code)

    def probes(self) -> int:
        return len(getattr(self.fake, "probes", []))

    def notes(self, card_id: str) -> list[str]:
        return [e["text"] for e in self.board.events(card_id) if e["kind"] == "note"]


class HouseWordsTest(LoginCase):
    """Q1: a turn whose own words name a lost login is a login failure, not a quiet house."""

    def test_its_words_bring_the_probe_forward_and_an_expired_login_holds_it_at_once(self):
        self.expire()
        card_id = self.quiet(said=EXPIRED_TEXT)
        summary = self.pass_at(2)
        self.assertEqual(summary["login"], 1)
        self.assertEqual(self.fake.resumes, [], "no resume attempt is spent")
        card = self.board.get(card_id)
        self.assertEqual(card["blocked_reason"],
                         login.block_reason("personal", self.cfg.spaces["personal"].config_dir))
        self.assertEqual(loginhold.held_space(self.board, card), "personal")
        self.assertIn(f"blocked {card_id}: the personal login expired", self.log_text())

    def test_words_the_probe_contradicts_leave_the_ordinary_rule_in_charge(self):
        """The login answers now, so the words were an older turn's: the quiet rule waits
        its ten minutes and spends its first attempt, as it always did."""
        card_id = self.quiet(said=EXPIRED_TEXT)
        self.assertEqual(self.pass_at(2).get("stuck", 0), 0)
        self.assertEqual(self.pass_at(11)["stuck"], 1)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.assertEqual(self.probes(), 1, "the answer taken at 2 still stands at 11")

    def test_a_probe_that_cannot_say_is_never_expired_and_spends_nothing(self):
        self.expire("You've hit your session limit · resets 9:40pm", 1)
        card_id = self.quiet(said=EXPIRED_TEXT)
        summary = self.pass_at(30)
        self.assertEqual((summary.get("stuck", 0), summary.get("login", 0)), (0, 0))
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.assertEqual(login.state_of(self.cfg, "personal"), login.UNKNOWN)
        self.assertIn("probe could not say", self.log_text())

    def test_quiet_words_that_name_nothing_do_not_probe_before_the_wait(self):
        self.quiet(said="I was rewriting the fetcher when it went quiet.")
        self.pass_at(2)
        self.assertEqual(self.probes(), 0)


class ProbeBeforeResumeTest(LoginCase):
    """Q2 in the drain: a quiet house is found, and the login is asked before a resume."""

    def test_a_due_quiet_house_in_an_expired_space_is_held_not_resumed(self):
        self.expire()
        card_id = self.quiet(said="halfway through the fetcher")
        summary = self.pass_at(11)
        self.assertEqual((summary.get("stuck", 0), summary["login"]), (0, 1))
        self.assertEqual(self.fake.resumes, [])
        self.assertTrue(self.board.get(card_id)["derived"]["needs_you"])
        self.assertFalse(any("rate limit" in note for note in self.notes(card_id)))

    def test_one_probe_per_space_in_ten_minutes_however_many_houses_ask(self):
        self.quiet(said=EXPIRED_TEXT)
        self.quiet(session=OTHER, said=EXPIRED_TEXT)
        self.pass_at(2)
        self.pass_at(5)
        self.assertEqual(self.probes(), 1)
        self.pass_at(13)
        self.assertEqual(self.probes(), 2)

    def test_the_probe_runs_under_the_space_config_dir(self):
        self.quiet(said=EXPIRED_TEXT)
        self.pass_at(2)
        self.assertEqual(self.fake.probes, [str(self.cfg.spaces["personal"].config_dir)])


class HoldAndRestoreTest(LoginCase):
    """Q3: the space's houses are held with one reason, none starts, and they come back."""

    def held(self) -> str:
        self.expire()
        card_id = self.quiet(said=EXPIRED_TEXT)
        self.pass_at(2)
        return card_id

    def test_an_exited_house_in_an_expired_space_keeps_its_resume_for_later(self):
        self.held()
        dead = self.dead("b")
        summary = self.pass_at(4)
        self.assertEqual((summary["resumed"], summary["login"]), (0, 1))
        self.assertEqual(loginhold.held_space(self.board, self.board.get(dead)), "personal")
        self.fake.login_answer = ("ok", 0)
        summary = self.pass_at(13)
        self.assertEqual(summary["relogged"], 2)
        self.assertEqual(sorted(r["session_id"][:8] for r in self.fake.resumes),
                         sorted([SESSION[:8], "bbbbbbbb"]))
        self.assertIsNone(self.board.get(dead)["blocked_reason"])

    def test_the_expired_space_starts_nothing_and_the_other_space_is_unaffected(self):
        self.cfg.drain_paused = False
        self.held()
        waiting = self.assigned("waits for the login")
        self.pass_at(3)
        self.assertEqual(self.fake.starts, [])
        self.assertEqual(self.board.get(waiting)["stage"], "assigned")
        self.assertIn(f"the personal login expired; {waiting} waits", self.log_text())
        with self.assertRaises(Refused) as refused:
            self.pass_at(3, card=waiting)
        self.assertIn("the personal login expired", str(refused.exception))
        login.record(self.cfg, "personal", {"state": login.GOOD}, self.at(4))
        login.record(self.cfg, "work", {"state": login.EXPIRED}, self.at(4))
        self.pass_at(5)
        self.assertEqual([s["name"] for s in self.fake.starts], [waiting])

    def test_it_comes_back_once_with_its_own_prompt_and_a_note(self):
        card_id = self.held()
        self.pass_at(8)
        self.assertEqual(self.fake.resumes, [], "still expired, and not probed inside ten")
        self.fake.login_answer = ("ok", 0)
        summary = self.pass_at(13)
        self.assertEqual(summary["relogged"], 1)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertIn("login had expired", self.fake.resumes[0]["prompt"])
        card = self.board.get(card_id)
        self.assertIsNone(card["blocked_reason"])
        self.assertNotIn(loginhold.HOLD_OPTION, card["options"])
        self.assertIn("login works again", self.notes(card_id)[-1])
        self.assertIn("the personal login answers again: good", self.log_text())
        self.pass_at(14)
        self.assertEqual(len(self.fake.resumes), 1)

    def test_a_card_he_unblocked_is_never_touched(self):
        card_id = self.held()
        self.board.unblock(card_id, "human")
        self.board.block(card_id, "house exited twice at building", "drain")
        self.fake.login_answer = ("ok", 0)
        self.pass_at(13)
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "house exited twice at building")

    def test_a_card_he_blocked_himself_over_the_hold_is_never_touched(self):
        card_id = self.held()
        self.board.block(card_id, "hold on, I am changing the brief", "human")
        self.fake.login_answer = ("ok", 0)
        self.pass_at(13)
        self.assertEqual(self.fake.resumes, [])
        self.assertEqual(self.board.get(card_id)["blocked_reason"], "hold on, I am changing the brief")

    def test_a_second_hold_after_he_answered_the_first_is_marked_again(self):
        """He unblocked the first hold by hand, leaving the marker; the next hold must still
        record the `set` event that is the marker, or it would never come back by itself."""
        card_id = self.held()
        self.board.unblock(card_id, "human")
        self.board.record_hook(card_id, "Notification", {
            "notification_type": "idle_prompt", "session_id": SESSION})
        self.pass_at(20)
        self.assertEqual(loginhold.held_space(self.board, self.board.get(card_id)), "personal")

    def test_a_voice_hold_taken_on_a_held_card_does_not_lose_the_login_hold(self):
        """c-651 records a `set` when a voice hold is taken; it says nothing about the login,
        so the card is still the login hold's and comes back once the login works."""
        card_id = self.held()
        self.board.hold_voice(card_id, 60)
        self.board.release_voice(card_id)
        self.assertEqual(loginhold.held_space(self.board, self.board.get(card_id)), "personal")
        self.fake.login_answer = ("ok", 0)
        self.pass_at(13)
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])

    def test_a_standing_reoffer_ask_cleared_by_the_hold_s_block_does_not_lose_it(self):
        """The hold's block drops his re-offer ask with a `set` after the block (c-651);
        that `set` is not the login's, so the hold is still recognised and put back."""
        card_id = self.housed(stage="review", plan_ref="p.md")
        self.board.approve(card_id, "outcome", "human", publish=lambda c: {"shipping": True})
        self.board.reoffer(card_id, "human")
        loginhold.hold(self.cfg, self.board, self.board.get(card_id), "personal")
        card = self.board.get(card_id)
        self.assertNotIn("reoffer", card["options"], "the block dropped the ask")
        self.assertEqual(loginhold.held_space(self.board, card), "personal")
        self.assertTrue(loginhold.restore(self.cfg, self.board, card, "personal"))
        self.assertEqual(len(self.fake.resumes), 1)
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])

    def test_a_shut_memory_gate_defers_the_comeback(self):
        card_id = self.held()
        self.cfg.memory_floor_mb, self.cfg.house_mb = 2048, 700
        self.machine.memory = 1000
        self.fake.login_answer = ("ok", 0)
        self.pass_at(13)
        self.assertEqual(self.fake.resumes, [])
        self.assertIsNotNone(self.board.get(card_id)["blocked_reason"])
        self.machine.memory = 4096
        self.pass_at(14)
        self.assertEqual(len(self.fake.resumes), 1)


class ListCheckHoldTest(DrainCase):
    """c-560: the Logins list's own check (not stubbed here) is the hold's probe too, so a
    login that worked and then expired is held on the list's answer and released once."""

    def pass_at(self, minutes: int) -> dict:
        at = self.start + timedelta(minutes=minutes)
        with mock.patch.object(drain, "now", return_value=at), \
                mock.patch.object(logins, "now", return_value=at), \
                mock.patch.object(self.board, "now", return_value=at.isoformat(timespec="seconds")):
            return self.once()

    def test_the_lists_check_holds_a_login_that_expired_and_logging_in_releases_it_once(self):
        self.start = datetime.now().astimezone()
        self.cfg.drain_paused = True
        card_id = self.housed()
        self.fake.rows.append(background_row(card_id, SESSION, status="busy"))
        self.pass_at(0)
        self.assertEqual(login.state_of(self.cfg, "personal"), login.GOOD)
        self.fake.login_answer = (EXPIRED_TEXT, 1)
        self.pass_at(24 * 60 + 1)
        self.assertEqual(login.state_of(self.cfg, "personal"), login.EXPIRED)
        probes = len(self.fake.probes)
        self.fake.rows[-1] = background_row(card_id, SESSION)
        self.board.record_hook(card_id, "Notification", {
            "hook_event_name": "Notification", "notification_type": "idle_prompt",
            "session_id": SESSION, "transcript_path": f"/t/{SESSION}.jsonl"})
        self.assertEqual(self.pass_at(24 * 60 + 2).get("login"), 1)
        self.assertEqual(len(self.fake.probes), probes, "held on the list's answer, no probe")
        self.assertEqual(loginhold.held_space(self.board, self.board.get(card_id)), "personal")
        self.assertIn("login expired", self.board.get(card_id)["blocked_reason"])
        self.fake.login_answer = ("ok", 0)
        self.assertEqual(self.pass_at(24 * 60 + 13).get("relogged"), 1)
        for minutes in (24 * 60 + 14, 24 * 60 + 25, 24 * 60 + 36):
            self.assertNotIn("login", self.pass_at(minutes))
        self.assertIsNone(self.board.get(card_id)["blocked_reason"])
        self.assertEqual(len([r for r in self.fake.resumes if "login" in r["prompt"]]), 1)


class BlockedExitedTest(DrainCase):
    def test_a_blocked_exited_house_is_blocked_once_not_every_pass(self):
        """Found building lane Q: reconcile blocked an exited house again on every pass, one
        more `block` event a poll, because it never asked whether the card was blocked."""
        card_id = self.dead()
        for _ in range(4):
            self.once()
        kinds = [e["kind"] for e in self.board.events(card_id)]
        self.assertEqual((kinds.count("resume"), kinds.count("block")), (1, 1))


class BosunHeldTest(LoginCase):
    def test_a_login_hold_on_bosun_s_card_is_released_without_a_resume(self):
        """c-647: the hold was taken before the card was Bosun's; the login works again."""
        self.board.close()
        self.board = Board(self.cfg.db_path, switches={authority.BUILDER}, builds=["keel"])
        card_id = self.dead(repo="keel")
        login.record(self.cfg, "personal", {"state": login.EXPIRED}, self.at(0))
        loginhold.hold(self.cfg, self.board, self.board.get(card_id), "personal")
        login.record(self.cfg, "personal", {"state": login.GOOD}, self.at(1))
        for minute in (2, 3):
            self.pass_at(minute)
        card = self.board.get(card_id)
        self.assertIsNone(card["blocked_reason"])
        self.assertNotIn(loginhold.HOLD_OPTION, card["options"])
        self.assertEqual((self.fake.resumes, self.fake.starts), ([], []))
        self.assertEqual(len([n for n in self.notes(card_id) if "login works again" in n]), 1)
