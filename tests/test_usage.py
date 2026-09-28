"""Grouping messages into windows, and which source the figures come from."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import context  # noqa: F401
from claude_profiles.core import usage
from claude_profiles.core.config import Profile
from claude_profiles.core.usage_online import Limits, Window

NOON = datetime(2026, 9, 28, 12, 30, tzinfo=timezone.utc)


def entry(minutes: int, tokens: int = 100, model: str = "claude-opus-5") -> usage.Entry:
    return usage.Entry(at=NOON + timedelta(minutes=minutes), model=model, input=tokens)


class TestBlocks(unittest.TestCase):
    def test_a_window_starts_at_the_full_hour(self):
        blocks = usage.build_blocks([entry(0)])
        self.assertEqual(blocks[0].start, NOON.replace(minute=0))
        self.assertEqual(blocks[0].end, NOON.replace(minute=0) + timedelta(hours=5))

    def test_messages_within_five_hours_stay_in_one_window(self):
        blocks = usage.build_blocks([entry(0), entry(60), entry(200)])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].totals.messages, 3)

    def test_a_window_lasts_five_hours_and_then_a_new_one_opens(self):
        blocks = usage.build_blocks([entry(0), entry(5 * 60 + 1)])
        self.assertEqual(len(blocks), 2)

    def test_a_five_hour_gap_also_ends_a_window(self):
        # Inside the first window, but five quiet hours after the last message.
        blocks = usage.build_blocks([entry(0), entry(10), entry(10 + 5 * 60)])
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].totals.messages, 2)

    def test_totals_add_every_kind_of_token(self):
        e = usage.Entry(at=NOON, model="claude-opus-5", input=1, output=2,
                        cache_creation=3, cache_read=4)
        totals = usage.Totals()
        totals.add(e)
        self.assertEqual(totals.total, 10)
        self.assertEqual(totals.opus, 10)     # counted separately as an Opus total
        self.assertEqual(totals.by_model, {"claude-opus-5": 10})

    def test_nothing_in_means_nothing_out(self):
        self.assertEqual(usage.build_blocks([]), [])


class TestReadEntries(unittest.TestCase):
    """A session resumed into a second file must not be counted twice."""

    def _profile(self, root: Path) -> Profile:
        (root / "cli" / "projects" / "demo").mkdir(parents=True)
        return Profile(id="demo", name="Demo", data_dir=str(root))

    def _line(self, message_id: str, request_id: str, at: datetime, tokens: int) -> str:
        return json.dumps({
            "type": "assistant", "timestamp": at.isoformat(), "requestId": request_id,
            "message": {"id": message_id, "model": "claude-opus-5",
                        "usage": {"input_tokens": tokens, "output_tokens": 0}},
        })

    def test_the_same_message_in_two_files_is_counted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = self._profile(root)
            folder = root / "cli" / "projects" / "demo"
            shared = self._line("msg_1", "req_1", NOON, 100)
            (folder / "a.jsonl").write_text(shared + "\n")
            (folder / "b.jsonl").write_text(
                shared + "\n" + self._line("msg_2", "req_2", NOON, 50) + "\n")
            entries = usage.read_entries(profile)
            self.assertEqual(len(entries), 2)
            self.assertEqual(sum(e.total for e in entries), 150)

    def test_lines_that_are_not_assistant_messages_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = self._profile(root)
            folder = root / "cli" / "projects" / "demo"
            folder.joinpath("a.jsonl").write_text("\n".join([
                json.dumps({"type": "user", "message": {"usage": {"input_tokens": 9}}}),
                "not json at all, with a \"usage\" word in it",
                "",
                self._line("msg_1", "req_1", NOON, 7),
            ]) + "\n")
            entries = usage.read_entries(profile)
            self.assertEqual([e.total for e in entries], [7])

    def test_a_profile_with_no_history_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Profile(id="demo", name="Demo", data_dir=tmp)
            self.assertEqual(usage.read_entries(profile), [])


class TestWhichSourceWins(unittest.TestCase):
    def _local(self) -> usage.ProfileUsage:
        block = usage.Block(start=NOON.replace(minute=0))
        block.totals.add(entry(0, tokens=250))
        return usage.ProfileUsage(profile_id="p", name="P", active=block, limit=1000)

    def test_without_an_account_the_local_count_is_used(self):
        data = self._local()
        self.assertAlmostEqual(data.share, 0.25)
        self.assertEqual(data.resets_at, NOON.replace(minute=0) + timedelta(hours=5))

    def test_the_account_wins_over_the_local_count(self):
        data = self._local()
        resets = NOON + timedelta(hours=2)
        data.account = Limits(five_hour=Window(share=0.8, resets_at=resets))
        self.assertAlmostEqual(data.share, 0.8)
        self.assertEqual(data.resets_at, resets)
        self.assertEqual(data.resets_in(now=NOON), timedelta(hours=2))

    def test_a_window_is_open_when_either_source_says_so(self):
        self.assertTrue(self._local().has_window)
        account_only = usage.ProfileUsage(profile_id="p", name="P")
        self.assertFalse(account_only.has_window)
        account_only.account = Limits(five_hour=Window(share=0.1))
        self.assertTrue(account_only.has_window)

    def test_a_limit_with_no_history_is_not_a_percentage(self):
        # A budget was set by hand, but nothing has been recorded against it:
        # reading that as 0% would hide a window that may be half gone.
        data = usage.ProfileUsage(profile_id="p", name="P", limit=300_000,
                                  weekly_limit=5_000_000)
        self.assertIsNone(data.share)
        self.assertIsNone(data.weekly_share)

    def test_with_no_limit_anywhere_there_is_no_percentage(self):
        data = usage.ProfileUsage(profile_id="p", name="P")
        self.assertIsNone(data.share)
        self.assertIsNone(data.weekly_share)
        self.assertIsNone(data.resets_in())

    def test_a_reset_already_past_counts_as_zero_left(self):
        data = usage.ProfileUsage(profile_id="p", name="P")
        data.account = Limits(five_hour=Window(share=1.0, resets_at=NOON - timedelta(hours=1)))
        self.assertEqual(data.resets_in(now=NOON), timedelta(0))


class TestAlerts(unittest.TestCase):
    def _at(self, share: float, resets_at=None) -> usage.ProfileUsage:
        data = usage.ProfileUsage(profile_id="p", name="Work")
        data.account = Limits(five_hour=Window(share=share, resets_at=resets_at))
        return data

    def test_quiet_below_the_threshold(self):
        self.assertIsNone(usage.Alerts(90).due(self._at(0.89)))

    def test_speaks_once_per_window(self):
        alerts = usage.Alerts(90)
        resets = NOON + timedelta(hours=1)
        self.assertIsNotNone(alerts.due(self._at(0.91, resets)))
        self.assertIsNone(alerts.due(self._at(0.95, resets)))     # same window, already said

    def test_a_new_window_is_worth_saying_again(self):
        alerts = usage.Alerts(90)
        self.assertIsNotNone(alerts.due(self._at(0.91, NOON)))
        self.assertIsNotNone(alerts.due(self._at(0.91, NOON + timedelta(hours=5))))

    def test_zero_turns_the_warning_off(self):
        self.assertIsNone(usage.Alerts(0).due(self._at(1.0, NOON)))

    def test_nothing_to_say_without_figures(self):
        self.assertIsNone(usage.Alerts(90).due(usage.ProfileUsage(profile_id="p", name="P")))


class TestFormatting(unittest.TestCase):
    def test_token_counts_read_as_people_write_them(self):
        self.assertEqual(usage.human_tokens(999), "999")
        self.assertEqual(usage.human_tokens(1500), "1.5K")
        self.assertEqual(usage.human_tokens(2_500_000), "2.5M")
        self.assertEqual(usage.human_tokens(3_000_000_000), "3.0B")

    def test_token_counts_are_read_back(self):
        self.assertEqual(usage.parse_tokens("2.5M"), 2_500_000)
        self.assertEqual(usage.parse_tokens("400k"), 400_000)
        self.assertEqual(usage.parse_tokens("1 200 000"), 1_200_000)
        self.assertEqual(usage.parse_tokens(""), 0)
        self.assertIsNone(usage.parse_tokens("lots"))

    def test_durations_are_short(self):
        self.assertEqual(usage.human_delta(timedelta(minutes=45)), "45m")
        self.assertEqual(usage.human_delta(timedelta(hours=2, minutes=5)), "2h 05m")
        self.assertEqual(usage.human_delta(timedelta(seconds=10)), "now")
        self.assertEqual(usage.human_delta(None), "-")

    def test_model_ids_become_names(self):
        self.assertEqual(usage.short_model("claude-opus-5"), "Opus 5")
        self.assertEqual(usage.short_model("claude-sonnet-4-5-20250929"), "Sonnet 4.5")
        self.assertEqual(usage.short_model("unknown"), "Unknown")

    def test_percentages_round_to_whole_numbers(self):
        self.assertEqual(usage.percent(0.071), "7%")
        self.assertEqual(usage.percent(None), "-")


if __name__ == "__main__":
    unittest.main()
