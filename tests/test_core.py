import unittest
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime

from eanalizer.data_loader import load_from_enea_csv
from eanalizer.price_fetcher import get_hourly_rce_prices
from eanalizer.core import (
    run_rce_analysis, run_analysis_with_tariffs
)
from eanalizer.tariffs import TariffManager
from eanalizer.models import EnergyData

# Przykładowa odpowiedź JSON z API PSE dla jednego dnia
FAKE_API_RESPONSE = {
    "value": [
        {"dtime": "2024-07-01 00:15:00", "rce_pln": 400.0}, # Godzina 00:00 - średnia 400
        {"dtime": "2024-07-01 00:30:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 00:45:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 01:00:00", "rce_pln": 400.0},
        {"dtime": "2024-07-01 01:15:00", "rce_pln": 800.0}, # Godzina 01:00 - średnia 700
        {"dtime": "2024-07-01 01:30:00", "rce_pln": 800.0},
        {"dtime": "2024-07-01 01:45:00", "rce_pln": 800.0},
        {"dtime": "2024-07-01 02:00:00", "rce_pln": 800.0}
    ]
}

class TestCoreFunctionality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_data = load_from_enea_csv('tests/test_data.csv')
        cls.tariff_manager = TariffManager('config/tariffs.csv', years=range(2024, 2025))

    def test_data_loading(self):
        self.assertEqual(len(self.test_data), 5)
        self.assertEqual(self.test_data[0].pobor_przed, 1.0)

    @patch('urllib.request.urlopen')
    def test_rce_fetching_and_analysis(self, mock_urlopen):
        """Testuje cały proces pobierania, cachowania i analizy cen RCE."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(FAKE_API_RESPONSE).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        test_date_str = '2024-07-01'
        cache_file = f'cache/rce_prices/{test_date_str}.json'
        if os.path.exists(cache_file):
            os.remove(cache_file)

        prices = get_hourly_rce_prices(datetime(2024, 7, 1), datetime(2024, 7, 1))
        
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

    # Pozostałe testy, które powinny tu być, ale zostały pominięte dla zwięzłości
    # W pełnej wersji powinny tu być testy dla simulate_physical_storage i calculate_optimal_capacity

    def test_net_metering_cascade_logic(self):
        """Testuje kaskadową logikę rozliczeń net-metering między strefami."""
        # Przygotowujemy dane testowe obejmujące dwie strefy taryfy G12w
        # Strefa wysoka (dzień roboczy): 2024-05-02 10:00
        # Strefa niska (święto): 2024-05-01 22:00
        test_data = [
            self.test_data[3], # 2024-05-02 11:59 (pobor_przed=2.5, oddanie_przed=0) -> strefa WYSOKA
            self.test_data[2]  # 2024-05-01 22:59 (pobor_przed=2.0, oddanie_przed=0) -> strefa NISKA
        ]
        # Dodajemy rekord z produkcją w strefie wysokiej
        test_data.append(EnergyData(timestamp=datetime(2024, 5, 2, 12, 0), pobor_przed=0, oddanie_przed=5.0, pobor=0, oddanie=5.0))

        import sys
        from io import StringIO
        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        # Uruchamiamy analizę z włączonym net-meteringiem (współczynnik 0.8)
        run_analysis_with_tariffs(test_data, 'G12w', False, None, 0.8)
        sys.stdout = original_stdout
        output = captured_output.getvalue()

        # Oczekiwana logika:
        # 1. Strefa WYSOKA: pobór=2.5, oddanie=5.0. Kredyt: 5.0*0.8=4.0. Do opłacenia: max(0, 2.5-4.0)=0. Rollover: 1.5
        # 2. Strefa NISKA: pobór=2.0, oddanie=0. Kredyt: 0*0.8 + 1.5 (rollover) = 1.5. Do opłacenia: max(0, 2.0-1.5)=0.5
        # Całkowity koszt: 0.5 * 0.76 (cena w strefie niskiej) = 0.38
        self.assertIn("Kredyt z poprzedniej strefy: 1.500 kWh", output)
        self.assertIn("Energia do opłacenia w strefie: 0.500 kWh", output)
        self.assertIn("SUMARYCZNY KOSZT ENERGII (po rozliczeniu): 0.38 zł", output)
