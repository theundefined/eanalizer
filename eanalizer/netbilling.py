"""
Rozliczenie prosumenta w systemie net-billing.

Model (uproszczony, zgodny z ustawą OZE po nowelizacjach):
- energia pobrana z sieci jest kupowana po cenie taryfy (energia + dystrybucja),
- energia oddana do sieci tworzy depozyt prosumencki o wartości:
  * RCEm (miesięczna cena PSE) x ilość oddana w miesiącu - wycena "rcem",
  * suma po godzinach RCE x ilość oddana w godzinie - wycena "rce"
    (możliwa dopiero od 07.2024; wcześniej wszyscy byli rozliczani po RCEm),
  przy czym ujemne ceny RCE liczone są jako 0,
- od 02.2025 wartość depozytu jest mnożona przez współczynnik 1,23,
- depozyt z miesiąca M jest dostępny od miesiąca M+1 przez 12 miesięcy
  i pokrywa wyłącznie koszt energii czynnej (nie opłaty dystrybucyjne),
  najstarsze środki wykorzystywane są w pierwszej kolejności,
- niewykorzystany depozyt po 12 miesiącach jest zwracany do 20% wartości
  depozytu miesięcznego (do 30% przy wycenie godzinowej RCE od 02.2025);
  zwrot nadpłaty przysługuje dla depozytów wygasających od 07.2024.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .tariffs import TariffManager

WYCENY = ["rcem", "rce"]
HOURLY_RCE_START = datetime(2024, 7, 1)
COEFFICIENT_START_MONTH = "2025-02"
COEFFICIENT = 1.23
REFUND_START_MONTH = "2024-07"
REFUND_LIMIT_RCEM = 0.20
REFUND_LIMIT_RCE = 0.30
DEPOSIT_VALIDITY_MONTHS = 12


def _month_range(first: str, last: str) -> List[str]:
    periods = pd.period_range(start=first, end=last, freq="M")
    return [str(p) for p in periods]


def _add_months(month: str, n: int) -> str:
    return str(pd.Period(month, freq="M") + n)


def settle_net_billing(
    simulation_df: Optional[pd.DataFrame],
    tariff_manager: TariffManager,
    tariff: str,
    rce_prices: Dict[datetime, float],
    rcem_prices: Dict[str, float],
    wycena: str = "rcem",
    fixed_fee: float = 0.0,
) -> Dict[str, Any]:
    """
    Rozlicza godzinowe wyniki symulacji (kolumny: timestamp, pobor_z_sieci,
    oddanie_do_sieci - np. z run_full_analysis) w systemie net-billing.
    Zwraca słownik z podsumowaniem oraz zestawieniem miesięcznym.
    """
    if wycena not in WYCENY:
        raise ValueError(f"Nieznany sposób wyceny: {wycena}")
    if simulation_df is None or simulation_df.empty:
        return {}

    monthly: Dict[str, Dict[str, float]] = {}
    hourly_value: Dict[str, float] = {}
    missing_rce_hours = 0

    for row in simulation_df.itertuples():
        ts = row.timestamp
        month = ts.strftime("%Y-%m")
        m = monthly.setdefault(
            month,
            {
                "pobor": 0.0,
                "oddanie": 0.0,
                "koszt_energii": 0.0,
                "koszt_dystrybucji": 0.0,
            },
        )
        _, energy_price, dist_price = tariff_manager.get_zone_and_price(ts, tariff)
        m["pobor"] += row.pobor_z_sieci
        m["oddanie"] += row.oddanie_do_sieci
        m["koszt_energii"] += row.pobor_z_sieci * energy_price
        m["koszt_dystrybucji"] += row.pobor_z_sieci * dist_price

        if wycena == "rce" and ts >= HOURLY_RCE_START and row.oddanie_do_sieci > 0:
            price = rce_prices.get(ts)
            if price is None or pd.isna(price):
                missing_rce_hours += 1
                price = 0.0
            hourly_value[month] = hourly_value.get(month, 0.0) + (
                row.oddanie_do_sieci * max(price, 0.0)
            )

    months = _month_range(min(monthly), max(monthly))
    missing_rcem_months: List[str] = []
    deposits: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    totals = {
        "wartosc_depozytu": 0.0,
        "pokryte_depozytem": 0.0,
        "zwrot_nadplaty": 0.0,
        "przepadly_depozyt": 0.0,
    }

    for month in months:
        m = monthly.get(
            month,
            {"pobor": 0.0, "oddanie": 0.0, "koszt_energii": 0.0, "koszt_dystrybucji": 0.0},
        )

        # 1. Koszt energii czynnej pokrywany z depozytów (najstarsze najpierw).
        to_cover = m["koszt_energii"]
        covered = 0.0
        for dep in deposits:
            if to_cover <= 0:
                break
            if dep["od"] <= month <= dep["do"] and dep["pozostalo"] > 0:
                used = min(dep["pozostalo"], to_cover)
                dep["pozostalo"] -= used
                to_cover -= used
                covered += used

        # 2. Wygasające depozyty: zwrot nadpłaty, reszta przepada.
        refund = 0.0
        expired = 0.0
        for dep in deposits:
            if dep["do"] == month and dep["pozostalo"] > 0:
                limit = dep["limit_zwrotu"] if month >= REFUND_START_MONTH else 0.0
                dep_refund = min(dep["pozostalo"], dep["wartosc"] * limit)
                refund += dep_refund
                expired += dep["pozostalo"] - dep_refund
                dep["pozostalo"] = 0.0

        # 3. Nowy depozyt z energii oddanej w tym miesiącu.
        hourly = wycena == "rce" and month >= HOURLY_RCE_START.strftime("%Y-%m")
        if hourly:
            base_value = hourly_value.get(month, 0.0)
        elif m["oddanie"] > 0:
            rcem = rcem_prices.get(month)
            if rcem is None:
                missing_rcem_months.append(month)
                rcem = 0.0
            base_value = m["oddanie"] * max(rcem, 0.0)
        else:
            base_value = 0.0
        coefficient = COEFFICIENT if month >= COEFFICIENT_START_MONTH else 1.0
        deposit_value = base_value * coefficient
        refund_limit = (
            REFUND_LIMIT_RCE
            if hourly and month >= COEFFICIENT_START_MONTH
            else REFUND_LIMIT_RCEM
        )
        if deposit_value > 0:
            deposits.append(
                {
                    "miesiac": month,
                    "od": _add_months(month, 1),
                    "do": _add_months(month, DEPOSIT_VALIDITY_MONTHS),
                    "wartosc": deposit_value,
                    "pozostalo": deposit_value,
                    "limit_zwrotu": refund_limit,
                }
            )

        totals["wartosc_depozytu"] += deposit_value
        totals["pokryte_depozytem"] += covered
        totals["zwrot_nadplaty"] += refund
        totals["przepadly_depozyt"] += expired
        rows.append(
            {
                "miesiac": month,
                "pobor": m["pobor"],
                "oddanie": m["oddanie"],
                "koszt_energii": m["koszt_energii"],
                "pokryte_depozytem": covered,
                "energia_do_zaplaty": m["koszt_energii"] - covered,
                "koszt_dystrybucji": m["koszt_dystrybucji"],
                "nowy_depozyt": deposit_value,
                "zwrot_nadplaty": refund,
                "saldo_depozytu": sum(d["pozostalo"] for d in deposits),
            }
        )

    koszt_energii = sum(r["koszt_energii"] for r in rows)
    koszt_dystrybucji = sum(r["koszt_dystrybucji"] for r in rows)
    energia_do_zaplaty = koszt_energii - totals["pokryte_depozytem"]
    calkowity_koszt = (
        energia_do_zaplaty + koszt_dystrybucji + fixed_fee - totals["zwrot_nadplaty"]
    )

    return {
        "wycena": wycena,
        "koszt_energii": koszt_energii,
        "energia_do_zaplaty": energia_do_zaplaty,
        "koszt_dystrybucji": koszt_dystrybucji,
        "oplaty_stale": fixed_fee,
        "depozyt_pozostaly": sum(d["pozostalo"] for d in deposits),
        "calkowity_koszt": calkowity_koszt,
        "brakujace_ceny_rce_godziny": missing_rce_hours,
        "brakujace_ceny_rcem": missing_rcem_months,
        "miesiace": pd.DataFrame(rows),
        **totals,
    }


def print_net_billing_summary(
    summary: Dict[str, Any], tariff: str, capacity: float = 0.0
):
    """Wyświetla podsumowanie rozliczenia net-billing wraz z tabelą miesięczną."""
    if not summary:
        print("Brak danych do rozliczenia net-billing.")
        return

    wycena_opis = (
        "RCEm (miesięczna)"
        if summary["wycena"] == "rcem"
        else "RCE (godzinowa, przed 07.2024 RCEm)"
    )
    header = f"--- Rozliczenie net-billing dla taryfy {tariff.upper()} (wycena: {wycena_opis})"
    if capacity > 0:
        header += f", magazyn fizyczny {capacity} kWh"
    print(f"\n{header} ---")

    monthly_df: pd.DataFrame = summary["miesiace"]
    table_header = (
        f"{'Miesiąc':<8} | {'Pobrane':>11} | {'Oddane':>11} | {'Energia':>9} | "
        f"{'Z depozytu':>10} | {'Dystryb.':>9} | {'Nowy dep.':>9} | {'Saldo dep.':>10}"
    )
    print(table_header)
    print("-" * len(table_header))
    for r in monthly_df.itertuples():
        print(
            f"{r.miesiac:<8} | {r.pobor:>7.1f} kWh | {r.oddanie:>7.1f} kWh | "
            f"{r.koszt_energii:>6.2f} zł | {r.pokryte_depozytem:>7.2f} zł | "
            f"{r.koszt_dystrybucji:>6.2f} zł | {r.nowy_depozyt:>6.2f} zł | "
            f"{r.saldo_depozytu:>7.2f} zł"
        )
    print("-" * len(table_header))

    print(f"Koszt energii czynnej (przed depozytem): {summary['koszt_energii']:.2f} zł")
    print(f"Wartość utworzonego depozytu:            {summary['wartosc_depozytu']:.2f} zł")
    print(f"Pokryte z depozytu:                      {summary['pokryte_depozytem']:.2f} zł")
    print(f"Energia do zapłaty:                      {summary['energia_do_zaplaty']:.2f} zł")
    print(f"Opłaty dystrybucyjne zmienne:            {summary['koszt_dystrybucji']:.2f} zł")
    print(f"Opłaty stałe:                            {summary['oplaty_stale']:.2f} zł")
    if summary["zwrot_nadplaty"] > 0:
        print(f"Zwrot nadpłaty (depozyt po 12 mies.):    -{summary['zwrot_nadplaty']:.2f} zł")
    if summary["przepadly_depozyt"] > 0:
        print(f"Przepadły depozyt:                       {summary['przepadly_depozyt']:.2f} zł")
    print("---------------------------------------------")
    print(f"SUMARYCZNY KOSZT (net-billing): {summary['calkowity_koszt']:.2f} zł")
    print(
        f"Depozyt do wykorzystania na koniec okresu: {summary['depozyt_pozostaly']:.2f} zł"
    )
    print("---------------------------------------------")

    if summary["brakujace_ceny_rcem"]:
        print(
            "Ostrzeżenie: brak cen RCEm dla miesięcy: "
            + ", ".join(summary["brakujace_ceny_rcem"])
            + " - energia oddana w tych miesiącach nie została wyceniona."
        )
    if summary["brakujace_ceny_rce_godziny"]:
        print(
            f"Ostrzeżenie: brak cen RCE dla {summary['brakujace_ceny_rce_godziny']} "
            "godzin z oddaniem energii - te godziny nie zostały wycenione."
        )
