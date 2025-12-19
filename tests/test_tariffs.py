import os
import unittest
from datetime import datetime

from eanalizer.tariffs import TariffManager

TEST_TARIFFS_CSV = "test_tariffs_temp.csv"


class TestTariffManager(unittest.TestCase):
    def setUp(self):
        """Inicjalizuje managera taryf przed każdym testem z tymczasowym plikiem taryf."""
        # Ceny brutto (z VAT 23%) na podstawie taryfy ENEA Operator 2026.
        tariffs_content = (
            "tariff,zone_name,day_type,start_hour,end_hour,energy_price,dist_price,dist_fee\n"
            "G11,stala,all,0,24,0.61254,0.35547,43.4682\n"
            "G12,nocna,all,22,6,0.414387,0.165681,46.1004\n"
            "G12,dzienna,all,6,22,0.710817,0.395199,46.1004\n"
            "G12w,pozaszczytowa,weekday,0,6,0.426195,0.153381,55.0302\n"
            "G12w,szczytowa,weekday,6,22,0.801714,0.385728,55.0302\n"
            "G12w,pozaszczytowa,weekday,22,24,0.426195,0.153381,55.0302\n"
            "G12w,pozaszczytowa,weekend,0,24,0.426195,0.153381,55.0302\n"
        )
        with open(TEST_TARIFFS_CSV, "w", encoding="utf-8") as f:
            f.write(tariffs_content)

        self.tariff_manager = TariffManager(TEST_TARIFFS_CSV, years=range(2024, 2027))

    def tearDown(self):
        """Usuwa tymczasowy plik taryf po każdym teście."""
        os.remove(TEST_TARIFFS_CSV)

    def test_g11_tariff(self):
        """Test dla taryfy G11 - zawsze powinna być jedna strefa."""
        ts = datetime(2025, 5, 1, 10, 0)
        zone, energy, dist = self.tariff_manager.get_zone_and_price(ts, "G11")
        self.assertEqual(zone, "stala")
        self.assertAlmostEqual(energy, 0.61254)
        self.assertAlmostEqual(dist, 0.35547)

    def test_g12_tariff_zones(self):
        """Test dla taryfy G12 - strefy dzienna i nocna."""
        # Nocna (4:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 4, 2, 4, 0), "G12")
        self.assertEqual(zone, "nocna")
        # Dzienna (14:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 4, 2, 14, 0), "G12")
        self.assertEqual(zone, "dzienna")
        # Nocna (23:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 4, 2, 23, 0), "G12")
        self.assertEqual(zone, "nocna")

    def test_g12w_tariff_zones(self):
        """Test dla taryfy G12w - uwzględnienie dni roboczych, weekendów i świąt."""
        # Dzień roboczy (wtorek) - szczyt (10:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 4, 2, 10, 0), "G12w")
        self.assertEqual(zone, "szczytowa")
        # Dzień roboczy (wtorek) - pozaszczyt (23:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 4, 2, 23, 0), "G12w")
        self.assertEqual(zone, "pozaszczytowa")

        # Weekend (sobota) - pozaszczyt (10:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 4, 6, 10, 0), "G12w")
        self.assertEqual(zone, "pozaszczytowa")

        # Święto (1 maja, czwartek) - pozaszczyt (10:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(datetime(2025, 5, 1, 10, 0), "G12w")
        self.assertEqual(zone, "pozaszczytowa")

    def test_get_fixed_fee(self):
        """Testuje pobieranie opłaty stałej."""
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G11"), 43.4682)
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G12"), 46.1004)
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G12w"), 55.0302)
        self.assertEqual(self.tariff_manager.get_fixed_fee("NIEISTEJACA"), 0.0)

    def test_get_all_tariffs(self):
        """Testuje pobieranie listy wszystkich taryf."""
        self.assertEqual(set(self.tariff_manager.get_all_tariffs()), {"G11", "G12", "G12w"})


if __name__ == "__main__":
    unittest.main()
