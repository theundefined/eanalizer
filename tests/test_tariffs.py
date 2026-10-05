import os
import unittest
from datetime import datetime

from eanalizer.config import DEFAULT_TARIFFS_CSV
from eanalizer.tariffs import TariffManager

TEST_TARIFFS_CSV = "test_tariffs_temp.csv"


class TestTariffManager(unittest.TestCase):
    def setUp(self):
        """Inicjalizuje managera taryf przed każdym testem z tymczasowym plikiem taryf."""
        with open(TEST_TARIFFS_CSV, "w", encoding="utf-8") as f:
            f.write(DEFAULT_TARIFFS_CSV)

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
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 2, 4, 0), "G12"
        )
        self.assertEqual(zone, "nocna")
        # Dzienna (6:00-13:00 i 15:00-22:00)
        for hour in (6, 10, 12, 15, 16, 21):
            zone, _, _ = self.tariff_manager.get_zone_and_price(
                datetime(2025, 4, 2, hour, 0), "G12"
            )
            self.assertEqual(zone, "dzienna", f"godzina {hour}")
        # Nocna popołudniowa dolina Enea (13:00-15:00)
        for hour in (13, 14):
            zone, _, _ = self.tariff_manager.get_zone_and_price(
                datetime(2025, 4, 2, hour, 0), "G12"
            )
            self.assertEqual(zone, "nocna", f"godzina {hour}")
        # Nocna (23:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 2, 23, 0), "G12"
        )
        self.assertEqual(zone, "nocna")

    def test_g12w_tariff_zones(self):
        """Test dla taryfy G12w - uwzględnienie dni roboczych, weekendów i świąt."""
        # Dzień roboczy (wtorek) - szczyt (10:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 2, 10, 0), "G12w"
        )
        self.assertEqual(zone, "szczytowa")
        # Dzień roboczy - ostatnia godzina szczytu (20:00) i początek
        # strefy pozaszczytowej Enea już o 21:00
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 2, 20, 0), "G12w"
        )
        self.assertEqual(zone, "szczytowa")
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 2, 21, 0), "G12w"
        )
        self.assertEqual(zone, "pozaszczytowa")
        # Dzień roboczy (wtorek) - pozaszczyt (23:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 2, 23, 0), "G12w"
        )
        self.assertEqual(zone, "pozaszczytowa")

        # Weekend (sobota) - pozaszczyt (10:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 4, 6, 10, 0), "G12w"
        )
        self.assertEqual(zone, "pozaszczytowa")

        # Święto (1 maja, czwartek) - pozaszczyt (10:00)
        zone, _, _ = self.tariff_manager.get_zone_and_price(
            datetime(2025, 5, 1, 10, 0), "G12w"
        )
        self.assertEqual(zone, "pozaszczytowa")

    def test_zone_cache_distinguishes_day_types(self):
        """Wyniki z cache muszą rozróżniać dzień roboczy, weekend i święto."""
        weekday = datetime(2025, 4, 2, 10, 0)
        saturday = datetime(2025, 4, 5, 10, 0)
        holiday = datetime(2025, 5, 1, 10, 0)
        for _ in range(2):
            self.assertEqual(
                self.tariff_manager.get_zone_and_price(weekday, "G12w")[0],
                "szczytowa",
            )
            self.assertEqual(
                self.tariff_manager.get_zone_and_price(saturday, "g12w")[0],
                "pozaszczytowa",
            )
            self.assertEqual(
                self.tariff_manager.get_zone_and_price(holiday, "G12w")[0],
                "pozaszczytowa",
            )
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(weekday, "NIEISTEJACA"),
            (None, 0.0, 0.0),
        )

    def test_get_fixed_fee(self):
        """Testuje pobieranie opłaty stałej."""
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G11"), 43.4682)
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G12"), 46.1004)
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G12w"), 55.0302)
        self.assertEqual(self.tariff_manager.get_fixed_fee("NIEISTEJACA"), 0.0)

    def test_get_fixed_fee_is_case_insensitive(self):
        """
        Nazwa taryfy podana małymi literami (np. --taryfa g12w) musi dawać tę
        samą opłatę stałą, co przy wyznaczaniu stref (które już ignorują
        wielkość liter) - inaczej koszt całkowity byłby zaniżony o opłaty stałe.
        """
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("g12w"), 55.0302)
        self.assertAlmostEqual(self.tariff_manager.get_fixed_fee("G12W"), 55.0302)

    def test_get_all_tariffs(self):
        """Testuje pobieranie listy wszystkich taryf."""
        self.assertEqual(
            set(self.tariff_manager.get_all_tariffs()), {"G11", "G12", "G12w"}
        )


if __name__ == "__main__":
    unittest.main()
