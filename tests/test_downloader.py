import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from requests.cookies import RequestsCookieJar

from eanalizer.config import AppConfig
from eanalizer.downloader import EneaDownloader


def _capture_stdout(func, *args, **kwargs):
    original_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = original_stdout
    return captured.getvalue()


class TestEneaDownloader(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.config = AppConfig(
            config_dir=self.tmp_dir / "config",
            data_dir=self.tmp_dir / "data",
            cache_dir=self.tmp_dir / "cache",
            email="user@example.com",
            password="secret",
            customer_id="12345",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_download_data_skips_when_credentials_incomplete(self):
        config = AppConfig(
            config_dir=self.tmp_dir / "config2",
            data_dir=self.tmp_dir / "data2",
            cache_dir=self.tmp_dir / "cache2",
        )
        downloader = EneaDownloader(config)

        with patch("eanalizer.downloader.requests.Session") as mock_session_class:
            output = _capture_stdout(downloader.download_data)

        mock_session_class.assert_not_called()
        self.assertIn("Dane logowania Enea nie są w pełni skonfigurowane", output)

    def test_download_data_skips_recent_file_without_force(self):
        current_year = datetime.now().year
        filename = (
            self.config.data_dir / f"12345_dane_dobowo_godzinowe_{current_year}.csv"
        )
        filename.write_text("Data;Wartosc\n", encoding="utf-8")

        downloader = EneaDownloader(self.config, force=False)
        with patch("eanalizer.downloader.requests.Session") as mock_session_class:
            output = _capture_stdout(downloader.download_data)

        mock_session_class.assert_not_called()
        self.assertIn("jest nowszy niż 1 godzina", output)

    @patch.object(EneaDownloader, "_run_download_process")
    def test_download_data_force_triggers_download(self, mock_run_process):
        current_year = datetime.now().year
        filename = (
            self.config.data_dir / f"12345_dane_dobowo_godzinowe_{current_year}.csv"
        )
        filename.write_text("Data;Wartosc\n", encoding="utf-8")

        downloader = EneaDownloader(self.config, force=True)
        _capture_stdout(downloader.download_data)

        mock_run_process.assert_called_once()

    def test_download_year_csv_skips_when_valid_for_past_year(self):
        past_year = datetime.now().year - 1
        filename = self.config.data_dir / f"12345_dane_dobowo_godzinowe_{past_year}.csv"
        filename.write_text("Data;Wartosc\n1;2\n", encoding="utf-8")

        downloader = EneaDownloader(self.config, force=False)
        mock_session = MagicMock()
        output = _capture_stdout(
            downloader._download_year_csv,
            mock_session,
            past_year,
            "POD123",
            "https://ebok.enea.pl/meter/summaryBalancingChart",
        )

        mock_session.post.assert_not_called()
        self.assertIn("już istnieje i jest prawidłowy", output)

    @patch("builtins.input", return_value="123456")
    @patch("time.sleep", return_value=None)
    @patch("eanalizer.downloader.requests.Session")
    def test_run_download_process_full_flow_writes_csv(
        self, mock_session_class, mock_sleep, mock_input
    ):
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.cookies = RequestsCookieJar()
        mock_session_class.return_value = mock_session

        login_page = MagicMock(
            url=(
                "https://eumowy.enea.pl/pl/Logowanie?client_id=asseco_ebok&"
                "redirect_uri=https%3A%2F%2Febok.enea.pl%2Fsignin-oidc&"
                "scope=openid+profile+phone&state=abc123"
            )
        )
        login_api_resp = MagicMock(status_code=200)
        code_check_resp = MagicMock(status_code=200)
        # Odpowiedź kończąca logowanie - jej treść nie ma już znaczenia, liczy
        # się tylko URL (używany przez enea_auth.looks_authenticated).
        final_login_resp = MagicMock(url="https://ebok.enea.pl/dashboard")
        many_clients_resp = MagicMock(
            text=(
                "<span>12345</span>"
                '<a href="/dashboard/select-current-client/'
                'aabbccdd-1122-3344-5566-778899aabbcc">wybierz</a>'
            ),
        )
        client_select_resp = MagicMock(text="")
        summary_page = MagicMock(
            text=(
                'data-point-of-delivery-id="POD123" '
                'data-min-date-value="2024" data-max-date-value="2024"'
            )
        )
        csv_content = "Data;Wartosc\n2024-01-01 00:00:00;1,0\n"
        csv_post_resp = MagicMock()
        csv_post_resp.json.return_value = {"data": csv_content}

        mock_session.get.side_effect = [
            login_page,
            final_login_resp,
            many_clients_resp,
            client_select_resp,
            summary_page,
        ]
        mock_session.post.side_effect = [login_api_resp, code_check_resp, csv_post_resp]

        downloader = EneaDownloader(self.config, force=True)
        _capture_stdout(downloader._run_download_process)

        output_file = self.config.data_dir / "12345_dane_dobowo_godzinowe_2024.csv"
        self.assertTrue(output_file.is_file())
        self.assertEqual(output_file.read_text(encoding="utf-8"), csv_content)
        mock_input.assert_called_once()
        # Sesja powinna zostać zapisana do pliku, by pominąć logowanie/2FA następnym razem.
        self.assertTrue(downloader._cookie_jar_path.is_file())

    @patch("time.sleep", return_value=None)
    @patch("eanalizer.downloader.requests.Session")
    def test_run_download_process_with_reused_session_landing_on_dashboard(
        self, mock_session_class, mock_sleep
    ):
        """
        Regresja: przy wznowionej sesji (z zapisanych ciasteczek) ebok.enea.pl
        potrafi przekierować od razu na /dashboard (z zapamiętanym "current
        client"), pomijając /dashboard/many-clients. _run_download_process
        musi mimo to poprawnie znaleźć GUID klienta.
        """
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.cookies = RequestsCookieJar()
        mock_session_class.return_value = mock_session

        # Sesja już zalogowana - probe w _ensure_authenticated ląduje wprost na
        # /dashboard, a nie na /dashboard/many-clients.
        authenticated_resp = MagicMock(url="https://ebok.enea.pl/dashboard")
        many_clients_resp = MagicMock(
            text=(
                "<span>12345</span>"
                '<a href="/dashboard/select-current-client/'
                'aabbccdd-1122-3344-5566-778899aabbcc">wybierz</a>'
            ),
        )
        client_select_resp = MagicMock(text="")
        summary_page = MagicMock(
            text=(
                'data-point-of-delivery-id="POD123" '
                'data-min-date-value="2024" data-max-date-value="2024"'
            )
        )
        csv_content = "Data;Wartosc\n2024-01-01 00:00:00;1,0\n"
        csv_post_resp = MagicMock()
        csv_post_resp.json.return_value = {"data": csv_content}

        mock_session.get.side_effect = [
            authenticated_resp,
            many_clients_resp,
            client_select_resp,
            summary_page,
        ]
        mock_session.post.return_value = csv_post_resp

        downloader = EneaDownloader(self.config, force=True)
        _capture_stdout(downloader._run_download_process)

        output_file = self.config.data_dir / "12345_dane_dobowo_godzinowe_2024.csv"
        self.assertTrue(output_file.is_file())
        self.assertEqual(output_file.read_text(encoding="utf-8"), csv_content)
        mock_session.post.assert_called_once()

    @patch("eanalizer.downloader.requests.Session")
    def test_ensure_authenticated_reuses_saved_session(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.cookies = RequestsCookieJar()
        authenticated_resp = MagicMock(
            url="https://ebok.enea.pl/dashboard/many-clients"
        )
        mock_session.get.return_value = authenticated_resp

        downloader = EneaDownloader(self.config)
        # Zapisana (choćby pusta) sesja powinna zostać wczytana przed próbą logowania.
        downloader._save_session_cookies(mock_session)

        output = _capture_stdout(downloader._ensure_authenticated, mock_session)

        self.assertIn("Wykorzystano zapisaną sesję", output)
        mock_session.post.assert_not_called()

    @patch("builtins.input", return_value="654321")
    @patch("eanalizer.downloader.requests.Session")
    def test_debug_mode_writes_cookie_dump(self, mock_session_class, mock_input):
        mock_session = MagicMock()
        mock_session.cookies = RequestsCookieJar()

        login_page = MagicMock(
            url=(
                "https://eumowy.enea.pl/pl/Logowanie?client_id=asseco_ebok&"
                "redirect_uri=https%3A%2F%2Febok.enea.pl%2Fsignin-oidc&"
                "scope=openid+profile+phone&state=abc123"
            )
        )
        login_api_resp = MagicMock(status_code=200)
        code_check_resp = MagicMock(status_code=200)
        final_login_resp = MagicMock(url="https://ebok.enea.pl/dashboard/many-clients")

        mock_session.get.side_effect = [login_page, final_login_resp]
        mock_session.post.side_effect = [login_api_resp, code_check_resp]

        downloader = EneaDownloader(self.config, debug=True)
        _capture_stdout(downloader._ensure_authenticated, mock_session)

        debug_path = self.config.cache_dir / "enea_cookie_debug.json"
        self.assertTrue(debug_path.is_file())

    def test_report_data_ranges_no_files(self):
        downloader = EneaDownloader(self.config)
        output = _capture_stdout(downloader._report_data_ranges)
        self.assertIn("Brak pobranych plików danych.", output)

    def test_report_data_ranges_with_real_file(self):
        target = self.config.data_dir / "12345_dane_dobowo_godzinowe_2024.csv"
        shutil.copy("tests/test_data.csv", target)

        downloader = EneaDownloader(self.config)
        output = _capture_stdout(downloader._report_data_ranges)

        self.assertIn("12345_dane_dobowo_godzinowe_2024.csv", output)


if __name__ == "__main__":
    unittest.main()
