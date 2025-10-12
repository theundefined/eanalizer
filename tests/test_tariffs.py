import unittest
from datetime import datetime
from eanalizer.tariffs import TariffManager

class TestTariffManager(unittest.TestCase):

    def setUp(self):
        """Inicjalizuje managera taryf przed każdym testem."""
        # Używamy lat, które obejmują nasze dane testowe i święta
        self.tariff_manager = TariffManager('config/tariffs.csv', years=range(2024, 2025))

    def test_g11_tariff(self):
        """Test dla taryfy G11 - zawsze powinna być jedna strefa."""
        ts = datetime(2024, 5, 1, 10, 0) # Dzień świąteczny, środek dnia
        self.assertEqual(self.tariff_manager.get_zone(ts, 'G11'), 'stala')

    def test_g12_tariff_zones(self):
        """Test dla taryfy G12 - strefy dzienna i nocna."""
        # Strefa niska (nocna)
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 1, 4, 0), 'G12'), 'niska')
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 1, 14, 0), 'G12'), 'niska')
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 1, 23, 0), 'G12'), 'niska')
        # Strefa wysoka (dzienna)
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 1, 7, 0), 'G12'), 'wysoka')
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 1, 16, 0), 'G12'), 'wysoka')

    def test_g12w_tariff_zones(self):
        """Test dla taryfy G12w - uwzględnienie dni roboczych, weekendów i świąt."""
        # Dzień roboczy (wtorek)
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 2, 10, 0), 'G12w'), 'wysoka') # 10:00 - strefa wysoka
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 2, 22, 0), 'G12w'), 'niska')  # 22:00 - strefa niska

        # Weekend (sobota)
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 4, 6, 10, 0), 'G12w'), 'niska') # 10:00 w weekend - strefa niska

        # Święto (1 maja 2024, środa)
        self.assertEqual(self.tariff_manager.get_zone(datetime(2024, 5, 1, 10, 0), 'G12w'), 'niska') # 10:00 w święto - strefa niska

if __name__ == '__main__':
    unittest.main()
