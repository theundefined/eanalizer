import unittest
import pandas as pd
from eanalizer.data_loader import load_from_enea_csv
from eanalizer.core import simulate_physical_storage, calculate_optimal_capacity, aggregate_daily_data, calculate_zoned_stats
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
        """Testuje logikę symulacji magazynu fizycznego z podziałem na koszty."""
        summary, _ = simulate_physical_storage(self.test_data, 5.0, self.tariff_manager, 'G12w')
        
        # Oczekiwane wyniki na podstawie ręcznych obliczeń z poprzednich kroków:
        # Pobór 1.0 kWh w strefie niskiej (cena 0.76) -> koszt 0.76
        # Pobór 2.0 kWh w strefie wysokiej (cena 1.08) -> koszt 2.16
        self.assertAlmostEqual(summary['strefy']['niska']['pobor_z_sieci'], 1.0)
        self.assertAlmostEqual(summary['strefy']['niska']['koszt_poboru'], 1.0 * 0.76)
        self.assertAlmostEqual(summary['strefy']['wysoka']['pobor_z_sieci'], 2.0)
        self.assertAlmostEqual(summary['strefy']['wysoka']['koszt_poboru'], 2.0 * 1.08)
        self.assertAlmostEqual(summary['calkowity_koszt'], (1.0 * 0.76) + (2.0 * 1.08))

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

    def test_cost_calculation(self):
        """Testuje, czy koszt energii jest poprawnie obliczany dla danej strefy."""
        # Dane tylko z 1 maja (święto, wszystko w strefie niskiej G12w, cena 0.76)
        may_first_data = [r for r in self.test_data if r.timestamp.day == 1]
        # Pobrana energia po bilansowaniu tego dnia: 1.0 + 2.0 = 3.0 kWh
        # Oczekiwany koszt: 3.0 kWh * 0.76 zł/kWh = 2.28 zł
        expected_cost = 3.0 * 0.76

        # Przechwytujemy wydruk, aby sprawdzić, co zostało wyświetlone
        import sys
        from io import StringIO
        original_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        # Wywołujemy funkcję z ceną dla tej strefy
        returned_cost = calculate_zoned_stats(may_first_data, price=0.76)
        sys.stdout = original_stdout

        # Sprawdzamy, czy funkcja zwróciła poprawny koszt
        self.assertAlmostEqual(returned_cost, expected_cost)

        # Sprawdzamy, czy wydruk zawiera poprawny koszt
        output = captured_output.getvalue()
        self.assertIn(f"(koszt: {expected_cost:.2f} zł)", output)


if __name__ == '__main__':
    unittest.main()
