#!/usr/bin/env python3
"""Offline suite for the redirect_uri verifier. No network, no shared state.

WHY OFFLINE IS THE POINT, not a convenience
-------------------------------------------
Measured 2026-08-10: all ten live login rows currently emit a callback whose
origin matches its canonical origin. So a live run exercises exactly ONE origin
path (MATCH) and leaves STALE / INSECURE_SCHEME / CREDENTIALS / MALFORMED
completely uncovered — which is how the previous version shipped a probe whose
MISMATCH branch silently discarded the origin finding for eight runs. Every
verdict combination below is therefore constructed, not observed.

Every network call goes through the module-level `http_get`, which these tests
replace. If a test in here ever reaches the network, that is a bug in the code
under test, not in the test.

    python test_redirect_uri.py          # exit 0 == green
"""
import base64
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gen_redirect_handoff as gen  # noqa: E402
import probe_redirect_uri as probe  # noqa: E402

CANON = "https://ai-demo.kyloren.workers.dev"


def spec(**over):
    s = {
        "worker": "ai-demo",
        "declared": True,
        "coverage_source": "inventory",
        "expects_login": True,
        "login_paths": ["/api/auth/login"],
        "canonical_origin": CANON,
        "callback_path": "/api/auth/callback",
        "note": "",
    }
    s.update(over)
    return s


def resp(status=200, location=None, body="", error=None):
    headers = {"Content-Type": "text/html"}
    if location is not None:
        headers["Location"] = location
    return {"status": status, "headers": headers, "body": body, "error": error}


def stub(mapping, default=None):
    """URL -> response. Anything unmapped is a hard failure, not a silent 404:
    a test that probes an unexpected URL has stopped testing what it claims to."""
    def _get(url, timeout=25):
        if url in mapping:
            return mapping[url]
        if default is not None:
            return default
        raise AssertionError(f"unstubbed request: {url}")
    return _get


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


# ---------------------------------------------------------------------------
# origin normalization
# ---------------------------------------------------------------------------

class TestNormalizeOrigin(unittest.TestCase):
    def test_default_port_is_resolved(self):
        self.assertEqual(probe.normalize_origin("https://x.dev/cb"), ("https", "x.dev", 443))
        self.assertEqual(probe.normalize_origin("http://x.dev/cb"), ("http", "x.dev", 80))

    def test_explicit_default_port_equals_implicit(self):
        # The bug this replaces: comparing raw netlocs called these two
        # different origins and reported a stale_origin that did not exist.
        self.assertEqual(probe.normalize_origin("https://x.dev:443/cb"),
                         probe.normalize_origin("https://x.dev/cb"))

    def test_hostname_is_lowercased(self):
        self.assertEqual(probe.normalize_origin("https://X.DEV/cb")[1], "x.dev")

    def test_non_http_scheme_is_none(self):
        for url in ("ftp://x.dev/cb", "javascript:alert(1)", "mailto:a@b.c"):
            self.assertIsNone(probe.normalize_origin(url), url)

    def test_out_of_range_port_is_none(self):
        self.assertIsNone(probe.normalize_origin("https://x.dev:99999/cb"))

    def test_missing_host_is_none(self):
        self.assertIsNone(probe.normalize_origin("https:///cb"))
        self.assertIsNone(probe.normalize_origin(""))

    def test_origin_str_roundtrip(self):
        self.assertEqual(probe.origin_str(("https", "x.dev", 443)), "https://x.dev")
        self.assertEqual(probe.origin_str(("https", "x.dev", 8443)), "https://x.dev:8443")
        self.assertEqual(probe.origin_str(("http", "x.dev", 80)), "http://x.dev")


# ---------------------------------------------------------------------------
# callback classification — every verdict
# ---------------------------------------------------------------------------

class TestClassifyCallback(unittest.TestCase):
    def c(self, uri, canonical=CANON):
        return probe.classify_callback(uri, canonical)

    def test_match(self):
        v, p, emitted = self.c(CANON + "/api/auth/callback")
        self.assertEqual((v, p), ("MATCH", []))
        self.assertEqual(emitted, CANON)

    def test_match_with_explicit_default_port(self):
        v, p, _ = self.c("https://ai-demo.kyloren.workers.dev:443/api/auth/callback")
        self.assertEqual((v, p), ("MATCH", []))

    def test_stale_host(self):
        v, p, emitted = self.c("https://ai-demo.vercel.app/api/auth/callback")
        self.assertEqual(v, "STALE")
        self.assertIn("stale_origin", p)
        self.assertEqual(emitted, "https://ai-demo.vercel.app")

    def test_stale_port(self):
        v, p, _ = self.c("https://ai-demo.kyloren.workers.dev:8443/api/auth/callback")
        self.assertEqual(v, "STALE")
        self.assertIn("stale_origin", p)

    def test_insecure_scheme_same_host_reports_only_the_scheme(self):
        # http://x and https://x differ in effective port only BECAUSE the
        # schemes differ. A second, bogus stale_origin here trains the reader
        # to skim the reasons list.
        v, p, _ = self.c("http://ai-demo.kyloren.workers.dev/api/auth/callback")
        self.assertEqual(v, "INSECURE_SCHEME")
        self.assertEqual(p, ["insecure_scheme"])

    def test_insecure_scheme_foreign_host_reports_both(self):
        v, p, _ = self.c("http://ai-demo.vercel.app/api/auth/callback")
        self.assertEqual(v, "INSECURE_SCHEME")
        self.assertEqual(p, ["insecure_scheme", "stale_origin"])

    def test_credentials_in_uri(self):
        v, p, _ = self.c("https://user:pw@ai-demo.kyloren.workers.dev/api/auth/callback")
        self.assertEqual(v, "CREDENTIALS")
        self.assertIn("credentials_in_uri", p)

    def test_empty(self):
        for val in ("", "   ", None):
            v, p, emitted = self.c(val)
            self.assertEqual((v, p, emitted), ("MALFORMED", ["empty_redirect_uri"], None), val)

    def test_non_http_scheme(self):
        v, p, _ = self.c("javascript:alert(1)")
        self.assertEqual(v, "MALFORMED")
        self.assertIn("unparseable_or_non_http_scheme", p)

    def test_whitespace(self):
        v, p, _ = self.c("https://ai-demo.kyloren.workers.dev/api/auth/call back")
        self.assertEqual(v, "MALFORMED")
        self.assertIn("whitespace_in_uri", p)

    def test_no_canonical_declared(self):
        v, p, _ = self.c("https://whatever.dev/cb", canonical="")
        self.assertEqual(v, "MALFORMED")
        self.assertIn("no_canonical_origin_declared", p)

    def test_http_canonical_is_its_own_problem(self):
        v, p, _ = self.c("https://ai-demo.kyloren.workers.dev/cb",
                         canonical="http://ai-demo.kyloren.workers.dev")
        self.assertIn("canonical_origin_not_https", p)
        self.assertNotIn("stale_origin", p)


# ---------------------------------------------------------------------------
# the ADD value
# ---------------------------------------------------------------------------

class TestDesiredRedirectUri(unittest.TestCase):
    def test_path_comes_from_the_emitted_uri(self):
        got = probe.desired_redirect_uri(spec(), "https://dead.example/api/auth/cb2")
        self.assertEqual(got, CANON + "/api/auth/cb2")

    def test_never_equals_a_stale_emitted_uri(self):
        emitted = "https://ai-demo.vercel.app/api/auth/callback"
        self.assertNotEqual(probe.desired_redirect_uri(spec(), emitted), emitted)

    def test_falls_back_to_declared_callback_path(self):
        for emitted in (None, "", "not-a-url"):
            self.assertEqual(probe.desired_redirect_uri(spec(), emitted),
                             CANON + "/api/auth/callback", emitted)

    def test_none_without_a_usable_canonical(self):
        self.assertIsNone(probe.desired_redirect_uri(spec(canonical_origin=""), None))
        self.assertIsNone(probe.desired_redirect_uri(spec(canonical_origin="ftp://x"), None))

    def test_none_when_no_path_is_knowable(self):
        self.assertIsNone(probe.desired_redirect_uri(spec(callback_path=None), None))

    def test_trailing_slash_on_canonical_does_not_double(self):
        got = probe.desired_redirect_uri(spec(canonical_origin=CANON + "/"), None)
        self.assertEqual(got, CANON + "/api/auth/callback")


# ---------------------------------------------------------------------------
# Google host check
# ---------------------------------------------------------------------------

class TestIsGoogleAuthorize(unittest.TestCase):
    def test_exact_host_over_https(self):
        self.assertTrue(probe.is_google_authorize(
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=x"))

    def test_lookalike_suffix_is_rejected(self):
        # The old substring test accepted this and replayed our authorize URL
        # at an attacker-controlled host.
        self.assertFalse(probe.is_google_authorize(
            "https://accounts.google.com.evil.example/o/oauth2/v2/auth"))

    def test_plain_http_is_rejected(self):
        self.assertFalse(probe.is_google_authorize("http://accounts.google.com/o/oauth2/v2/auth"))

    def test_empty_is_rejected(self):
        self.assertFalse(probe.is_google_authorize(""))
        self.assertFalse(probe.is_google_authorize(None))


# ---------------------------------------------------------------------------
# login discovery
# ---------------------------------------------------------------------------

AUTHZ = ("https://accounts.google.com/o/oauth2/v2/auth?client_id=123-abc.apps."
         "googleusercontent.com&redirect_uri=" +
         CANON.replace(":", "%3A").replace("/", "%2F") + "%2Fapi%2Fauth%2Fcallback")


class TestFindAuthorize(unittest.TestCase):
    def test_found_on_a_later_path(self):
        s = spec(login_paths=["/api/auth/google/start", "/api/auth/login"])
        m = {CANON + "/api/auth/google/start": resp(404),
             CANON + "/api/auth/login": resp(302, location=AUTHZ)}
        with mock.patch.object(probe, "http_get", stub(m)):
            got = probe.find_authorize(s)
        self.assertEqual(got["login"], "FOUND")
        self.assertEqual(got["login_path"], "/api/auth/login")
        self.assertEqual(got["authorize_url"], AUTHZ)
        self.assertEqual(len(got["attempts"]), 2)

    def test_missing_when_the_host_answers_without_an_authorize(self):
        with mock.patch.object(probe, "http_get", stub({}, default=resp(404))):
            got = probe.find_authorize(spec())
        self.assertEqual(got["login"], "MISSING")
        self.assertIsNone(got["authorize_url"])

    def test_unreachable_on_transport_failure(self):
        bad = resp(0, error="URLError: getaddrinfo failed")
        with mock.patch.object(probe, "http_get", stub({}, default=bad)):
            got = probe.find_authorize(spec())
        self.assertEqual(got["login"], "UNREACHABLE")

    def test_unreachable_on_5xx(self):
        with mock.patch.object(probe, "http_get", stub({}, default=resp(503))):
            got = probe.find_authorize(spec())
        self.assertEqual(got["login"], "UNREACHABLE")

    def test_lookalike_redirect_is_not_a_login(self):
        evil = "https://accounts.google.com.evil.example/o/oauth2/v2/auth?client_id=x"
        with mock.patch.object(probe, "http_get", stub({}, default=resp(302, location=evil))):
            got = probe.find_authorize(spec())
        self.assertEqual(got["login"], "MISSING")

    def test_no_declared_paths_is_unreachable_not_a_crash(self):
        with mock.patch.object(probe, "http_get", stub({})):
            got = probe.find_authorize(spec(login_paths=[]))
        self.assertEqual(got["login"], "UNREACHABLE")
        self.assertEqual(got["attempts"], [])


# ---------------------------------------------------------------------------
# Google replay
# ---------------------------------------------------------------------------

class TestCheckGoogle(unittest.TestCase):
    def g(self, r):
        with mock.patch.object(probe, "http_get", stub({}, default=r)):
            return probe.check_google(AUTHZ)

    def test_registered_302(self):
        got = self.g(resp(302, location="https://accounts.google.com/signin/v2/identifier"))
        self.assertEqual(got["registration"], "REGISTERED")
        self.assertEqual(got["http"], 302)

    def test_registered_200_consent(self):
        self.assertEqual(self.g(resp(200, body="<html>consent</html>"))["registration"],
                         "REGISTERED")

    def test_mismatch_in_body(self):
        self.assertEqual(self.g(resp(400, body="Error 400: redirect_uri_mismatch"))["registration"],
                         "MISMATCH")

    def test_mismatch_hidden_in_base64_autherror(self):
        loc = ("https://accounts.google.com/signin/oauth/error?authError="
               + b64('{"error":"redirect_uri_mismatch"}'))
        self.assertEqual(self.g(resp(302, location=loc))["registration"], "MISMATCH")

    def test_oauth_error_without_mismatch(self):
        loc = "https://accounts.google.com/signin/oauth/error?authError=" + b64("{}")
        self.assertEqual(self.g(resp(302, location=loc))["registration"], "OAUTH_ERROR")

    def test_plain_400(self):
        self.assertEqual(self.g(resp(400, body="bad request"))["registration"], "HTTP_400_OTHER")

    def test_unknown_status_is_named_not_swallowed(self):
        self.assertEqual(self.g(resp(500))["registration"], "UNKNOWN_500")

    def test_unreachable_keeps_the_transport_error(self):
        got = self.g(resp(0, error="timeout"))
        self.assertEqual(got["registration"], "UNREACHABLE")
        self.assertEqual(got["error"], "timeout")

    def test_location_is_returned_so_no_second_request_is_needed(self):
        loc = "https://accounts.google.com/signin/v2/identifier"
        calls = []

        def counting(url, timeout=25):
            calls.append(url)
            return resp(302, location=loc)

        with mock.patch.object(probe, "http_get", counting):
            got = probe.check_google(AUTHZ)
        self.assertEqual(len(calls), 1)
        self.assertEqual(got["location"], loc)


# ---------------------------------------------------------------------------
# verdict composition — the combination matrix
# ---------------------------------------------------------------------------

def row_for(registration="REGISTERED", redirect_uri=CANON + "/api/auth/callback",
            login="FOUND", s=None):
    return probe.evaluate(
        s or spec(),
        login={"login": login, "login_path": "/api/auth/login", "login_http": 302,
               "authorize_url": AUTHZ, "attempts": []},
        registration={"registration": registration, "http": 302, "location": "", "error": None},
        callback={"client_id": "123-abc.apps.googleusercontent.com",
                  "redirect_uri": redirect_uri},
    )


class TestCompose(unittest.TestCase):
    def test_ok(self):
        r = row_for()
        self.assertEqual((r["verdict"], r["blocking"], r["reasons"]), ("OK", False, []))

    def test_registration_only(self):
        r = row_for(registration="MISMATCH")
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["reasons"], ["registration_mismatch"])
        self.assertEqual(r["origin"], "MATCH")

    def test_origin_only_registered_but_dead_host(self):
        # ai-ziyaoastro, measured 2026-08-09: registered on the client, emitting
        # a host that answers 402. Google is happy; the user is stranded.
        r = row_for(redirect_uri="https://ai-demo.vercel.app/api/auth/callback")
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["registration"], "REGISTERED")
        self.assertEqual(r["reasons"], ["origin_stale_origin"])

    def test_both_axes_are_reported_neither_masks_the_other(self):
        # THE regression this rewrite exists for. The old single `google` field
        # ranked MISMATCH above the origin finding and dropped it, so fixing the
        # console produced a green probe and a still-broken login.
        r = row_for(registration="MISMATCH",
                    redirect_uri="https://ai-demo.vercel.app/api/auth/callback")
        self.assertEqual(r["reasons"], ["registration_mismatch", "origin_stale_origin"])
        self.assertEqual(r["origin"], "STALE")

    def test_every_origin_problem_survives(self):
        r = row_for(registration="MISMATCH",
                    redirect_uri="http://ai-demo.vercel.app/api/auth/callback")
        self.assertEqual(r["reasons"],
                         ["registration_mismatch", "origin_insecure_scheme", "origin_stale_origin"])

    def test_credentials_block(self):
        r = row_for(redirect_uri="https://u:p@ai-demo.kyloren.workers.dev/api/auth/callback")
        self.assertEqual(r["reasons"], ["origin_credentials_in_uri"])

    def test_registration_unreachable_blocks(self):
        r = row_for(registration="UNREACHABLE")
        self.assertEqual(r["reasons"], ["registration_unreachable"])

    def test_login_missing_blocks(self):
        # The old NO_LOGIN verdict was EXCLUDED from the failure count, so a
        # site could lose its login endpoint and the gate still read BAD=0.
        r = probe.evaluate(spec(), login={"login": "MISSING", "attempts": []},
                           registration={"registration": "NOT_APPLICABLE"})
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertTrue(r["reasons"][0].startswith("login_missing"))

    def test_login_unreachable_blocks_with_its_own_reason(self):
        r = probe.evaluate(spec(), login={"login": "UNREACHABLE", "attempts": []},
                           registration={"registration": "NOT_APPLICABLE"})
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertTrue(r["reasons"][0].startswith("login_unreachable"))

    def test_not_applicable_is_explicit_not_an_accident(self):
        r = probe.evaluate(spec(expects_login=False, worker="ai-fleet-fly-hooks"))
        self.assertEqual((r["verdict"], r["blocking"], r["reasons"]),
                         ("NOT_APPLICABLE", False, []))
        self.assertEqual(r["registration"], "NOT_APPLICABLE")
        self.assertIsNone(r["desired_redirect_uri"])

    def test_hooks_only_service_ignores_a_supplied_callback(self):
        r = probe.evaluate(spec(expects_login=False),
                           callback={"client_id": "x", "redirect_uri": "https://evil/cb"})
        self.assertEqual(r["verdict"], "NOT_APPLICABLE")
        self.assertIsNone(r["redirect_uri"])

    def test_undeclared_service_blocks_even_when_everything_else_passes(self):
        r = row_for(s=spec(declared=False, coverage_source="cf-deploy-configs"))
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertTrue(r["reasons"][0].startswith("undeclared_service"))

    def test_unexpected_origin_verdict_still_produces_a_reason(self):
        v, blocking, reasons = probe.compose(
            spec(), login={"login": "FOUND"}, registration={"registration": "REGISTERED"},
            origin={"origin": "WEIRD", "origin_problems": []})
        self.assertEqual((v, blocking, reasons), ("BLOCKED", True, ["origin_weird"]))


# ---------------------------------------------------------------------------
# probe() end to end, still offline
# ---------------------------------------------------------------------------

class TestProbe(unittest.TestCase):
    def test_full_pass(self):
        m = {CANON + "/api/auth/login": resp(302, location=AUTHZ),
             AUTHZ: resp(302, location="https://accounts.google.com/signin/v2/identifier")}
        with mock.patch.object(probe, "http_get", stub(m)):
            r = probe.probe(spec())
        self.assertEqual(r["verdict"], "OK")
        self.assertEqual(r["client_id"], "123-abc.apps.googleusercontent.com")
        self.assertEqual(r["redirect_uri"], CANON + "/api/auth/callback")

    def test_login_failure_does_not_reach_google(self):
        calls = []

        def counting(url, timeout=25):
            calls.append(url)
            return resp(404)

        with mock.patch.object(probe, "http_get", counting):
            r = probe.probe(spec())
        self.assertEqual(r["verdict"], "BLOCKED")
        self.assertEqual(r["registration"], "NOT_APPLICABLE")
        self.assertNotIn(AUTHZ, calls)

    def test_hooks_only_service_makes_no_request_at_all(self):
        def explode(url, timeout=25):
            raise AssertionError(f"expects_login=false must not probe: {url}")

        with mock.patch.object(probe, "http_get", explode):
            r = probe.probe(spec(expects_login=False))
        self.assertEqual(r["verdict"], "NOT_APPLICABLE")


# ---------------------------------------------------------------------------
# coverage merge
# ---------------------------------------------------------------------------

class TestBuildSpecs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def inv(self):
        return {
            "default_login_paths": ["/api/auth/login"],
            "unknown_service_expects_login": True,
            "services": {
                "ai-demo": {"expects_login": True,
                            "canonical_origin": CANON,
                            "callback_path": "/api/auth/callback"},
                "ai-hooks": {"expects_login": False, "login_paths": [],
                             "canonical_origin": "https://ai-hooks.kyloren.workers.dev"},
            },
        }

    def test_inventory_only(self):
        specs = probe.build_specs(self.inv(), cfg_dir=self.cfg)
        self.assertEqual(sorted(specs), ["ai-demo", "ai-hooks"])
        self.assertEqual(specs["ai-demo"]["coverage_source"], "inventory")
        self.assertEqual(specs["ai-demo"]["login_paths"], ["/api/auth/login"])

    def test_both_sources_are_recorded(self):
        (self.cfg / "ai-demo").mkdir()
        specs = probe.build_specs(self.inv(), cfg_dir=self.cfg)
        self.assertEqual(specs["ai-demo"]["coverage_source"], "inventory+cf-deploy-configs")

    def test_deployed_but_undeclared_worker_is_added_and_blocks(self):
        # ai-trader had a deploy config and no inventory row; eight probe runs
        # never once looked at it.
        (self.cfg / "ai-stranger").mkdir()
        (self.cfg / "loose.txt").write_text("not a dir", encoding="utf-8")
        specs = probe.build_specs(self.inv(), cfg_dir=self.cfg)
        self.assertIn("ai-stranger", specs)
        self.assertNotIn("loose.txt", specs)
        s = specs["ai-stranger"]
        self.assertFalse(s["declared"])
        self.assertEqual(s["coverage_source"], "cf-deploy-configs")
        _v, blocking, reasons = probe.compose(s, login={"login": "NOT_APPLICABLE"})
        self.assertTrue(blocking)
        self.assertTrue(reasons[0].startswith("undeclared_service"))

    def test_missing_cfg_dir_is_not_fatal(self):
        specs = probe.build_specs(self.inv(), cfg_dir=self.cfg / "nope")
        self.assertEqual(sorted(specs), ["ai-demo", "ai-hooks"])

    def test_the_real_inventory_loads_and_declares_what_it_must(self):
        inv = probe.load_inventory()
        self.assertTrue(inv.get("services"))
        for name, entry in inv["services"].items():
            self.assertIn("expects_login", entry, name)
            self.assertIn("canonical_origin", entry, name)
            self.assertIsNotNone(probe.normalize_origin(entry["canonical_origin"]), name)
            if entry.get("expects_login"):
                self.assertTrue(entry.get("callback_path"), name)


# ---------------------------------------------------------------------------
# state file
# ---------------------------------------------------------------------------

class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def rows(self):
        return [row_for(),
                row_for(registration="MISMATCH"),
                probe.evaluate(spec(expects_login=False)),
                row_for(s=spec(declared=False))]

    def test_envelope_shape(self):
        p = probe.write_state(self.rows(), path=self.dir / "state.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], probe.SCHEMA_VERSION)
        self.assertEqual(data["generator"], "probe_redirect_uri.py")
        self.assertEqual(data["summary"],
                         {"total": 4, "ok": 1, "blocked": 2, "not_applicable": 1, "undeclared": 1})
        self.assertEqual(len(data["rows"]), 4)

    def test_replace_leaves_no_temp_file_behind(self):
        target = self.dir / "state.json"
        probe.write_state(self.rows(), path=target)
        probe.write_state(self.rows(), path=target)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["state.json"])

    def test_a_failed_write_does_not_replace_the_previous_state(self):
        target = self.dir / "state.json"
        probe.write_state(self.rows(), path=target)
        before = target.read_text(encoding="utf-8")
        with mock.patch.object(probe.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                probe.write_state(self.rows(), path=target)
        self.assertEqual(target.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["state.json"])


# ---------------------------------------------------------------------------
# handoff generation
# ---------------------------------------------------------------------------

def state_of(rows):
    return {"schema": gen.EXPECTED_SCHEMA, "generated_at": "2026-08-10T00:00:00+0800",
            "generator": "probe_redirect_uri.py", "summary": probe.summarize(rows),
            "rows": rows}


class TestHandoff(unittest.TestCase):
    def test_add_line_is_the_canonical_uri_never_the_stale_one(self):
        stale = "https://ai-demo.vercel.app/api/auth/callback"
        rows = [row_for(registration="MISMATCH", redirect_uri=stale)]
        text = "\n".join(gen.build_handoff(state_of(rows)))
        self.assertIn("- ADD: `" + CANON + "/api/auth/callback`", text)
        self.assertNotIn("ADD: `" + stale + "`", text)
        self.assertIn("do NOT register this", text)
        self.assertIn(stale, text)

    def test_the_flip_order_is_stated_when_the_emitted_uri_differs(self):
        rows = [row_for(registration="MISMATCH",
                        redirect_uri="https://ai-demo.vercel.app/api/auth/callback")]
        text = "\n".join(gen.build_handoff(state_of(rows)))
        self.assertIn("in that order, never before", text)

    def test_clean_row_is_listed_green_and_never_addable(self):
        text = "\n".join(gen.build_handoff(state_of([row_for()])))
        self.assertIn("`ai-demo`", text)
        self.assertNotIn("- ADD:", text)

    def test_not_applicable_row_gets_its_own_line(self):
        rows = [probe.evaluate(spec(worker="ai-hooks", expects_login=False))]
        text = "\n".join(gen.build_handoff(state_of(rows)))
        self.assertIn("No Google SSO by design", text)
        self.assertIn("`ai-hooks`", text)
        self.assertNotIn("- ADD:", text)

    def test_shared_client_is_flagged(self):
        a = row_for(registration="MISMATCH", s=spec(worker="ai-ut"))
        b = row_for(registration="MISMATCH", s=spec(worker="ai-eatery"))
        text = "\n".join(gen.build_handoff(state_of([a, b])))
        self.assertIn("**shared client** — 2 services depend on it "
                      "(ai-eatery, ai-ut). ADD ONLY.", text)
        # ONE heading for the client, both workers on it, ordered by the same
        # (priority, name) sort as everything else — not by row order. Two
        # headings would mean two operators each editing the shared client.
        self.assertIn("## ai-eatery, ai-ut", text)
        self.assertEqual(text.count("\n## ai-"), 1)
        # Both are being edited in this pass, so there is no bystander to warn about.
        self.assertNotIn("do NOT touch their lines", text)

    def test_shared_client_warns_even_when_only_one_row_is_addable(self):
        # ai-ut / ai-eatery, measured 2026-08-10: the co-tenant was CLEAN, so a
        # warning derived from the addable rows alone went silent on the one
        # client where a careless edit takes a *working* site offline. Counting
        # must span every row on the client, not just the blocked ones.
        blocked = row_for(registration="MISMATCH", s=spec(worker="ai-ut"))
        ok = row_for(s=spec(worker="ai-eatery"))
        text = "\n".join(gen.build_handoff(state_of([blocked, ok])))
        self.assertIn("**shared client** — 2 services depend on it "
                      "(ai-eatery, ai-ut). ADD ONLY.", text)
        self.assertIn("do NOT touch their lines: `ai-eatery`", text)
        # ...and the bystander is still not something to add.
        self.assertEqual(text.count("- ADD:"), 1)
        self.assertIn("## ai-ut", text)

    def test_single_tenant_client_is_not_called_shared(self):
        text = "\n".join(gen.build_handoff(state_of([row_for(registration="MISMATCH")])))
        self.assertNotIn("shared client", text)

    def test_priority_order(self):
        rows = [row_for(registration="MISMATCH", s=spec(worker=w))
                for w in ("ai-zzz", "ai-jci-taipei", "ai-fracdigi")]
        for i, r in enumerate(rows):  # distinct clients so each gets a section
            r["client_id"] = f"client-{i}"
        text = "\n".join(gen.build_handoff(state_of(rows)))
        self.assertLess(text.index("## ai-fracdigi"), text.index("## ai-jci-taipei"))
        self.assertLess(text.index("## ai-jci-taipei"), text.index("## ai-zzz"))

    def test_login_missing_row_is_visible_and_not_console_fixable(self):
        r = probe.evaluate(spec(), login={"login": "MISSING", "attempts": []},
                           registration={"registration": "NOT_APPLICABLE"})
        text = "\n".join(gen.build_handoff(state_of([r])))
        self.assertIn("## Blocked, but NOT a console problem", text)
        self.assertIn("`ai-demo` — login=MISSING", text)
        self.assertNotIn("- ADD:", text)

    def test_undeclared_row_without_a_client_is_not_console_fixable(self):
        r = probe.evaluate(spec(declared=False), login={"login": "MISSING", "attempts": []})
        text = "\n".join(gen.build_handoff(state_of([r])))
        self.assertIn("## Blocked, but NOT a console problem", text)

    def test_a_regressed_derivation_crashes_instead_of_emitting(self):
        stale = "https://ai-demo.vercel.app/api/auth/callback"
        r = row_for(registration="MISMATCH", redirect_uri=stale)
        r["desired_redirect_uri"] = stale  # simulate the old echo-the-emitted-URI bug
        with self.assertRaises(AssertionError):
            gen.build_handoff(state_of([r]))

    def test_bare_array_state_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "s.json"
            p.write_text(json.dumps([{"worker": "ai-demo"}]), encoding="utf-8")
            with self.assertRaises(SystemExit):
                gen.load_state(p)

    def test_wrong_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "s.json"
            p.write_text(json.dumps({"schema": 1, "rows": []}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                gen.load_state(p)

    def test_current_schema_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "s.json"
            p.write_text(json.dumps(state_of([row_for()])), encoding="utf-8")
            self.assertEqual(gen.load_state(p)["schema"], gen.EXPECTED_SCHEMA)

    def test_generator_and_consumer_agree_on_the_schema(self):
        self.assertEqual(gen.EXPECTED_SCHEMA, probe.SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# the control's own logic (network-free parts)
# ---------------------------------------------------------------------------

class TestControl(unittest.TestCase):
    def setUp(self):
        import control_redirect_uri
        self.ctl = control_redirect_uri

    def test_positive_control_requires_registered_AND_match(self):
        good = row_for()
        self.assertIs(self.ctl.pick_positive([good]), good)
        self.assertIsNone(self.ctl.pick_positive([row_for(registration="MISMATCH")]))
        self.assertIsNone(self.ctl.pick_positive(
            [row_for(redirect_uri="https://ai-demo.vercel.app/api/auth/callback")]))

    def test_no_positive_row_is_a_failure_not_a_pass(self):
        buf = io.StringIO()
        with mock.patch.object(self.ctl.sys, "stderr", buf):
            self.assertEqual(self.ctl.run([row_for(registration="MISMATCH")]), 2)
        self.assertIn("UNPROVEN", buf.getvalue())

    def test_negative_control_host_is_unacquirable_but_still_a_real_domain(self):
        # RFC 2606 §3: example.com is held by IANA forever, so it can never be
        # registered on one of our clients and can never be acquired by anyone.
        #
        # The ".invalid" TLD is unacquirable too, and it was WRONG here: measured
        # 2026-08-10, Google answers a .invalid redirect_uri with invalid_request
        # (a policy rejection) instead of redirect_uri_mismatch, so the negative
        # control never reached the comparison it exists to exercise. The host
        # must be syntactically real. If this is ever "hardened" back to a
        # reserved TLD, the control silently stops testing anything.
        self.assertTrue(self.ctl.BOGUS_HOST.endswith(".example.com"))
        mutated = self.ctl.mutate(CANON + "/api/auth/callback")
        self.assertEqual(mutated, f"https://{self.ctl.BOGUS_HOST}/api/auth/callback")

    def test_a_control_that_never_ran_is_two_not_one(self):
        # OAUTH_ERROR means Google rejected the request before comparing the
        # redirect_uri. That is evidence about the control, not about the probe,
        # and reporting it as 1 sends the operator hunting a probe bug.
        def fake(url, timeout=25):
            if self.ctl.BOGUS_HOST in url:
                return {"registration": "OAUTH_ERROR", "http": 302,
                        "location": "https://accounts.google.com/signin/oauth/error?authError=x",
                        "error": None}
            return {"registration": "REGISTERED", "http": 302, "location": "", "error": None}

        buf = io.StringIO()
        with mock.patch.object(self.ctl, "check_google", fake):
            with mock.patch.object(self.ctl.sys, "stderr", buf):
                rc = self.ctl.run([row_for()])
        self.assertEqual(rc, 2)
        self.assertIn("did not run", buf.getvalue())

    def test_unreachable_is_also_two(self):
        def fake(url, timeout=25):
            return {"registration": "UNREACHABLE", "http": 0, "location": "",
                    "error": "getaddrinfo failed"}

        with mock.patch.object(self.ctl, "check_google", fake):
            with mock.patch.object(self.ctl.sys, "stderr", io.StringIO()):
                self.assertEqual(self.ctl.run([row_for()]), 2)

    def test_deviation_fails_and_each_case_costs_one_request(self):
        calls = []

        def fake(url, timeout=25):
            calls.append(url)
            return {"registration": "REGISTERED", "http": 302, "location": "", "error": None}

        with mock.patch.object(self.ctl, "check_google", fake):
            with mock.patch.object(self.ctl.sys, "stderr", io.StringIO()):
                rc = self.ctl.run([row_for()])
        self.assertEqual(rc, 1)          # negative control answered REGISTERED
        self.assertEqual(len(calls), 2)  # one request per case, not two

    def test_both_controls_holding_is_the_only_zero(self):
        def fake(url, timeout=25):
            verdict = "MISMATCH" if self.ctl.BOGUS_HOST in url else "REGISTERED"
            return {"registration": verdict, "http": 302, "location": "", "error": None}

        with mock.patch.object(self.ctl, "check_google", fake):
            with mock.patch.object(self.ctl.sys, "stderr", io.StringIO()):
                self.assertEqual(self.ctl.run([row_for()]), 0)

    def test_unreachable_google_is_exit_2_not_a_pass(self):
        def fake(url, timeout=25):
            return {"registration": "UNREACHABLE", "http": 0, "location": "", "error": "dns"}

        with mock.patch.object(self.ctl, "check_google", fake):
            with mock.patch.object(self.ctl.sys, "stderr", io.StringIO()):
                self.assertEqual(self.ctl.run([row_for()]), 2)

    def test_old_state_shape_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "s.json"
            p.write_text(json.dumps([{"worker": "x"}]), encoding="utf-8")
            with mock.patch.object(self.ctl.sys, "stderr", io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.ctl.load_rows(p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
