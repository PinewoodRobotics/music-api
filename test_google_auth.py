import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.parse
from unittest import mock

import accounts
from accounts import AccountError, Google, Slack

PROFILE = {"display_name": "Ada", "image_192": "http://img/192"}
SLACK_USER = {"id": "U123", "team_id": "T1", "deleted": False, "is_bot": False, "profile": PROFILE}
GOOD = {"email": "ada@pinewood.edu", "email_verified": True, "hd": "pinewood.edu", "name": "Ada L", "picture": "http://g/pic"}


def make(userinfo=GOOD, slack_reply=None, admins=()):
    slack = Slack("cid", "sec", "xoxb-1", "http://x/cb", "T1", admins)
    google = Google("gid", "gsec", "http://x/auth/google/callback", slack)
    calls = []
    slack_reply = slack_reply or {"ok": True, "user": SLACK_USER}

    def fake(url, data=None, headers=None):
        calls.append((url, data, headers))
        if url == Google.TOKEN_URL:
            return {"access_token": "at"}
        if url == Google.USERINFO_URL:
            return userinfo
        if url.endswith("users.lookupByEmail"):
            return slack_reply
        raise AssertionError(url)
    return google, calls, fake


def start(google):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(google.login_url("/next")).query)
    return {k: v[0] for k, v in q.items()}


class GoogleTest(unittest.TestCase):
    def finish(self, google, fake, state=None, code="c"):
        q = start(google)
        with mock.patch.object(accounts, "_http_json", fake):
            return google.finish(code, state or q["state"])

    def test_authorize_url(self):
        google, _, _ = make()
        url = google.login_url("/x")
        self.assertTrue(url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
        q = start(google)
        self.assertEqual((q["hd"], q["prompt"], q["scope"], q["response_type"]), ("pinewood.edu", "select_account", "openid email profile", "code"))
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["redirect_uri"], "http://x/auth/google/callback")
        self.assertTrue(q["state"] and q["nonce"] and q["code_challenge"])

    def test_success_maps_to_slack_user(self):
        google, calls, fake = make(admins=["ada@pinewood.edu"])
        q = start(google)
        with mock.patch.object(accounts, "_http_json", fake):
            user, nxt = google.finish("c", q["state"])
        self.assertEqual(nxt, "/next")
        self.assertEqual(user, {"id": "U123", "name": "Ada", "avatar": "http://img/192", "admin": True, "kind": "slack", "via": "google"})
        token_call = next(c for c in calls if c[0] == Google.TOKEN_URL)
        form = urllib.parse.parse_qs(token_call[1].decode())
        import base64, hashlib
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, q["code_challenge"])
        self.assertEqual(form["grant_type"], ["authorization_code"])

    def test_next_path_kept_and_sanitised(self):
        google, _, fake = make()
        state = urllib.parse.parse_qs(urllib.parse.urlparse(google.login_url("/a?b=1")).query)["state"][0]
        with mock.patch.object(accounts, "_http_json", fake):
            self.assertEqual(google.finish("c", state)[1], "/a?b=1")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(google.login_url("//evil.com")).query)["state"][0]
        with mock.patch.object(accounts, "_http_json", fake):
            self.assertEqual(google.finish("c", state)[1], "/")

    def test_rejections(self):
        for bad in ({**GOOD, "email": "ada@gmail.com"}, {**GOOD, "email_verified": False},
                    {**GOOD, "hd": "other.edu"}, {**GOOD, "hd": None}, {**GOOD, "email": "ada@evil.pinewood.edu"}):
            google, _, fake = make(bad)
            with self.assertRaises(AccountError) as cm:
                self.finish(google, fake)
            self.assertIn("@pinewood.edu", str(cm.exception))

    def test_users_not_found(self):
        google, _, fake = make(slack_reply={"ok": False, "error": "users_not_found"})
        with self.assertRaises(AccountError) as cm:
            self.finish(google, fake)
        self.assertIn("isn't in the Pinewood Robotics Slack", str(cm.exception))

    def test_missing_scope(self):
        google, _, fake = make(slack_reply={"ok": False, "error": "missing_scope"})
        with mock.patch.object(sys, "stderr", io.StringIO()) as err, self.assertRaises(AccountError) as cm:
            self.finish(google, fake)
        self.assertIn("isn't fully set up", str(cm.exception))
        self.assertIn("users:read.email", err.getvalue())

    def test_deleted_bot_or_other_team(self):
        for patch in ({"deleted": True}, {"is_bot": True}, {"team_id": "T2"}):
            google, _, fake = make(slack_reply={"ok": True, "user": {**SLACK_USER, **patch}})
            with self.assertRaises(AccountError):
                self.finish(google, fake)

    def test_expired_and_reused_state(self):
        google, _, fake = make()
        state = start(google)["state"]
        google.pending[state] = (*google.pending[state][:1], time.time() - 601, *google.pending[state][2:])
        with self.assertRaises(AccountError):
            self.finish(google, fake, state=state)
        google, _, fake = make()
        self.finish(google, fake)
        with self.assertRaises(AccountError):
            google.finish("c", "nope")

    def test_configured(self):
        google, _, _ = make()
        self.assertTrue(google.configured)
        google.slack.bot_token = None
        self.assertFalse(google.configured)


if __name__ == "__main__":
    unittest.main()
