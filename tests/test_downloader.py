import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        filename = (
            self.config.data_dir / f"12345_dane_dobowo_godzinowe_{past_year}.csv"
        )
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

    @patch("time.sleep", return_value=None)
    @patch("eanalizer.downloader.requests.Session")
    def test_run_download_process_full_flow_writes_csv(
        self, mock_session_class, mock_sleep
    ):
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session_class.return_value = mock_session

        login_page = MagicMock(text='<input name="token" value="TOK123">')
        client_select_resp = MagicMock(text="")
        summary_page = MagicMock(
            text=(
                'data-point-of-delivery-id="POD123" '
                'data-min-date-value="2024" data-max-date-value="2024"'
            )
        )
        login_post_resp = MagicMock(
            text=(
                "<span>12345</span>"
                '<a href="/dashboard/select-current-client/'
                'aabbccdd-1122-3344-5566-778899aabbcc">wybierz</a>'
            )
        )
        csv_content = "Data;Wartosc\n2024-01-01 00:00:00;1,0\n"
        csv_post_resp = MagicMock()
        csv_post_resp.json.return_value = {"data": csv_content}

        mock_session.get.side_effect = [login_page, client_select_resp, summary_page]
        mock_session.post.side_effect = [login_post_resp, csv_post_resp]

        downloader = EneaDownloader(self.config, force=True)
        _capture_stdout(downloader._run_download_process)

        output_file = self.config.data_dir / "12345_dane_dobowo_godzinowe_2024.csv"
        self.assertTrue(output_file.is_file())
        self.assertEqual(output_file.read_text(encoding="utf-8"), csv_content)

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
