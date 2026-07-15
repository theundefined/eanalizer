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
import pandas as pd
from eanalizer.core import (
    run_rce_analysis,
    run_full_analysis,
    run_tariff_comparison,
    print_analysis_summary,
    calculate_optimal_capacity,
    find_missing_hours,
)
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
            f.write(
                "tariff,zone_name,day_type,start_hour,end_hour,energy_price,dist_price,dist_fee\n"
            )
            f.write("G12w,szczytowa,weekday,6,21,0.78,0.30,10.0\n")
            f.write("G12w,pozaszczytowa,weekday,0,6,0.46,0.30,10.0\n")
            f.write("G12w,pozaszczytowa,weekday,21,24,0.46,0.30,10.0\n")
            f.write("G12w,pozaszczytowa,weekend,0,24,0.46,0.30,10.0\n")

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

    @patch("urllib.request.urlopen")
    def test_rce_fetch_failure_is_not_cached(self, mock_urlopen):
        """
        Testuje, że nieudane pobranie cen RCE (błąd sieci/API) nie jest trwale
        zapisywane w cache jako pusty wynik - kolejne uruchomienie musi
        spróbować pobrać dane ponownie, zamiast na stałe zakładać ich brak.
        """
        test_date_str = "2024-08-01"
        cache_file = self.test_config.cache_dir / f"{test_date_str}.json"
        if cache_file.exists():
            cache_file.unlink()

        mock_urlopen.side_effect = ConnectionError("Connection error")
        prices = get_hourly_rce_prices(
            datetime(2024, 8, 1),
            datetime(2024, 8, 1),
            cache_dir=self.test_config.cache_dir,
        )
        self.assertEqual(prices, {})
        self.assertFalse(cache_file.exists())

        # Kolejne uruchomienie (np. po odzyskaniu łączności) musi ponownie
        # spróbować pobrać dane, a nie polegać na trwale "zatrutym" cache.
        mock_urlopen.side_effect = None
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(
            {
                "value": [
                    {"dtime": "2024-08-01 00:15:00", "rce_pln": 400.0},
                    {"dtime": "2024-08-01 00:30:00", "rce_pln": 400.0},
                ]
            }
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        prices = get_hourly_rce_prices(
            datetime(2024, 8, 1),
            datetime(2024, 8, 1),
            cache_dir=self.test_config.cache_dir,
        )
        self.assertEqual(mock_urlopen.call_count, 2)
        self.assertTrue(cache_file.exists())
        self.assertIn(datetime(2024, 8, 1, 0, 0), prices)

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

        summary, _ = run_full_analysis(
            data=test_data,
            capacity=0,
            tariff="G12w",
            tariff_manager=self.tariff_manager,  # Pass the tariff_manager
            net_metering_ratio=0.8,
        )
        print_analysis_summary(summary, 0, "G12w", 0.8)

        sys.stdout = original_stdout
        output = captured_output.getvalue()

        # Wysoka: oddanie 5 * 0.8 = 4. Pobor 2.5. Rollover 1.5
        # Niska: pobor 2.0. Kredyt 1.5. Do zaplaty 0.5. Koszt 0.5 * 0.76 = 0.38
        self.assertIn("Kredyt z poprzedniej strefy: 1.500 kWh", output)
        self.assertIn("Energia do opłacenia w strefie: 0.500 kWh", output)
        self.assertIn("SUMARYCZNY KOSZT (po rozliczeniu): 10.38 zł", output)

    def test_optimal_capacity_g12w_arbitrage_on_net_export_day(self):
        """
        Testuje obliczanie pojemności dla arbitrażu nawet w dniu,
        który jest ogólnie dniem eksportu netto.
        """
        # Net-export day, but with consumption during the high-price zone
        test_data = [
            EnergyData(
                timestamp=datetime(2024, 5, 2, 12, 0),
                pobor_przed=5.0,
                oddanie_przed=0.0,
                pobor=5.0,
                oddanie=0.0,
            ),
            EnergyData(
                timestamp=datetime(2024, 5, 2, 4, 0),
                pobor_przed=0.0,
                oddanie_przed=10.0,
                pobor=0.0,
                oddanie=10.0,
            ),
        ]
        # Daily data: pobor=5, oddanie=10 -> net export
        daily_df = pd.DataFrame(
            [
                {
                    "date": datetime(2024, 5, 2).date(),
                    "pobor_przed": 5.0,
                    "oddanie_przed": 10.0,
                    "pobor": 0.0,
                    "oddanie": 5.0,
                }
            ]
        )

        import sys
        from io import StringIO

        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        calculate_optimal_capacity(
            hourly_data=test_data,
            daily_data=daily_df,
            tariff_manager=self.tariff_manager,
            tariff="G12w",
        )

        sys.stdout = original_stdout
        output = captured_output.getvalue()

        # The capacity for arbitrage should still be 5.0, as this is the consumption
        # in the high-price zone that could be shifted.
        self.assertIn("Pojemność wymagana dla arbitrażu taryfowego: 5.000 kWh", output)

    def test_find_missing_hours_annotates_dst_spring_gap(self):
        """
        Brak godziny w dniu zmiany czasu na letni (ostatnia niedziela marca) powinien
        być oznaczony jako prawdopodobnie oczekiwany, a nie zwykły błąd w danych.
        """
        # 2023-03-26 to ostatnia niedziela marca (zmiana czasu); godzina 01:00 nie istnieje.
        test_data = [
            EnergyData(
                timestamp=datetime(2023, 3, 26, hour),
                pobor_przed=0,
                oddanie_przed=0,
                pobor=0,
                oddanie=0,
            )
            for hour in range(24)
            if hour != 1
        ]

        import sys
        from io import StringIO

        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        find_missing_hours(test_data, "2023-03-26", "2023-03-26")
        sys.stdout = original_stdout

        output = captured_output.getvalue()
        self.assertIn("Brak danych dla godziny: 2023-03-26 01:00", output)
        self.assertIn(
            "2023-03-26 01:00 (prawdopodobnie zmiana czasu na letni, a nie błąd w danych)",
            output,
        )

    def test_find_missing_hours_does_not_annotate_regular_gap(self):
        """Zwykły brak danych (poza dniem zmiany czasu) nie powinien mieć adnotacji o DST."""
        test_data = [
            EnergyData(
                timestamp=datetime(2023, 6, 15, hour),
                pobor_przed=0,
                oddanie_przed=0,
                pobor=0,
                oddanie=0,
            )
            for hour in range(24)
            if hour != 10
        ]

        import sys
        from io import StringIO

        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        find_missing_hours(test_data, "2023-06-15", "2023-06-15")
        sys.stdout = original_stdout

        output = captured_output.getvalue()
        self.assertIn("Brak danych dla godziny: 2023-06-15 10:00", output)
        self.assertNotIn("prawdopodobnie zmiana czasu", output)

    def test_tariff_comparison_shows_cost_breakdown(self):
        """
        Porównanie taryf powinno pokazywać rozbicie na koszt energii i opłaty
        stałe (abonament), a nie tylko sumę całkowitą.
        """
        expected_summary, _ = run_full_analysis(
            data=self.test_data,
            capacity=0,
            tariff_manager=self.tariff_manager,
            tariff="G12w",
            net_metering_ratio=None,
            storage_efficiency=1.0,
        )
        expected_total = expected_summary["calkowity_koszt"]
        expected_fixed = expected_summary["oplaty_stale"]
        expected_energy = expected_total - expected_fixed

        import sys
        from io import StringIO

        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()
        run_tariff_comparison(
            data=self.test_data,
            tariff_manager=self.tariff_manager,
            capacity=0,
            net_metering_ratio=None,
            storage_efficiency=1.0,
        )
        sys.stdout = original_stdout
        output = captured_output.getvalue()

        self.assertIn(
            f"Taryfa G12w : {expected_total:>10.2f} zł "
            f"(energia: {expected_energy:>9.2f} zł, opłaty stałe: {expected_fixed:>8.2f} zł)",
            output,
        )
