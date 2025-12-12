import unittest
from datetime import datetime
from eanalizer.tariffs import TariffManager


class TestTariffManager(unittest.TestCase):

    def setUp(self):
        """Inicjalizuje managera taryf przed każdym testem."""
        self.tariff_manager = TariffManager(
            "config/tariffs.csv", years=range(2024, 2025)
        )

    def test_g11_tariff(self):
        """Test dla taryfy G11 - zawsze powinna być jedna strefa."""
        ts = datetime(2024, 5, 1, 10, 0)
        zone, _ = self.tariff_manager.get_zone_and_price(ts, "G11")
        self.assertEqual(zone, "stala")

    def test_g12_tariff_zones(self):
        """Test dla taryfy G12 - strefy dzienna i nocna."""
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 4, 0), "G12")[
                0
            ],
            "niska",
        )
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 14, 0), "G12")[
                0
            ],
            "niska",
        )
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 23, 0), "G12")[
                0
            ],
            "niska",
        )
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 7, 0), "G12")[
                0
            ],
            "wysoka",
        )
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 16, 0), "G12")[
                0
            ],
            "wysoka",
        )

    def test_g12w_tariff_zones(self):
        """Test dla taryfy G12w - uwzględnienie dni roboczych, weekendów i świąt."""
        # Dzień roboczy (wtorek)
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 10, 0), "G12w")[
                0
            ],
            "wysoka",
        )
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 2, 22, 0), "G12w")[
                0
            ],
            "niska",
        )

        # Weekend (sobota)
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 4, 6, 10, 0), "G12w")[
                0
            ],
            "niska",
        )

        # Święto (1 maja 2024, środa)
        self.assertEqual(
            self.tariff_manager.get_zone_and_price(datetime(2024, 5, 1, 10, 0), "G12w")[
                0
            ],
            "niska",
        )


if __name__ == "__main__":
    unittest.main()
