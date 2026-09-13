import json
import unittest
from unittest.mock import MagicMock, patch

from requests.cookies import RequestsCookieJar

from eanalizer import enea_auth


class TestInteractiveLogin(unittest.TestCase):
    def _make_session(self, login_api_resp, code_check_resp, final_login_resp):
        session = MagicMock()
        session.cookies = RequestsCookieJar()
        session.post.side_effect = [login_api_resp, code_check_resp]
        session.get.return_value = final_login_resp
        return session

    @patch("builtins.input", return_value="123456")
    def test_derives_api_host_from_login_page_redirect(self, mock_input):
        """
        Regresja: host formularza logowania się przenosił raz już (sierpień 2026:
        ebok.enea.pl -> eumowy.enea.pl; wrzesień 2026: eumowy.enea.pl ->
        moja.enea.pl). Host API logowania/2FA musi być wyliczany z faktycznego
        URL-a przekierowania, a nie zahardkodowany, inaczej kolejna przeprowadzka
        Enei znów wywali logowanie.
        """
        login_page = MagicMock(
            url=(
                "https://moja.enea.pl/pl/Logowanie?client_id=asseco_ebok&"
                "redirect_uri=https%3A%2F%2Febok.enea.pl%2Fsignin-oidc&"
                "scope=openid+profile+phone&state=abc123"
            )
        )
        login_api_resp = MagicMock(status_code=200)
        code_check_resp = MagicMock(status_code=200)
        final_login_resp = MagicMock(url="https://ebok.enea.pl/dashboard")
        session = self._make_session(login_api_resp, code_check_resp, final_login_resp)

        result = enea_auth.interactive_login(
            session, "user@example.com", "secret", login_page
        )

        self.assertIs(result, final_login_resp)
        login_call, code_check_call = session.post.call_args_list
        self.assertEqual(
            login_call.args[0], "https://moja.enea.pl/api/login/login"
        )
        self.assertEqual(
            code_check_call.args[0], "https://moja.enea.pl/api/login/code/check"
        )
        login_payload = json.loads(login_call.kwargs["data"])
        self.assertEqual(login_payload["login"], "user@example.com")
        self.assertEqual(login_payload["password"], "secret")

    def test_rejects_unexpected_login_host(self):
        login_page = MagicMock(
            url="https://ktos-inny.example.com/pl/Logowanie?state=abc123"
        )
        session = MagicMock()

        with self.assertRaises(ConnectionError):
            enea_auth.interactive_login(
                session, "user@example.com", "secret", login_page
            )
        session.post.assert_not_called()

    @patch("builtins.input", return_value="123456")
    def test_debug_dumps_raw_api_responses(self, mock_input):
        login_page = MagicMock(
            url=(
                "https://moja.enea.pl/pl/Logowanie?client_id=asseco_ebok&"
                "redirect_uri=https%3A%2F%2Febok.enea.pl%2Fsignin-oidc&"
                "scope=openid+profile+phone&state=abc123"
            )
        )
        login_api_resp = MagicMock(status_code=200)
        login_api_resp.json.return_value = {"ok": True}
        code_check_resp = MagicMock(status_code=200)
        code_check_resp.json.return_value = {"smsAttemptsLeft": 7}
        final_login_resp = MagicMock(url="https://ebok.enea.pl/dashboard")
        session = self._make_session(login_api_resp, code_check_resp, final_login_resp)

        with patch("builtins.print") as mock_print:
            enea_auth.interactive_login(
                session, "user@example.com", "secret", login_page, debug=True
            )

        debug_lines = [
            call.args[0] for call in mock_print.call_args_list if call.args
        ]
        self.assertTrue(any("login/login" in line for line in debug_lines))
        self.assertTrue(
            any("smsAttemptsLeft" in line for line in debug_lines)
        )

    def test_already_authenticated_skips_login(self):
        login_page = MagicMock(url="https://ebok.enea.pl/dashboard")
        session = MagicMock()

        result = enea_auth.interactive_login(
            session, "user@example.com", "secret", login_page
        )

        self.assertIs(result, login_page)
        session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
