import unittest
import pandas as pd
from eanalizer.data_loader import load_from_enea_csv
from eanalizer.core import simulate_physical_storage, calculate_optimal_capacity, aggregate_daily_data
from eanalizer.tariffs import TariffManager

class TestCoreFunctionality(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Wczytuje dane testowe raz dla wszystkich testów w tej klasie."""
        cls.test_data = load_from_enea_csv('tests/test_data.csv')
        cls.tariff_manager = TariffManager('config/tariffs.csv', years=range(2024, 2025))

    def test_data_loading(self):
        """Sprawdza, czy dane testowe są poprawnie wczytywane i parsowane."""
        self.assertEqual(len(self.test_data), 5)
        # Sprawdzenie pierwszego rekordu
        first_record = self.test_data[0]
        self.assertEqual(first_record.pobor_przed, 1.0)
        self.assertEqual(first_record.oddanie, 0.0)

    def test_physical_storage_simulation(self):
        """Testuje logikę symulacji magazynu fizycznego."""
        # Pojemność magazynu: 5 kWh
        summary, _ = simulate_physical_storage(self.test_data, 5.0, self.tariff_manager, 'G12w')
        
        # Ręczne obliczenia dla danych testowych:
        # 1. 01.05 04:59 (niska): pobór 1.0 z sieci. Stan magazynu: 0.0
        # 2. 01.05 10:59 (niska): nadwyżka 2.5 -> 2.5 do magazynu. Stan: 2.5
        # 3. 01.05 22:59 (niska): niedobór 2.0 -> 2.0 z magazynu. Stan: 0.5
        # 4. 02.05 11:59 (wysoka): niedobór 2.5 -> 0.5 z magazynu, 2.0 z sieci. Stan: 0.0
        # 5. 04.05 10:59 (niska): nadwyżka 4.8 -> 4.8 do magazynu. Stan: 4.8
        # Ostatecznie: pobrano 1.0 (niska) i 2.0 (wysoka), nic nie oddano do sieci.
        self.assertAlmostEqual(summary['pobor_z_sieci']['niska'], 1.0)
        self.assertAlmostEqual(summary['pobor_z_sieci']['wysoka'], 2.0)
        # Sprawdzamy, czy nic nie zostało oddane do sieci
        self.assertAlmostEqual(sum(summary['oddanie_do_sieci'].values()), 0.0)

    def test_optimal_capacity_calculation(self):
        """Testuje logikę obliczania optymalnej pojemności magazynu."""
        # Na podstawie danych testowych:
        # - Pojemność dla dni z nadprodukcją (4 maja) wynosi 0.0 kWh.
        # - Pojemność dla arbitrażu (2 maja, dzień roboczy) to suma poboru `pobor_przed` w strefie wysokiej, czyli 2.5 kWh.
        # - Optymalna pojemność to maximum z tych dwóch wartości, czyli 2.5 kWh.
        daily_df = aggregate_daily_data(self.test_data)
        import sys
        from io import StringIO
        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        calculate_optimal_capacity(self.test_data, daily_df, self.tariff_manager, 'G12w')
        sys.stdout = original_stdout
        
        output = captured_output.getvalue()
        self.assertIn("Wynik: 2.500 kWh", output)

if __name__ == '__main__':
    unittest.main()
