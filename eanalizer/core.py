from typing import List, Optional, Dict, Tuple, Any
from datetime import datetime
from .models import EnergyData, SimulationResult
from .tariffs import TariffManager
import pandas as pd


def run_full_analysis(
    data: List[EnergyData],
    capacity: float,
    tariff_manager: TariffManager,
    tariff: str,
    net_metering_ratio: Optional[float] = None,
    storage_efficiency: float = 1.0,
) -> Tuple[Dict[str, Any], Optional[pd.DataFrame]]:
    """
    Runs a universal analysis, simulating a physical storage of a given
    capacity with a given efficiency.
    A capacity of 0 means a standard analysis without storage.
    Efficiency is applied during charging.
    Returns a summary dictionary and an optional DataFrame with hourly results.
    """
    if not data:
        return {}, None

    num_months = (
        (data[-1].timestamp.year - data[0].timestamp.year) * 12
        + (data[-1].timestamp.month - data[0].timestamp.month)
        + 1
    )

    stan_magazynu = 0.0
    wyniki_symulacji = []
    stats: Dict[str, Any] = {"strefy": {}}

    # Hourly simulation
    for rekord in data:
        pobor_z_magazynu, oddanie_do_magazynu, pobor_z_sieci, oddanie_do_sieci = (
            0.0,
            0.0,
            0.0,
            0.0,
        )

        # Bilansowanie godzinowe
        if rekord.oddanie_przed > rekord.pobor_przed:
            nadwyzka = rekord.oddanie_przed - rekord.pobor_przed

            # Apply efficiency on charging
            wolne_miejsce_netto = capacity - stan_magazynu
            potrzebna_nadwyzka_brutto = (
                wolne_miejsce_netto / storage_efficiency if storage_efficiency > 0 else float("inf")
            )

            realna_nadwyzka_do_ladowania = min(nadwyzka, potrzebna_nadwyzka_brutto)
            przyrost_stanu_magazynu = realna_nadwyzka_do_ladowania * storage_efficiency

            stan_magazynu += przyrost_stanu_magazynu
            oddanie_do_magazynu = realna_nadwyzka_do_ladowania
            oddanie_do_sieci = nadwyzka - oddanie_do_magazynu

            pobor_z_magazynu = 0.0
            pobor_z_sieci = 0.0

        elif rekord.pobor_przed > rekord.oddanie_przed:
            niedobor = rekord.pobor_przed - rekord.oddanie_przed

            # Discharging is 1:1
            pobor_z_magazynu = min(niedobor, stan_magazynu)
            stan_magazynu -= pobor_z_magazynu

            oddanie_do_magazynu = 0.0
            oddanie_do_sieci = 0.0
            pobor_z_sieci = niedobor - pobor_z_magazynu

        else:  # ideal self-consumption
            pobor_z_sieci = 0.0
            oddanie_do_sieci = 0.0
            pobor_z_magazynu = 0.0
            oddanie_do_magazynu = 0.0

        zone, energy_price, dist_price = tariff_manager.get_zone_and_price(rekord.timestamp, tariff)
        if zone:
            price = energy_price + dist_price
            if zone not in stats["strefy"]:
                stats["strefy"][zone] = {
                    "pobor_z_sieci": 0,
                    "oddanie_do_sieci": 0,
                    "koszt_poboru": 0,
                    "price": price,
                }
            stats["strefy"][zone]["pobor_z_sieci"] += pobor_z_sieci
            stats["strefy"][zone]["oddanie_do_sieci"] += oddanie_do_sieci
            stats["strefy"][zone]["koszt_poboru"] += pobor_z_sieci * price

        wyniki_symulacji.append(
            SimulationResult(
                timestamp=rekord.timestamp,
                pobor_z_sieci=pobor_z_sieci,
                oddanie_do_sieci=oddanie_do_sieci,
                pobor_z_magazynu=pobor_z_magazynu,
                oddanie_do_magazynu=oddanie_do_magazynu,
                stan_magazynu=stan_magazynu,
            )
        )

    # Cost calculation based on aggregated zone data
    if net_metering_ratio is not None:
        total_cost = 0.0
        rollover_credit = 0.0
        zone_prices = {zone: stats["strefy"][zone]["price"] for zone in stats["strefy"]}
        sorted_zones = sorted(zone_prices, key=zone_prices.get, reverse=True)

        for zone in sorted_zones:
            zone_stats = stats["strefy"][zone]
            price = zone_prices[zone]
            pobor_z_sieci = zone_stats["pobor_z_sieci"]
            oddanie_do_sieci = zone_stats["oddanie_do_sieci"]
            magazyn_w_strefie = oddanie_do_sieci * net_metering_ratio
            dostepny_kredyt = magazyn_w_strefie + rollover_credit
            energia_do_oplacenia = max(0, pobor_z_sieci - dostepny_kredyt)
            koszt_strefy = energia_do_oplacenia * price
            total_cost += koszt_strefy
            zone_stats["koszt_poboru"] = koszt_strefy
            zone_stats["magazyn_w_strefie"] = magazyn_w_strefie
            zone_stats["kredyt_z_poprzedniej"] = rollover_credit
            zone_stats["energia_do_oplacenia"] = energia_do_oplacenia
            rollover_credit = max(0, dostepny_kredyt - pobor_z_sieci)

        stats["calkowity_koszt"] = total_cost
        stats["niewykorzystany_kredyt_koncowy"] = rollover_credit
    else:
        stats["calkowity_koszt"] = sum(zone_stats["koszt_poboru"] for zone_stats in stats["strefy"].values())

    fixed_fee = tariff_manager.get_fixed_fee(tariff) * num_months
    stats["oplaty_stale"] = fixed_fee
    if "calkowity_koszt" in stats:
        stats["calkowity_koszt"] += fixed_fee

    oryginalny_pobor = sum(d.pobor_przed for d in data)
    calkowity_pobor_z_sieci = sum(zone_stats["pobor_z_sieci"] for zone_stats in stats["strefy"].values())
    stats["oszczednosc"] = oryginalny_pobor - calkowity_pobor_z_sieci

    return stats, pd.DataFrame(wyniki_symulacji)


def print_analysis_summary(
    summary: Dict[str, Any],
    capacity: float,
    tariff: str,
    net_metering_ratio: Optional[float],
):
    """Prints a formatted summary of the analysis results."""
    header = "--- Analiza zużycia i kosztów ---"
    if capacity > 0:
        header = f"--- Wyniki symulacji magazynu fizycznego ({capacity} kWh) dla taryfy {tariff.upper()} ---"
    print(f"\n{header}")

    for zone, stats in sorted(summary.get("strefy", {}).items()):
        print(f"\n--- STREFA: {zone.upper()} (cena: {stats.get('price', 0):.2f} zł/kWh) ---")
        pobor_z_sieci = stats.get("pobor_z_sieci", 0)
        oddanie_do_sieci = stats.get("oddanie_do_sieci", 0)

        # In case of capacity=0, these are just the balanced values
        if capacity > 0:
            print(f"Energia pobrana z sieci: {pobor_z_sieci:.3f} kWh")
            print(f"Energia oddana do sieci:  {oddanie_do_sieci:.3f} kWh")
        else:
            print(f"Energia pobrana (po bilansowaniu): {pobor_z_sieci:.3f} kWh")
            print(f"Energia oddana (po bilansowaniu):  {oddanie_do_sieci:.3f} kWh")

        if net_metering_ratio is not None:
            print(
                f"Wytworzony kredyt w strefie ({int(net_metering_ratio * 100)}%): {stats.get('magazyn_w_strefie', 0):.3f} kWh"
            )
            print(f"Kredyt z poprzedniej strefy: {stats.get('kredyt_z_poprzedniej', 0):.3f} kWh")
            print(
                f"Energia do opłacenia w strefie: {stats.get('energia_do_oplacenia', 0):.3f} kWh (koszt: {stats.get('koszt_poboru', 0):.2f} zł)"
            )
        else:
            print(f"Koszt energii pobranej: {stats.get('koszt_poboru', 0):.2f} zł")

    print("\n---------------------------------------------")
    print(f"OPLATY STALE: {summary.get('oplaty_stale', 0):.2f} zł")
    koszt_label = "SUMARYCZNY KOSZT (z magazynem)" if capacity > 0 else "SUMARYCZNY KOSZT (po rozliczeniu)"
    print(f"{koszt_label}: {summary.get('calkowity_koszt', 0):.2f} zł")

    if net_metering_ratio is not None:
        print(f"Niewykorzystany kredyt na koniec okresu: {summary.get('niewykorzystany_kredyt_koncowy', 0):.3f} kWh")
    if capacity > 0:
        print(f"Zaoszczedzona energia dzieki magazynowi: {summary.get('oszczednosc', 0):.3f} kWh")
    print("---------------------------------------------")


def run_tariff_comparison(
    data: List[EnergyData],
    tariff_manager: TariffManager,
    capacity: float,
    net_metering_ratio: Optional[float],
    storage_efficiency: float,
    verbose: bool = False,
):
    """
    Calculates and prints the cost for all available tariffs, with or without
    a physical storage simulation.
    """
    all_tariffs = tariff_manager.get_all_tariffs()
    results = {}
    header = "--- Porównanie taryf ---"
    if capacity > 0:
        header = (
            f"--- Porównanie taryf z magazynem fizycznym ({capacity} kWh, sprawność {int(storage_efficiency*100)}%) ---"
        )
    print(f"\n{header}")

    if verbose:
        print("Tryb szczegółowy włączony. Pokazywanie pełnej analizy dla każdej taryfy.")

    for tariff in all_tariffs:
        summary, _ = run_full_analysis(
            data,
            capacity,
            tariff_manager,
            tariff,
            net_metering_ratio,
            storage_efficiency,
        )
        if verbose:
            print_analysis_summary(summary, capacity, tariff, net_metering_ratio)

        cost = summary.get("calkowity_koszt")
        if cost is not None:
            results[tariff] = cost

    sorted_results = sorted(results.items(), key=lambda item: item[1])

    if verbose:
        print(f"\n{'='*20} PODSUMOWANIE PORÓWNANIA {'='*20}")

    print(f"Analiza dla okresu od {data[0].timestamp.date()} do {data[-1].timestamp.date()}")
    if net_metering_ratio:
        print(f"Uwzględniono net-metering ze współczynnikiem {net_metering_ratio}")
    print("---------------------------------------------")
    for tariff, cost in sorted_results:
        print(f"Taryfa {tariff:<5}: {cost:>10.2f} zł")
    print("---------------------------------------------")

    if sorted_results:
        best_tariff, best_cost = sorted_results[0]
        print(f"\nNajkorzystniejsza taryfa w tym okresie: {best_tariff} ({best_cost:.2f} zł)")
    else:
        print("Nie udało się obliczyć kosztów dla żadnej taryfy.")
    return results


def run_rce_analysis(data: List[EnergyData], hourly_prices: Dict[datetime, float]):
    if not data or not hourly_prices:
        print("Brak danych lub cen RCE do przeprowadzenia analizy.")
        return
    total_cost, total_income = 0.0, 0.0
    for record in data:
        price = hourly_prices.get(record.timestamp)
        if price is not None and not pd.isna(price):
            total_cost += record.pobor * price
            total_income += record.oddanie * price
        else:
            print(f"Ostrzeżenie: Brak ceny RCE dla godziny {record.timestamp}.")
    print("\n--- Analiza finansowa (ceny RCE) ---")
    print(f"SUMARYCZNY KOSZT energii pobranej: {total_cost:.2f} zł")
    print(f"SUMARYCZNY PRZYCHÓD z energii oddanej: {total_income:.2f} zł")
    print(f"BILANS FINANSOWY (przychód - koszt): {total_income - total_cost:.2f} zł")
    print("----------------------------------------")


def filter_data_by_date(
    data: List[EnergyData], start_date_str: Optional[str], end_date_str: Optional[str]
) -> List[EnergyData]:
    if not data or not (start_date_str or end_date_str):
        return data
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else None
        end_date = (
            datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59) if end_date_str else None
        )
    except ValueError:
        print("Błąd: Niepoprawny format daty. Użyj formatu RRRR-MM-DD.")
        return []
    if start_date and end_date and start_date > end_date:
        print("Błąd: Data początkowa nie może być późniejsza niż data końcowa.")
        return []
    print(f"\nFiltrowanie danych w zakresie od {start_date_str or 'początku'} do {end_date_str or 'końca'}...")
    filtered_list = [
        d for d in data if (not start_date or d.timestamp >= start_date) and (not end_date or d.timestamp <= end_date)
    ]
    print(f"Po filtrowaniu pozostało {len(filtered_list)} rekordów.")
    return filtered_list


def aggregate_daily_data(data: List[EnergyData]) -> pd.DataFrame:
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["date"] = df["timestamp"].dt.date
    daily_df = (
        df.groupby("date")
        .agg(
            pobor_przed=("pobor_przed", "sum"),
            oddanie_przed=("oddanie_przed", "sum"),
            pobor=("pobor", "sum"),
            oddanie=("oddanie", "sum"),
        )
        .reset_index()
    )
    return daily_df


def export_to_csv(df: pd.DataFrame, file_path: str):
    if df.empty:
        print("Brak danych do wyeksportowania.")
        return
    try:
        df.to_csv(file_path, index=False, decimal=",", sep=";", float_format="%.3f")
        print(f"\nPomyślnie wyeksportowano dane do pliku: {file_path}")
    except Exception as e:
        print(f"\nBłąd podczas eksportowania pliku CSV: {e}")


def calculate_optimal_capacity(
    hourly_data: List[EnergyData],
    daily_data: pd.DataFrame,
    tariff_manager: TariffManager,
    tariff: str,
):
    if daily_data.empty or not hourly_data:
        return
    hourly_df = pd.DataFrame(hourly_data)
    hourly_df["date"] = hourly_df["timestamp"].dt.date
    net_export_days = daily_data[daily_data["oddanie"] > daily_data["pobor"]]
    capacity_for_export_days = 0
    if not net_export_days.empty:
        required_capacities = [hourly_df[hourly_df["date"] == day]["pobor"].sum() for day in net_export_days["date"]]
        capacity_for_export_days = max(required_capacities) if required_capacities else 0
    capacity_for_import_days = 0
    expensive_zone_name = None  # Initialize to None

    # Dynamically find the name of the most expensive zone for the given tariff
    tariff_rules = tariff_manager.tariffs_df[tariff_manager.tariffs_df["tariff"].str.lower() == tariff.lower()].copy()
    if not tariff_rules.empty:
        tariff_rules["total_price"] = tariff_rules["energy_price"] + tariff_rules["dist_price"]
        expensive_zone_name = tariff_rules.loc[tariff_rules["total_price"].idxmax()]["zone_name"]

        if expensive_zone_name:
            hourly_df["zone"] = hourly_df["timestamp"].apply(
                lambda ts: tariff_manager.get_zone_and_price(ts, tariff)[0] or "poza strefa"
            )
            # Arbitrage capacity is the max consumption in the high zone on any given day
            pobor_w_strefie_wysokiej = (
                hourly_df[hourly_df["zone"] == expensive_zone_name].groupby("date")["pobor_przed"].sum()
            )
            capacity_for_import_days = pobor_w_strefie_wysokiej.max() if not pobor_w_strefie_wysokiej.empty else 0
    optimal_capacity = max(capacity_for_export_days, capacity_for_import_days)
    print("\n--- Kalkulacja optymalnej pojemności magazynu ---")
    print(f"Pojemność wymagana dla dni z nadprodukcją: {capacity_for_export_days:.3f} kWh")
    print(f"Pojemność wymagana dla arbitrażu taryfowego: {capacity_for_import_days:.3f} kWh")
    print("Optymalna pojemność (większa z powyższych):")
    print(f"Wynik: {optimal_capacity:.3f} kWh")
    print("--------------------------------------------------")


def analyze_daily_trends(daily_df: pd.DataFrame):
    if daily_df.empty:
        return
    net_export_days_df = daily_df[daily_df["oddanie"] > daily_df["pobor"]]
    net_export_days_count = len(net_export_days_df)
    total_days = len(daily_df)
    percentage = (net_export_days_count / total_days) * 100 if total_days > 0 else 0
    print("\n--- Analiza trendów dziennych ---")
    print(f"Liczba dni z nadprodukcją energii: {net_export_days_count} z {total_days} dni")
    print(f"Procent dni z nadprodukcją energii: {percentage:.2f}%")
    print("-----------------------------------")


def find_missing_hours(data: List[EnergyData], start_date_str: Optional[str], end_date_str: Optional[str]):
    if not data or not (start_date_str or end_date_str):
        return
    df = pd.DataFrame(data).set_index("timestamp")
    start_time = pd.to_datetime(start_date_str) if start_date_str else df.index.min()
    end_time = pd.to_datetime(end_date_str).replace(hour=23, minute=59) if end_date_str else df.index.max()
    expected_range = pd.date_range(start=start_time, end=end_time, freq="h")
    missing_timestamps = expected_range.difference(df.index)
    if not missing_timestamps.empty:
        print("\n--- UWAGA: Wykryto brakujące godziny w danych ---")
        if len(missing_timestamps) > 24:
            print(f"Wykryto {len(missing_timestamps)} brakujących godzin. Wyświetlanie może być skrócone.")
        for ts in missing_timestamps[:24]:
            print(f"Brak danych dla godziny: {ts.strftime('%Y-%m-%d %H:%M')}")
        if len(missing_timestamps) > 24:
            print("...")
        print("-------------------------------------------------")
