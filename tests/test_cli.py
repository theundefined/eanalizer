import shutil
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from eanalizer.cli import main
from eanalizer.config import AppConfig


def _run_cli(argv, app_config, rce_prices=None):
    """Uruchamia main() CLI z podanymi argumentami, mockując load_config i
    get_hourly_rce_prices (by nie wykonywać realnych zapytań sieciowych do PSE),
    oraz wymuszając identycznościową funkcję i18n `_`, by asercje na tekstach
    komunikatów nie zależały od lokalnych ustawień systemowych (locale)."""
    original_argv = sys.argv
    sys.argv = ["eanalizer"] + argv
    original_stdout = sys.stdout
    sys.stdout = captured = StringIO()
    try:
        with patch("eanalizer.cli.load_config", return_value=app_config), patch(
            "eanalizer.cli.get_hourly_rce_prices", return_value=rce_prices or {}
        ), patch("eanalizer.cli._", new=lambda s: s):
            main()
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
    return captured.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.config_dir = self.tmp_dir / "config"
        self.data_dir = self.tmp_dir / "data"
        self.cache_dir = self.tmp_dir / "cache"

        tariffs_path = self.config_dir / "tariffs.csv"
        self.app_config = AppConfig(
            config_dir=self.config_dir,
            data_dir=self.data_dir,
            cache_dir=self.cache_dir,
        )
        tariffs_path.write_text(
            "tariff,zone_name,day_type,start_hour,end_hour,energy_price,dist_price,dist_fee\n"
            "G11,stala,all,0,24,0.6,0.3,40.0\n"
            "G12,dzienna,all,6,22,0.7,0.4,46.0\n"
            "G12,nocna,all,22,6,0.4,0.2,46.0\n",
            encoding="utf-8",
        )
        shutil.copy("tests/test_data.csv", self.data_dir / "test_data.csv")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_no_files_found(self):
        empty_data_dir = self.tmp_dir / "empty_data"
        empty_data_dir.mkdir()
        output = _run_cli(["--katalog", str(empty_data_dir)], self.app_config)
        self.assertIn("No .csv files found for processing", output)

    def test_single_analysis_prints_summary(self):
        output = _run_cli(
            ["--katalog", str(self.data_dir), "--taryfa", "G11"], self.app_config
        )
        self.assertIn("Analiza zużycia i kosztów", output)
        self.assertIn("SUMARYCZNY KOSZT", output)

    def test_rce_mode_warns_about_ignored_storage_flags(self):
        output = _run_cli(
            [
                "--katalog",
                str(self.data_dir),
                "--z-cenami-rce",
                "--magazyn-fizyczny",
                "10",
                "--z-netmetering",
            ],
            self.app_config,
        )
        self.assertIn(
            "tryb --z-cenami-rce nie obsługuje symulacji magazynu ani net-meteringu",
            output,
        )

    def test_rce_mode_no_warning_without_storage_flags(self):
        output = _run_cli(
            ["--katalog", str(self.data_dir), "--z-cenami-rce"], self.app_config
        )
        self.assertNotIn("nie obsługuje symulacji magazynu", output)

    def test_tariff_comparison_warns_about_ignored_export_flags(self):
        output = _run_cli(
            [
                "--katalog",
                str(self.data_dir),
                "--porownaj-taryfy",
                "--eksport-dzienny",
                str(self.tmp_dir / "out.csv"),
            ],
            self.app_config,
        )
        self.assertIn(
            "tryb --porownaj-taryfy nie obsługuje eksportu danych",
            output,
        )
        self.assertIn("Porównanie taryf", output)

    def test_tariff_comparison_no_warning_without_extra_flags(self):
        output = _run_cli(
            ["--katalog", str(self.data_dir), "--porownaj-taryfy"], self.app_config
        )
        self.assertNotIn("nie obsługuje eksportu", output)
        self.assertIn("Porównanie taryf", output)


if __name__ == "__main__":
    unittest.main()
