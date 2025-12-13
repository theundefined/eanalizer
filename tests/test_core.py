import unittest
import os
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from eanalizer.data_loader import load_from_enea_csv
from eanalizer.price_fetcher import get_hourly_rce_prices
from eanalizer.core import run_rce_analysis, run_analysis_with_tariffs
from eanalizer.tariffs import TariffManager
from eanalizer.models import EnergyData
from eanalizer.config import AppConfig

# Przykładowa odpowiedź JSON z API PSE dla jednego dnia
FAKE_API_RESPONSE = {
    "value": [
        {"dtime": "2024-07-01 00:15:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 00:30:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 00:45:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 01:00:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 01:15:00", "rce_pln": 800.0},
        {"dtime": "2024-07-01 01:30:00", "rce_pln": 800.0},
        {"dtime": "2024-07-01 01:45:00", "rce_pln": 800.0},
        {"dtime": "2024-07-01 02:00:00", "rce_pln": 800.0},
    ]
}


class TestCoreFunctionality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a temporary directory to hold all test-related subdirectories
        cls.test_base_dir = tempfile.mkdtemp()

        # Create specific directories for config, data, and cache
        cls.config_dir = Path(cls.test_base_dir) / "config"
        cls.data_dir = Path(cls.test_base_dir) / "data"
        cls.cache_dir = Path(cls.test_base_dir) / "cache"

        cls.config_dir.mkdir()
        cls.data_dir.mkdir()
        cls.cache_dir.mkdir()

        # Create a dummy tariffs file inside the temporary config directory
        tariffs_path = cls.config_dir / "tariffs.csv"
        with open(tariffs_path, "w") as f:
            f.write("tariff,zone_name,day_type,start_hour,end_hour,price_per_kwh\n")
            f.write("G12w,wysoka,weekday,6,21,1.08\n")
            f.write("G12w,niska,weekday,0,6,0.76\n")
            f.write("G12w,niska,weekday,21,24,0.76\n")
            f.write("G12w,niska,weekend,0,24,0.76\n")

        # Create a test AppConfig instance with the new structure
        cls.test_config = AppConfig(
            config_dir=cls.config_dir,
            data_dir=cls.data_dir,
            cache_dir=cls.cache_dir,
        )

        cls.tariff_manager = TariffManager(
            str(cls.test_config.tariffs_file), years=range(2024, 2025)
        )
        cls.test_data = load_from_enea_csv("tests/test_data.csv")

    @classmethod
    def tearDownClass(cls):
        # Clean up the base temporary directory
        shutil.rmtree(cls.test_base_dir)

    def test_data_loading(self):
        self.assertEqual(len(self.test_data), 5)
        self.assertEqual(self.test_data[0].pobor_przed, 1.0)

    @patch("urllib.request.urlopen")
    def test_rce_fetching_and_analysis(self, mock_urlopen):
        """Testuje cały proces pobierania, cachowania i analizy cen RCE."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(FAKE_API_RESPONSE).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        test_date_str = "2024-07-01"
        cache_file = self.test_config.cache_dir / f"{test_date_str}.json"

        if os.path.exists(cache_file):
            os.remove(cache_file)

        prices = get_hourly_rce_prices(
            datetime(2024, 7, 1),
            datetime(2024, 7, 1),
            cache_dir=self.test_config.cache_dir,
        )

        mock_urlopen.assert_called_once()
        self.assertTrue(os.path.exists(cache_file))
        self.assertAlmostEqual(prices[datetime(2024, 7, 1, 0, 0)], 0.4)
        self.assertAlmostEqual(prices[datetime(2024, 7, 1, 1, 0)], 0.7)

        test_energy_data = [d for d in self.test_data if d.timestamp.day == 1]
        test_energy_data[0].timestamp = datetime(2024, 7, 1, 0, 0)
        test_energy_data[1].timestamp = datetime(2024, 7, 1, 1, 0)
        test_energy_data = test_energy_data[:2]

        import sys
        from io import StringIO

        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        run_rce_analysis(test_energy_data, prices)
        sys.stdout = original_stdout

        output = captured_output.getvalue()
        self.assertIn("SUMARYCZNY KOSZT energii pobranej: 0.40 zł", output)
        self.assertIn("SUMARYCZNY PRZYCHÓD z energii oddanej: 1.75 zł", output)

    def test_net_metering_cascade_logic(self):
        """Testuje kaskadową logikę rozliczeń net-metering między strefami."""
        test_data = [self.test_data[3], self.test_data[2]]
        test_data.append(
            EnergyData(
                timestamp=datetime(2024, 5, 2, 12, 0),
                pobor_przed=0,
                oddanie_przed=5.0,
                pobor=0,
                oddanie=5.0,
            )
        )

        import sys
        from io import StringIO

        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        run_analysis_with_tariffs(
            data=test_data,
            tariff="G12w",
            tariff_manager=self.tariff_manager,  # Pass the tariff_manager
            should_calc_optimal_capacity=False,
            daily_export_path=None,
            net_metering_ratio=0.8,
        )
        sys.stdout = original_stdout
        output = captured_output.getvalue()

        self.assertIn("Kredyt z poprzedniej strefy: 1.500 kWh", output)
        self.assertIn("Energia do opłacenia w strefie: 0.500 kWh", output)
        self.assertIn("SUMARYCZNY KOSZT ENERGII (po rozliczeniu): 0.38 zł", output)
