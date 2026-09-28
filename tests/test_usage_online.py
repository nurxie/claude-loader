"""The account's answer is an undocumented shape, so pin down how it is read."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import context  # noqa: F401
from claude_profiles.core import usage_online
from claude_profiles.core.config import Profile

# Trimmed from a real answer: the keys that matter, none of the empty ones.
USAGE_ANSWER = {
    "five_hour": {"utilization": 7.0, "resets_at": "2026-09-28T23:20:00.082557+00:00",
                  "limit_dollars": None, "used_dollars": None, "locked_reason": None},
    "seven_day": None,
    "seven_day_opus": None,
    "limits": [{"kind": "session", "group": "session", "percent": 7, "severity": "normal",
                "resets_at": "2026-09-28T23:20:00.082557+00:00", "is_active": True}],
}

PROFILE_ANSWER = {
    "account": {"uuid": "aaaaaaaa-1111-2222-3333-444444444444", "full_name": "Sam Example",
                "display_name": "sam", "email": "someone@example.org",
                "has_claude_max": False, "has_claude_pro": False},
    "organization": {"uuid": "bbbbbbbb-5555-6666-7777-888888888888", "name": "Example Team",
                     "organization_type": "claude_team"},
    "application": {"name": "Claude Code", "slug": "claude-code"},
}


class TestParseUsage(unittest.TestCase):
    def test_reads_the_five_hour_window(self):
        limits = usage_online.parse(USAGE_ANSWER)
        self.assertIsNotNone(limits.five_hour)
        # 7.0 is a percentage, not a fraction.
        self.assertAlmostEqual(limits.five_hour.share, 0.07)
        self.assertEqual(limits.five_hour.resets_at,
                         datetime(2026, 9, 28, 23, 20, 0, 82557, tzinfo=timezone.utc))

    def test_absent_windows_stay_absent(self):
        limits = usage_online.parse(USAGE_ANSWER)
        self.assertIsNone(limits.seven_day)
        self.assertIsNone(limits.seven_day_opus)
        self.assertFalse(limits.empty)

    def test_falls_back_to_the_limits_array(self):
        limits = usage_online.parse({"limits": USAGE_ANSWER["limits"]})
        self.assertAlmostEqual(limits.five_hour.share, 0.07)

    def test_reads_the_weekly_and_opus_windows(self):
        limits = usage_online.parse({
            "five_hour": {"utilization": 12},
            "seven_day": {"utilization": 40, "resets_at": 1790000000},
            "seven_day_opus": {"utilization": 55.5},
        })
        self.assertAlmostEqual(limits.seven_day.share, 0.40)
        self.assertAlmostEqual(limits.seven_day_opus.share, 0.555)
        self.assertEqual(limits.seven_day.resets_at.year, 2026)

    def test_used_over_limit_when_there_is_no_percentage(self):
        limits = usage_online.parse({"five_hour": {"used": 25, "limit": 100}})
        self.assertAlmostEqual(limits.five_hour.share, 0.25)

    def test_a_full_window_never_goes_over_one(self):
        limits = usage_online.parse({"five_hour": {"utilization": 140}})
        self.assertEqual(limits.five_hour.share, 1.0)

    def test_an_answer_with_nothing_in_it_is_empty(self):
        self.assertTrue(usage_online.parse({"seven_day": None, "limits": []}).empty)

    def test_a_locked_window_keeps_its_reason(self):
        limits = usage_online.parse({"five_hour": {"utilization": 100,
                                                   "locked_reason": "limit_reached"}})
        self.assertEqual(limits.five_hour.locked_reason, "limit_reached")


class TestParseAccount(unittest.TestCase):
    def test_reads_who_and_where(self):
        account = usage_online.parse_account(PROFILE_ANSWER)
        self.assertEqual(account.email, "someone@example.org")
        self.assertEqual(account.organization, "Example Team")
        self.assertEqual(account.plan, "Team")
        self.assertEqual(account.label, "someone@example.org · Example Team")
        self.assertEqual(account.key, "aaaaaaaa-1111-2222-3333-444444444444")

    def test_personal_plans_come_from_the_account_flags(self):
        answer = {"account": {"email": "me@example.org", "has_claude_max": True},
                  "organization": {"name": ""}}
        self.assertEqual(usage_online.parse_account(answer).plan, "Max")

    def test_falls_back_to_the_plan_from_the_credentials_file(self):
        account = usage_online.parse_account({"account": {"email": "me@example.org"}}, "Pro")
        self.assertEqual(account.plan, "Pro")

    def test_an_empty_answer_says_nothing(self):
        account = usage_online.parse_account({})
        self.assertEqual(account.label, "")
        self.assertEqual(account.key, "")

    def test_an_organization_named_after_the_account_is_left_out(self):
        answer = {"account": {"email": "me@example.org"},
                  "organization": {"name": "me@example.org's Organization"}}
        self.assertEqual(usage_online.parse_account(answer).label, "me@example.org")

    def test_the_key_falls_back_to_the_email(self):
        account = usage_online.parse_account({"account": {"email": "Me@Example.org"}})
        self.assertEqual(account.key, "me@example.org")


class TestMoments(unittest.TestCase):
    def test_milliseconds_and_seconds_both_work(self):
        self.assertEqual(usage_online._moment(1790648861712).year, 2026)
        self.assertEqual(usage_online._moment(1790648861).year, 2026)

    def test_a_time_without_a_zone_is_read_as_utc(self):
        self.assertEqual(usage_online._moment("2026-09-28T23:20:00").tzinfo, timezone.utc)

    def test_nonsense_is_not_a_time(self):
        self.assertIsNone(usage_online._moment("later"))
        self.assertIsNone(usage_online._moment(None))


class TestDuplicates(unittest.TestCase):
    class _Usage:
        def __init__(self, name, account):
            self.name, self.identity = name, account

    def test_finds_profiles_sharing_an_account(self):
        same = usage_online.Account(uuid="a", email="me@example.org")
        other = usage_online.Account(uuid="b", email="other@example.org")
        found = usage_online.duplicates([self._Usage("Work", same),
                                         self._Usage("Personal", same),
                                         self._Usage("Client", other),
                                         self._Usage("Unknown", None)])
        self.assertEqual(found, {"me@example.org": ["Work", "Personal"]})




class TestWhoWithoutAToken(unittest.TestCase):
    """A profile signed in through the Desktop app has no token here, but
    Claude Code still records the account in `.claude.json`."""

    def _profile(self, tmp, settings=None, credentials=None) -> Profile:
        cli = Path(tmp) / "cli"
        cli.mkdir(parents=True)
        if settings is not None:
            (cli / ".claude.json").write_text(json.dumps(settings))
        if credentials is not None:
            (cli / ".credentials.json").write_text(json.dumps(credentials))
        return Profile(id="demo", name="Demo", data_dir=tmp)

    def test_the_account_is_read_from_the_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp, {"oauthAccount": {
                "accountUuid": "u1", "emailAddress": "me@example.org",
                "displayName": "sam", "seatTier": "team_labs_standard"}})
            account = usage_online.local_account(profile)
            self.assertEqual(account.email, "me@example.org")
            self.assertEqual(account.name, "sam")
            self.assertEqual(account.plan, "Team")

    def test_a_profile_that_was_never_opened_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(usage_online.local_account(self._profile(tmp)))

    def test_settings_without_an_account_say_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp, {"machineID": "x"})
            self.assertIsNone(usage_online.local_account(profile))

    def test_a_broken_settings_file_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp)
            (Path(tmp) / "cli" / ".claude.json").write_text("{ not json")
            self.assertIsNone(usage_online.local_account(profile))

    def test_signed_in_elsewhere_is_said_differently_from_never_signed_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp, {"oauthAccount": {"emailAddress": "me@example.org"}})
            with self.assertRaises(usage_online.Unavailable) as caught:
                usage_online._credentials(profile)
            said = str(caught.exception)
            self.assertIn("me@example.org", said)
            self.assertIn("claude-demo", said)     # what to run to fix it

        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp)
            with self.assertRaises(usage_online.Unavailable) as caught:
                usage_online._credentials(profile)
            self.assertIn("not signed in yet", str(caught.exception))

    def test_a_real_token_is_used_when_there_is_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp, {"oauthAccount": {"emailAddress": "me@example.org"}},
                                    {"claudeAiOauth": {"accessToken": "secret",
                                                       "subscriptionType": "max"}})
            self.assertEqual(usage_online._credentials(profile)["accessToken"], "secret")
            self.assertEqual(usage_online.plan_name(profile), "Max")

    def test_an_expired_token_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = self._profile(tmp, None,
                                    {"claudeAiOauth": {"accessToken": "old",
                                                       "expiresAt": 1_000_000_000_000}})
            with self.assertRaises(usage_online.Unavailable) as caught:
                usage_online._token(usage_online._credentials(profile))
            self.assertIn("expired", str(caught.exception))



class TestRemembering(unittest.TestCase):
    """Answers are kept for a while; failures only briefly, because the usual
    reason for one is a profile that has just not been signed in yet."""

    def setUp(self):
        self.store = {}
        self.calls = []

    def _ask(self, value):
        def ask():
            self.calls.append(1)
            if isinstance(value, Exception):
                raise value
            return value
        return ask

    def test_an_answer_is_not_asked_for_twice(self):
        for _ in range(3):
            got = usage_online._remembered(self.store, "p", 900, False, self._ask("x"))
        self.assertEqual(got, "x")
        self.assertEqual(len(self.calls), 1)

    def test_force_asks_again(self):
        usage_online._remembered(self.store, "p", 900, False, self._ask("x"))
        usage_online._remembered(self.store, "p", 900, True, self._ask("x"))
        self.assertEqual(len(self.calls), 2)

    def test_a_failure_is_repeated_back_while_it_is_fresh(self):
        boom = usage_online.Unavailable("not signed in")
        for _ in range(2):
            with self.assertRaises(usage_online.Unavailable):
                usage_online._remembered(self.store, "p", 900, False, self._ask(boom))
        self.assertEqual(len(self.calls), 1)

    def test_a_failure_is_forgotten_long_before_an_answer_would_be(self):
        boom = usage_online.Unavailable("not signed in")
        with self.assertRaises(usage_online.Unavailable):
            usage_online._remembered(self.store, "p", 900, False, self._ask(boom),
                                     error_seconds=0)
        # Signed in since: the next ask goes through rather than waiting 15 minutes.
        got = usage_online._remembered(self.store, "p", 900, False, self._ask("x"),
                                       error_seconds=0)
        self.assertEqual(got, "x")
        self.assertEqual(len(self.calls), 2)

if __name__ == "__main__":
    unittest.main()
