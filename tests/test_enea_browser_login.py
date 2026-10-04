import http.cookiejar
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eanalizer import enea_auth, enea_browser_login


def _cookie(name="EBOK_SESSION", value="v1", domain="ebok.enea.pl", expires=None):
    return enea_browser_login.make_cookie(
        name=name,
        value=value,
        domain=domain,
        path="/",
        secure=True,
        http_only=True,
        expires=expires,
    )


class TestMakeCookie(unittest.TestCase):
    def test_session_and_httponly_cookies_survive_lwp_roundtrip(self):
        """Ciasteczka z okna przeglądarki muszą przejść przez zapis/odczyt
        LWPCookieJar w cache - inaczej kolejne uruchomienie znów otworzy okno."""
        cookies = [
            _cookie(),
            _cookie("KEYCLOAK_SESSION", "s", ".sso.moja.enea.pl", expires=4102444800),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "jar.txt")
            jar = http.cookiejar.LWPCookieJar(path)
            for cookie in cookies:
                jar.set_cookie(cookie)
            jar.save(ignore_discard=True, ignore_expires=True)

            loaded = http.cookiejar.LWPCookieJar(path)
            loaded.load(ignore_discard=True, ignore_expires=True)

        by_name = {c.name: c for c in loaded}
        self.assertEqual(by_name["EBOK_SESSION"].domain, "ebok.enea.pl")
        self.assertIsNone(by_name["EBOK_SESSION"].expires)
        self.assertTrue(by_name["EBOK_SESSION"].has_nonstandard_attr("HttpOnly"))
        self.assertEqual(by_name["KEYCLOAK_SESSION"].domain, ".sso.moja.enea.pl")
        self.assertEqual(by_name["KEYCLOAK_SESSION"].expires, 4102444800)


class TestSubprocessHandoff(unittest.TestCase):
    """Okno działa w procesie potomnym (Qt segfaultuje przy ponownym oknie w
    tym samym procesie) - wynik wraca przez plik JSON."""

    def _fake_child(self, data, seen=None):
        def run(cmd, check, input=None, text=None):
            if seen is not None:
                seen["cmd"] = cmd
                seen["stdin"] = input
            result_path = cmd[4]
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return MagicMock(returncode=0)

        return run

    def test_cookies_and_user_agent_come_back_from_child(self):
        cookie = _cookie(expires=4102444800)
        data = {
            "logged_in": True,
            "cookies": [enea_browser_login.cookie_to_dict(cookie)],
            "user_agent": "UA okna",
        }
        with patch(
            "eanalizer.enea_browser_login.subprocess.run", self._fake_child(data)
        ):
            cookies, user_agent = enea_browser_login.login_via_browser("/tmp/profil")

        self.assertEqual(user_agent, "UA okna")
        (restored,) = cookies
        self.assertEqual(
            enea_browser_login.cookie_to_dict(restored),
            enea_browser_login.cookie_to_dict(cookie),
        )

    def test_credentials_go_through_stdin_not_command_line(self):
        seen = {}
        with patch(
            "eanalizer.enea_browser_login.subprocess.run",
            self._fake_child({"logged_in": False}, seen),
        ):
            enea_browser_login.login_via_browser(
                "/tmp/profil", email="user@example.com", password="tajne-haslo"
            )
        self.assertNotIn("tajne-haslo", " ".join(seen["cmd"]))
        self.assertEqual(
            json.loads(seen["stdin"]),
            {"email": "user@example.com", "password": "tajne-haslo"},
        )

    def test_window_closed_in_child_returns_none(self):
        with patch(
            "eanalizer.enea_browser_login.subprocess.run",
            self._fake_child({"logged_in": False}),
        ):
            self.assertIsNone(enea_browser_login.login_via_browser("/tmp/profil"))

    @patch(
        "eanalizer.enea_browser_login.subprocess.run",
        return_value=MagicMock(returncode=-11),
    )
    def test_crashed_child_raises_connection_error(self, _):
        with self.assertRaises(ConnectionError):
            enea_browser_login.login_via_browser("/tmp/profil")


class TestAutofill(unittest.TestCase):
    def test_script_embeds_credentials_as_safe_js_literal(self):
        password = 'a"b\\c</script>\'d'
        script = enea_browser_login.build_autofill_script("user@example.com", password)
        literal = json.dumps({"login": "user@example.com", "password": password})
        self.assertIn(f"var creds = {literal};", script)
        # Formularz jest tylko wypełniany - nigdy wysyłany.
        self.assertNotIn("submit", script.lower())
        self.assertNotIn(".click(", script)

    def test_fills_only_email_password_form(self):
        self.assertTrue(
            enea_browser_login.is_login_form_url(
                "https://moja.enea.pl/pl/Logowanie?client_id=asseco_ebok"
            )
        )
        self.assertFalse(
            enea_browser_login.is_login_form_url(
                "https://moja.enea.pl/pl/Logowanie/Wprowadz_kod?client_id=x"
            )
        )
        self.assertFalse(
            enea_browser_login.is_login_form_url("https://evil.example.com/pl/Logowanie")
        )


class TestCookieTracker(unittest.TestCase):
    def test_removal_of_old_value_after_overwrite_keeps_new_cookie(self):
        tracker = enea_browser_login.CookieTracker()
        tracker.added(_cookie(value="stare"))
        # Kolejność sygnałów przy nadpisaniu nie jest gwarantowana.
        tracker.added(_cookie(value="nowe"))
        tracker.removed(_cookie(value="stare"))

        self.assertEqual([c.value for c in tracker.enea_cookies()], ["nowe"])

    def test_removal_of_current_value_deletes_cookie(self):
        tracker = enea_browser_login.CookieTracker()
        tracker.added(_cookie(value="v"))
        tracker.removed(_cookie(value="v"))
        self.assertEqual(tracker.enea_cookies(), [])

    def test_only_enea_cookies_are_returned(self):
        tracker = enea_browser_login.CookieTracker()
        tracker.added(_cookie())
        tracker.added(_cookie("NID", "x", ".google.com"))
        self.assertEqual([c.name for c in tracker.enea_cookies()], ["EBOK_SESSION"])


class TestNavigationAllowList(unittest.TestCase):
    def test_allows_only_https_enea_hosts(self):
        allowed = [
            "https://ebok.enea.pl/logowanie",
            "https://moja.enea.pl/pl/Logowanie?x=1",
            "https://sso.moja.enea.pl/realms/enea/protocol/openid-connect/auth",
        ]
        blocked = [
            "http://ebok.enea.pl/",
            "https://www.google.com/",
            "https://notenea.pl/",
            "https://enea.pl.evil.example.com/",
        ]
        for url in allowed:
            self.assertTrue(enea_browser_login.is_allowed_navigation(url), url)
        for url in blocked:
            self.assertFalse(enea_browser_login.is_allowed_navigation(url), url)


class TestAvailability(unittest.TestCase):
    @patch("eanalizer.enea_browser_login.importlib.util.find_spec", return_value=None)
    def test_missing_pyqt_reports_install_command(self, _):
        reason = enea_browser_login.unavailable_reason()
        self.assertIn(enea_browser_login.INSTALL_HINT, reason)

    @patch.dict("os.environ", {}, clear=True)
    @patch("eanalizer.enea_browser_login.sys.platform", "linux")
    @patch("eanalizer.enea_browser_login.importlib.util.find_spec", return_value=object())
    def test_no_display_on_linux_is_reported(self, _):
        reason = enea_browser_login.unavailable_reason()
        self.assertIn("DISPLAY", reason)

    @patch(
        "eanalizer.enea_browser_login.unavailable_reason",
        return_value="Brak środowiska graficznego",
    )
    def test_authenticate_session_falls_back_to_import_guidance(self, _):
        with self.assertRaises(enea_auth.RecaptchaRequiredError) as ctx:
            enea_browser_login.authenticate_session(MagicMock(), "/tmp/nieuzywany")
        self.assertIn("--import-cookies", str(ctx.exception))


class TestAuthenticateSession(unittest.TestCase):
    @patch("eanalizer.enea_browser_login.unavailable_reason", return_value=None)
    @patch("eanalizer.enea_browser_login.login_via_browser")
    def test_cookies_from_window_are_verified_with_requests(self, mock_login, _):
        mock_login.return_value = ([_cookie()], "QtWebEngine UA")
        session = MagicMock()
        session.cookies = http.cookiejar.CookieJar()
        session.get.return_value = MagicMock(url="https://ebok.enea.pl/dashboard")

        result = enea_browser_login.authenticate_session(session, "/tmp/profil")

        self.assertIs(result, session.get.return_value)
        self.assertEqual([c.name for c in session.cookies], ["EBOK_SESSION"])

    @patch("eanalizer.enea_browser_login.unavailable_reason", return_value=None)
    @patch("eanalizer.enea_browser_login.login_via_browser")
    def test_retries_with_browser_user_agent_when_default_one_is_rejected(
        self, mock_login, _
    ):
        mock_login.return_value = ([_cookie()], "QtWebEngine UA")
        session = MagicMock()
        session.cookies = http.cookiejar.CookieJar()
        session.headers = {"User-Agent": "Chrome/140"}
        session.get.side_effect = [
            MagicMock(url="https://moja.enea.pl/pl/Logowanie"),
            MagicMock(url="https://ebok.enea.pl/dashboard"),
        ]

        result = enea_browser_login.authenticate_session(session, "/tmp/profil")

        self.assertEqual(result.url, "https://ebok.enea.pl/dashboard")
        self.assertEqual(session.headers["User-Agent"], "QtWebEngine UA")

    @patch("eanalizer.enea_browser_login.unavailable_reason", return_value=None)
    @patch("eanalizer.enea_browser_login.login_via_browser", return_value=None)
    def test_window_closed_by_user_raises(self, *_):
        with self.assertRaises(ConnectionError):
            enea_browser_login.authenticate_session(MagicMock(), "/tmp/profil")


class TestLoginFallback(unittest.TestCase):
    def _captcha_login_page(self):
        return MagicMock(
            url=(
                "https://moja.enea.pl/pl/Logowanie?client_id=asseco_ebok&"
                "redirect_uri=https%3A%2F%2Febok.enea.pl%2Fsignin-oidc&"
                "scope=openid+profile+phone&state=abc123"
            ),
            text='<div data-recaptchaEnabled="1"></div>',
        )

    @patch("eanalizer.enea_browser_login.authenticate_session")
    def test_captcha_opens_browser_window_when_profile_dir_given(self, mock_auth):
        session = MagicMock()
        result = enea_auth.login(
            session, "u@example.com", "p", self._captcha_login_page(),
            browser_profile_dir="/tmp/profil",
        )
        self.assertIs(result, mock_auth.return_value)
        session.post.assert_not_called()

    def test_captcha_without_profile_dir_raises_import_guidance(self):
        with self.assertRaises(enea_auth.RecaptchaRequiredError):
            enea_auth.login(MagicMock(), "u@example.com", "p", self._captcha_login_page())


if __name__ == "__main__":
    unittest.main()
