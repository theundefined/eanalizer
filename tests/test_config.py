import configparser
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eanalizer.config import (
    AppConfig,
    _get_default_dir,
    _get_dev_root,
    _prompt_for_enea_credentials,
    load_config,
)


class TestAppConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_config(self, **overrides):
        defaults = {
            "config_dir": self.tmp_dir / "config",
            "data_dir": self.tmp_dir / "data",
            "cache_dir": self.tmp_dir / "cache",
        }
        defaults.update(overrides)
        return AppConfig(**defaults)

    def test_post_init_creates_directories(self):
        config_dir = self.tmp_dir / "config"
        data_dir = self.tmp_dir / "data"
        cache_dir = self.tmp_dir / "cache"
        self.assertFalse(config_dir.exists())

        self._make_config(config_dir=config_dir, data_dir=data_dir, cache_dir=cache_dir)

        self.assertTrue(config_dir.is_dir())
        self.assertTrue(data_dir.is_dir())
        self.assertTrue(cache_dir.is_dir())

    def test_tariffs_file_and_config_file_properties(self):
        cfg = self._make_config()
        self.assertEqual(cfg.tariffs_file, cfg.config_dir / "tariffs.csv")
        self.assertEqual(cfg.config_file, cfg.config_dir / "config.ini")

    def test_save_writes_paths_and_credentials(self):
        cfg = self._make_config(
            email="test@example.com", password="secret", customer_id="12345"
        )
        cfg.save()

        parser = configparser.ConfigParser()
        parser.read(cfg.config_file, encoding="utf-8")
        self.assertEqual(parser["paths"]["data_dir"], str(cfg.data_dir))
        self.assertEqual(parser["enea_credentials"]["email"], "test@example.com")
        self.assertEqual(parser["enea_credentials"]["customer_id"], "12345")

    def test_save_without_credentials_omits_credentials_section(self):
        cfg = self._make_config()
        cfg.save()

        parser = configparser.ConfigParser()
        parser.read(cfg.config_file, encoding="utf-8")
        self.assertIn("paths", parser)
        self.assertNotIn("enea_credentials", parser)

    def test_save_preserves_existing_unrelated_sections(self):
        cfg = self._make_config()
        cfg.config_file.write_text("[custom]\nfoo = bar\n", encoding="utf-8")

        cfg.save()

        parser = configparser.ConfigParser()
        parser.read(cfg.config_file, encoding="utf-8")
        self.assertEqual(parser["custom"]["foo"], "bar")
        self.assertIn("paths", parser)


class TestGetDefaultDir(unittest.TestCase):
    def test_dev_env_paths_are_independent_of_cwd(self):
        """
        Regresja: wykrywanie środowiska dev (i co za tym idzie domyślne
        ścieżki config/data/cache) nie może zależeć od katalogu roboczego
        procesu, tylko od lokalizacji samego pakietu - inaczej przypadkowy
        plik pyproject.toml w katalogu, z którego uruchomiono zainstalowane
        (np. przez pipx) narzędzie, przełączyłby ścieżki na ten obcy katalog.
        """
        expected_root = _get_dev_root()
        self.assertIsNotNone(expected_root)

        fake_project = Path(tempfile.mkdtemp())
        try:
            (fake_project / "pyproject.toml").write_text(
                "[project]\n", encoding="utf-8"
            )
            original_cwd = os.getcwd()
            os.chdir(fake_project)
            try:
                data_dir = _get_default_dir("data")
            finally:
                os.chdir(original_cwd)

            self.assertEqual(data_dir, expected_root / "data")
            self.assertNotEqual(data_dir, fake_project / "data")
        finally:
            shutil.rmtree(fake_project, ignore_errors=True)

    def test_unknown_dir_type_raises(self):
        with self.assertRaises(ValueError):
            _get_default_dir("nieistniejacy_typ")


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_valid_paths_ini(self, config_dir: Path, data_dir: Path, cache_dir: Path):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.ini").write_text(
            "[paths]\n"
            f"config_dir = {config_dir}\n"
            f"data_dir = {data_dir}\n"
            f"cache_dir = {cache_dir}\n",
            encoding="utf-8",
        )

    @patch("eanalizer.config._get_default_dir")
    def test_load_config_with_valid_existing_config_does_not_prompt(
        self, mock_get_default_dir
    ):
        config_dir = self.tmp_dir / "config"
        data_dir = self.tmp_dir / "data"
        cache_dir = self.tmp_dir / "cache"
        self._write_valid_paths_ini(config_dir, data_dir, cache_dir)
        mock_get_default_dir.return_value = config_dir

        app_cfg = load_config(require_credentials=False, prompt_for_missing=True)

        self.assertEqual(app_cfg.config_dir, config_dir)
        self.assertEqual(app_cfg.data_dir, data_dir)
        self.assertEqual(app_cfg.cache_dir, cache_dir)
        # load_config powinien również zasiać domyślny plik taryf, jeśli brak.
        self.assertTrue(app_cfg.tariffs_file.is_file())

    @patch("eanalizer.config._get_default_dir")
    def test_load_config_raises_when_missing_and_prompt_disabled(
        self, mock_get_default_dir
    ):
        config_dir = self.tmp_dir / "empty_config"
        config_dir.mkdir()
        mock_get_default_dir.return_value = config_dir

        with self.assertRaises(FileNotFoundError):
            load_config(require_credentials=False, prompt_for_missing=False)

    @patch("eanalizer.config._get_default_dir")
    def test_load_config_raises_when_credentials_required_but_missing(
        self, mock_get_default_dir
    ):
        config_dir = self.tmp_dir / "config_no_creds"
        data_dir = self.tmp_dir / "data_no_creds"
        cache_dir = self.tmp_dir / "cache_no_creds"
        self._write_valid_paths_ini(config_dir, data_dir, cache_dir)
        mock_get_default_dir.return_value = config_dir

        with self.assertRaises(ValueError):
            load_config(require_credentials=True, prompt_for_missing=False)


class TestPromptForEneaCredentials(unittest.TestCase):
    @patch("builtins.input")
    @patch("eanalizer.config.getpass.getpass", return_value="secret")
    @patch("eanalizer.config.requests.Session")
    def test_single_valid_customer_selected_automatically(
        self, mock_session_class, mock_getpass, mock_input
    ):
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session_class.return_value = mock_session

        # Nowy flow logowania Enea (OIDC/eumowy.enea.pl + kod 2FA) - patrz enea_auth.py.
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
        many_clients_resp = MagicMock(
            text=(
                "<span>12345</span>"
                '<a href="/dashboard/select-current-client/'
                'aabbccdd-1122-3344-5566-778899aabbcc">wybierz</a>'
            ),
        )
        client_select_resp = MagicMock()
        summary_page = MagicMock(text='data-point-of-delivery-id="POD123"')

        mock_session.get.side_effect = [
            login_page,
            final_login_resp,
            many_clients_resp,
            client_select_resp,
            summary_page,
        ]
        mock_session.post.side_effect = [login_api_resp, code_check_resp]
        # Kolejne wywołania input(): najpierw email, potem kod weryfikacyjny 2FA.
        mock_input.side_effect = ["user@example.com", "123456"]

        creds = _prompt_for_enea_credentials()

        self.assertEqual(
            creds,
            {
                "email": "user@example.com",
                "password": "secret",
                "customer_id": "12345",
            },
        )

    @patch("builtins.input", return_value="user@example.com")
    @patch("eanalizer.config.getpass.getpass", return_value="secret")
    @patch("eanalizer.config.requests.Session")
    def test_raises_system_exit_when_no_customers_found(
        self, mock_session_class, mock_getpass, mock_input
    ):
        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session_class.return_value = mock_session

        # Sesja już zalogowana (np. z zapisanych ciasteczek) - brak profili klientów w treści.
        authenticated_resp = MagicMock(
            url="https://ebok.enea.pl/dashboard/many-clients", text=""
        )
        mock_session.get.return_value = authenticated_resp

        with self.assertRaises(SystemExit):
            _prompt_for_enea_credentials()


if __name__ == "__main__":
    unittest.main()
