import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from eanalizer.core import run_tariff_comparison
from eanalizer.models import EnergyData
from eanalizer.netbilling import print_net_billing_summary, settle_net_billing
from eanalizer.price_fetcher import get_monthly_rcem_prices, parse_rcem_html
from eanalizer.tariffs import TariffManager

TEST_TARIFFS_CSV = "test_netbilling_tariffs_temp.csv"

# Fragment strony PSE z RCEm: tabela roczna, w tym skorygowana RCEm (ta z
# późniejszą datą publikacji powinna wygrać) oraz miesiąc z gwiazdkami.
RCEM_HTML = """
<html><body>
<table><tr><td>2025</td><td>cena [zł/MWh]**</td></tr>
<tr><td>styczeń</td><td>RCEm</td><td>480,01</td><td>11.02.2025</td></tr>
<tr><td>skorygowana RCEm*</td><td>-</td><td>-</td><td>-</td></tr>
<tr><td>marzec***</td><td>RCEm</td><td>182,96</td><td>11.04.2025</td></tr>
<tr><td>skorygowana RCEm*</td><td>178,84</td><td>11.03.2026</td><td>-2,25</td></tr>
</table>
<table><tr><td>2024</td><td>cena [zł/MWh]**</td></tr>
<tr><td>grudzień</td><td>RCEm</td><td>470,23</td><td>11.01.2025</td></tr>
</table>
</body></html>
"""


def _sim_df(rows):
    """rows: lista (timestamp, pobor_z_sieci, oddanie_do_sieci)."""
    return pd.DataFrame(
        [
            {"timestamp": ts, "pobor_z_sieci": p, "oddanie_do_sieci": o}
            for ts, p, o in rows
        ]
    )


class TestSettleNetBilling(unittest.TestCase):
    def setUp(self):
        with open(TEST_TARIFFS_CSV, "w", encoding="utf-8") as f:
            f.write(
                "tariff,zone_name,day_type,start_hour,end_hour,energy_price,dist_price,dist_fee\n"
                "G11,stala,all,0,24,0.5,0.3,10.0\n"
            )
        self.tm = TariffManager(TEST_TARIFFS_CSV, years=range(2023, 2027))

    def tearDown(self):
        os.remove(TEST_TARIFFS_CSV)

    def test_deposit_available_from_next_month_and_covers_energy_only(self):
        df = _sim_df(
            [
                (datetime(2024, 5, 10, 12), 0.0, 100.0),  # depozyt 100*0.3 = 30 zł
                (datetime(2024, 5, 10, 20), 10.0, 0.0),  # energia 5 zł, dystr. 3 zł
                (datetime(2024, 6, 10, 20), 20.0, 0.0),  # energia 10 zł, dystr. 6 zł
            ]
        )
        s = settle_net_billing(
            df, self.tm, "G11", {}, {"2024-05": 0.3, "2024-06": 0.3}
        )
        months = s["miesiace"].set_index("miesiac")
        # Depozyt z maja nie pokrywa poboru z maja.
        self.assertAlmostEqual(months.loc["2024-05", "pokryte_depozytem"], 0.0)
        self.assertAlmostEqual(months.loc["2024-05", "nowy_depozyt"], 30.0)
        # W czerwcu depozyt pokrywa całą energię, ale nie dystrybucję.
        self.assertAlmostEqual(months.loc["2024-06", "pokryte_depozytem"], 10.0)
        self.assertAlmostEqual(months.loc["2024-06", "energia_do_zaplaty"], 0.0)
        self.assertAlmostEqual(s["koszt_dystrybucji"], 9.0)
        self.assertAlmostEqual(s["depozyt_pozostaly"], 20.0)
        # Przed 02.2025 brak współczynnika 1,23.
        self.assertAlmostEqual(s["wartosc_depozytu"], 30.0)
        self.assertAlmostEqual(s["calkowity_koszt"], 5.0 + 9.0)

    def test_coefficient_1_23_from_february_2025(self):
        df = _sim_df(
            [
                (datetime(2025, 1, 10, 12), 0.0, 100.0),
                (datetime(2025, 2, 10, 12), 0.0, 100.0),
            ]
        )
        s = settle_net_billing(
            df, self.tm, "G11", {}, {"2025-01": 0.4, "2025-02": 0.4}
        )
        months = s["miesiace"].set_index("miesiac")
        self.assertAlmostEqual(months.loc["2025-01", "nowy_depozyt"], 40.0)
        self.assertAlmostEqual(months.loc["2025-02", "nowy_depozyt"], 40.0 * 1.23)

    def test_hourly_rce_negative_prices_count_as_zero(self):
        h1 = datetime(2025, 5, 10, 11)
        h2 = datetime(2025, 5, 10, 12)
        df = _sim_df([(h1, 0.0, 10.0), (h2, 0.0, 10.0)])
        s = settle_net_billing(
            df,
            self.tm,
            "G11",
            rce_prices={h1: 0.2, h2: -0.1},
            rcem_prices={"2025-05": 99.0},  # nie może zostać użyta
            wycena="rce",
        )
        self.assertAlmostEqual(s["wartosc_depozytu"], 10.0 * 0.2 * 1.23)

    def test_hourly_rce_falls_back_to_rcem_before_july_2024(self):
        df = _sim_df(
            [
                (datetime(2024, 6, 10, 12), 0.0, 10.0),
                (datetime(2024, 7, 10, 12), 0.0, 10.0),
            ]
        )
        s = settle_net_billing(
            df,
            self.tm,
            "G11",
            rce_prices={datetime(2024, 7, 10, 12): 0.5},
            rcem_prices={"2024-06": 0.3, "2024-07": 99.0},
            wycena="rce",
        )
        months = s["miesiace"].set_index("miesiac")
        self.assertAlmostEqual(months.loc["2024-06", "nowy_depozyt"], 3.0)
        self.assertAlmostEqual(months.loc["2024-07", "nowy_depozyt"], 5.0)

    def test_refund_after_12_months(self):
        # Depozyt z 01.2025 (bez 1,23) = 100 zł, ważny 02.2025-01.2026; bez
        # poboru w tym czasie wraca 20% (RCEm), reszta przepada.
        df = _sim_df(
            [
                (datetime(2025, 1, 10, 12), 0.0, 250.0),
                (datetime(2026, 1, 10, 20), 0.0, 0.0),
            ]
        )
        s = settle_net_billing(df, self.tm, "G11", {}, {"2025-01": 0.4})
        self.assertAlmostEqual(s["zwrot_nadplaty"], 20.0)
        self.assertAlmostEqual(s["przepadly_depozyt"], 80.0)
        self.assertAlmostEqual(s["depozyt_pozostaly"], 0.0)
        self.assertAlmostEqual(s["calkowity_koszt"], -20.0)
        months = s["miesiace"].set_index("miesiac")
        self.assertEqual(len(months), 13)
        self.assertAlmostEqual(months.loc["2026-01", "zwrot_nadplaty"], 20.0)

    def test_refund_limit_30_percent_for_hourly_rce_from_february_2025(self):
        h = datetime(2025, 3, 10, 12)
        df = _sim_df([(h, 0.0, 100.0), (datetime(2026, 3, 10, 20), 0.0, 0.0)])
        s = settle_net_billing(df, self.tm, "G11", {h: 1.0}, {}, wycena="rce")
        deposit = 100.0 * 1.23
        self.assertAlmostEqual(s["zwrot_nadplaty"], deposit * 0.30)

    def test_no_refund_for_deposits_expiring_before_july_2024(self):
        df = _sim_df(
            [
                (datetime(2023, 1, 10, 12), 0.0, 100.0),
                (datetime(2024, 1, 10, 20), 0.0, 0.0),
            ]
        )
        s = settle_net_billing(df, self.tm, "G11", {}, {"2023-01": 0.5})
        self.assertAlmostEqual(s["zwrot_nadplaty"], 0.0)
        self.assertAlmostEqual(s["przepadly_depozyt"], 50.0)

    def test_oldest_deposit_used_first(self):
        df = _sim_df(
            [
                (datetime(2025, 1, 10, 12), 0.0, 100.0),  # 10 zł, wygasa 01.2026
                (datetime(2025, 3, 10, 12), 0.0, 100.0),  # 12.30 zł
                (datetime(2025, 12, 10, 20), 20.0, 0.0),  # energia 10 zł
                (datetime(2026, 1, 10, 20), 0.0, 0.0),
            ]
        )
        s = settle_net_billing(
            df, self.tm, "G11", {}, {"2025-01": 0.1, "2025-03": 0.1}
        )
        # Całe 10 zł pobrano z najstarszego depozytu, więc z niego nie ma już
        # zwrotu, a depozyt z 03.2025 pozostaje nietknięty.
        self.assertAlmostEqual(s["pokryte_depozytem"], 10.0)
        self.assertAlmostEqual(s["zwrot_nadplaty"], 0.0)
        self.assertAlmostEqual(s["depozyt_pozostaly"], 12.3)

    def test_missing_rcem_is_reported(self):
        df = _sim_df([(datetime(2025, 5, 10, 12), 0.0, 10.0)])
        s = settle_net_billing(df, self.tm, "G11", {}, {})
        self.assertEqual(s["brakujace_ceny_rcem"], ["2025-05"])
        self.assertAlmostEqual(s["wartosc_depozytu"], 0.0)

        captured = StringIO()
        original_stdout, sys.stdout = sys.stdout, captured
        try:
            print_net_billing_summary(s, "G11")
        finally:
            sys.stdout = original_stdout
        self.assertIn("brak cen RCEm dla miesięcy: 2025-05", captured.getvalue())
        self.assertIn("SUMARYCZNY KOSZT (net-billing)", captured.getvalue())

    def test_fixed_fee_included(self):
        df = _sim_df([(datetime(2025, 5, 10, 20), 10.0, 0.0)])
        s = settle_net_billing(df, self.tm, "G11", {}, {}, fixed_fee=10.0)
        self.assertAlmostEqual(s["calkowity_koszt"], 5.0 + 3.0 + 10.0)

    def test_invalid_valuation_raises(self):
        df = _sim_df([(datetime(2025, 5, 10, 20), 1.0, 0.0)])
        with self.assertRaises(ValueError):
            settle_net_billing(df, self.tm, "G11", {}, {}, wycena="xyz")

    def test_tariff_comparison_with_net_billing(self):
        data = [
            EnergyData(datetime(2025, 5, 10, 12), 0.0, 100.0, 0.0, 100.0),
            EnergyData(datetime(2025, 6, 10, 20), 20.0, 0.0, 20.0, 0.0),
        ]
        captured = StringIO()
        original_stdout, sys.stdout = sys.stdout, captured
        try:
            results = run_tariff_comparison(
                data,
                self.tm,
                capacity=0.0,
                net_metering_ratio=None,
                storage_efficiency=1.0,
                net_billing={
                    "rce_prices": {},
                    "rcem_prices": {"2025-05": 0.1, "2025-06": 0.1},
                    "wycena": "rcem",
                },
            )
        finally:
            sys.stdout = original_stdout
        # Energia 10 zł pokryta depozytem 12.30 zł; zostaje dystrybucja 6 zł
        # i opłaty stałe za 2 miesiące (20 zł).
        self.assertAlmostEqual(results["G11"], 6.0 + 20.0)
        self.assertIn("Uwzględniono net-billing (wycena: RCEM)", captured.getvalue())


class TestRcemPrices(unittest.TestCase):
    def setUp(self):
        self.cache_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.cache_dir, ignore_errors=True)

    def test_parse_rcem_html_uses_latest_correction(self):
        prices = parse_rcem_html(RCEM_HTML)
        self.assertEqual(set(prices), {"2025-01", "2025-03", "2024-12"})
        self.assertAlmostEqual(prices["2025-01"], 0.48001)
        self.assertAlmostEqual(prices["2025-03"], 0.17884)
        self.assertAlmostEqual(prices["2024-12"], 0.47023)

    @patch("urllib.request.urlopen")
    def test_rcem_is_fetched_once_and_cached(self, mock_urlopen):
        response = MagicMock()
        response.status = 200
        response.read.return_value = RCEM_HTML.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response

        prices = get_monthly_rcem_prices(["2025-01", "2025-03"], self.cache_dir)
        self.assertEqual(prices, {"2025-01": 0.48001, "2025-03": 0.17884})
        self.assertEqual(mock_urlopen.call_count, 1)

        # Kolejne wywołanie korzysta z cache, także dla miesiąca, którego
        # PSE jeszcze nie opublikowała (cache jest świeży).
        prices = get_monthly_rcem_prices(["2025-01", "2025-09"], self.cache_dir)
        self.assertEqual(prices, {"2025-01": 0.48001})
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_stale_cache_is_refreshed_when_month_missing(self, mock_urlopen):
        cache_file = self.cache_dir / "rcem.json"
        cache_file.write_text(
            json.dumps(
                {
                    "fetched_at": (datetime.now() - timedelta(days=2)).isoformat(),
                    "prices": {"2024-12": 0.47023},
                }
            ),
            encoding="utf-8",
        )
        response = MagicMock()
        response.status = 200
        response.read.return_value = RCEM_HTML.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response

        # Wszystkie potrzebne miesiące w cache - brak zapytania mimo wieku cache.
        get_monthly_rcem_prices(["2024-12"], self.cache_dir)
        mock_urlopen.assert_not_called()

        prices = get_monthly_rcem_prices(["2024-12", "2025-03"], self.cache_dir)
        self.assertEqual(prices, {"2024-12": 0.47023, "2025-03": 0.17884})
        mock_urlopen.assert_called_once()

    @patch("urllib.request.urlopen", side_effect=ConnectionError("offline"))
    def test_fetch_failure_returns_cached_subset(self, _mock_urlopen):
        prices = get_monthly_rcem_prices(["2025-01"], self.cache_dir)
        self.assertEqual(prices, {})
        self.assertFalse((self.cache_dir / "rcem.json").exists())


if __name__ == "__main__":
    unittest.main()
