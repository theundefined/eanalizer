from typing import List, Optional, Dict, Tuple, Any
from datetime import datetime
from .models import EnergyData, SimulationResult
from .tariffs import TariffManager
import pandas as pd


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
        start_date = (
            datetime.strptime(start_date_str, "%Y-%m-%d") if start_date_str else None
        )
        end_date = (
            datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            if end_date_str
            else None
        )
    except ValueError:
        print("Błąd: Niepoprawny format daty. Użyj formatu RRRR-MM-DD.")
        return []
    if start_date and end_date and start_date > end_date:
        print("Błąd: Data początkowa nie może być późniejsza niż data końcowa.")
        return []
    print(
        f"\nFiltrowanie danych w zakresie od {start_date_str or 'początku'} do {end_date_str or 'końca'}..."
    )
    filtered_list = [
        d
        for d in data
        if (not start_date or d.timestamp >= start_date)
        and (not end_date or d.timestamp <= end_date)
    ]
    print(f"Po filtrowaniu pozostało {len(filtered_list)} rekordów.")
    return filtered_list


def run_analysis_with_tariffs(
    data: List[EnergyData],
    tariff: str,
    tariff_manager: TariffManager,  # Accept a TariffManager instance
    should_calc_optimal_capacity: bool,
    daily_export_path: Optional[str],
    net_metering_ratio: Optional[float],
):
    """Analyzes data based on a given tariff using a provided TariffManager."""
    if not data:
        print("Brak danych do analizy.")
        return

    # tariff_manager is now passed in, so we don't create it here.
    zoned_data_raw: Dict[str, List[EnergyData]] = {}
    zone_prices: Dict[str, float] = {}
    for record in data:
        zone, price = tariff_manager.get_zone_and_price(record.timestamp, tariff)
        if zone:
            if zone not in zoned_data_raw:
                zoned_data_raw[zone] = []
                zone_prices[zone] = price
            zoned_data_raw[zone].append(record)

    sorted_zones = sorted(zone_prices, key=zone_prices.get, reverse=True)
    print("\n--- Analiza zużycia i kosztów (ceny stałe z taryfy) ---")

    rollover_credit = 0.0
    total_cost = 0.0

    for zone in sorted_zones:
        zone_data = zoned_data_raw.get(zone, [])
        price = zone_prices.get(zone, 0.0)
        print(f"\n--- STREFA: {zone.upper()} (cena: {price:.2f} zł/kWh) ---")

        total_pobrana_po = sum(d.pobor for d in zone_data)
        total_oddana_po = sum(d.oddanie for d in zone_data)

        print(f"Energia pobrana (po bilansowaniu): {total_pobrana_po:.3f} kWh")
        print(f"Energia oddana (po bilansowaniu):  {total_oddana_po:.3f} kWh")

        if net_metering_ratio is not None:
            magazyn_w_strefie = total_oddana_po * net_metering_ratio
            dostepny_kredyt = magazyn_w_strefie + rollover_credit
            energia_do_oplacenia = max(0, total_pobrana_po - dostepny_kredyt)
            koszt_strefy = energia_do_oplacenia * price
            total_cost += koszt_strefy
            # The rollover credit to be passed to the NEXT zone is what's left from the CURRENT zone's available credit
            rollover_credit = max(0, dostepny_kredyt - total_pobrana_po)

            print(
                f"Wytworzony kredyt w strefie ({int(net_metering_ratio * 100)}%): {magazyn_w_strefie:.3f} kWh"
            )
            # This line was confusing, let's show what was brought INTO this zone
            print(
                f"Kredyt z poprzedniej strefy: {dostepny_kredyt - magazyn_w_strefie:.3f} kWh"
            )
            print(
                f"Energia do opłacenia w strefie: {energia_do_oplacenia:.3f} kWh (koszt: {koszt_strefy:.2f} zł)"
            )
        else:
            koszt_strefy = total_pobrana_po * price
            total_cost += koszt_strefy
            print(f"Koszt energii pobranej: {koszt_strefy:.2f} zł")

    print("\n-----------------------------------------------------")
    print(f"SUMARYCZNY KOSZT ENERGII (po rozliczeniu): {total_cost:.2f} zł")
    if net_metering_ratio is not None:
        print(f"Niewykorzystany kredyt na koniec okresu: {rollover_credit:.3f} kWh")
    print("-----------------------------------------------------")

    daily_data_df = aggregate_daily_data(data)
    analyze_daily_trends(daily_data_df)

    if should_calc_optimal_capacity:
        calculate_optimal_capacity(data, daily_data_df, tariff_manager, tariff)

    if daily_export_path:
        export_to_csv(daily_data_df, daily_export_path)


def simulate_physical_storage(
    data: List[EnergyData],
    capacity: float,
    tariff_manager: TariffManager,
    tariff: str,
    net_metering_ratio: Optional[float] = None,
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    if not data:
        return {}, pd.DataFrame()

    stan_magazynu = 0.0
    wyniki_symulacji = []
    stats: Dict[str, Any] = {"strefy": {}}

    # First, run the hourly simulation
    for rekord in data:
        pobor_z_magazynu, oddanie_do_magazynu, pobor_z_sieci, oddanie_do_sieci = (
            0.0,
            0.0,
            0.0,
            0.0,
        )

        if rekord.oddanie_przed > rekord.pobor_przed:
            nadwyzka = rekord.oddanie_przed - rekord.pobor_przed
            do_naladowania = min(nadwyzka, capacity - stan_magazynu)
            oddanie_do_magazynu = do_naladowania
            stan_magazynu += do_naladowania
            oddanie_do_sieci = nadwyzka - do_naladowania
        elif rekord.pobor_przed > rekord.oddanie_przed:
            niedobor = rekord.pobor_przed - rekord.oddanie_przed
            do_rozladowania = min(niedobor, stan_magazynu)
            pobor_z_magazynu = do_rozladowania
            stan_magazynu -= do_rozladowania
            pobor_z_sieci = niedobor - do_rozladowania

        zone, price = tariff_manager.get_zone_and_price(rekord.timestamp, tariff)
        if zone:
            if zone not in stats["strefy"]:
                stats["strefy"][zone] = {
                    "pobor_z_sieci": 0,
                    "oddanie_do_sieci": 0,
                    "koszt_poboru": 0,
                    "price": price,
                }
            stats["strefy"][zone]["pobor_z_sieci"] += pobor_z_sieci
            stats["strefy"][zone]["oddanie_do_sieci"] += oddanie_do_sieci
            # We calculate gross cost here, but it will be overwritten if net-metering is on
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

    # Second, calculate costs based on aggregated zone data
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

            # Update stats for printing in cli
            zone_stats["koszt_poboru"] = koszt_strefy  # Overwrite with net cost
            zone_stats["magazyn_w_strefie"] = magazyn_w_strefie
            zone_stats["kredyt_z_poprzedniej"] = rollover_credit
            zone_stats["energia_do_oplacenia"] = energia_do_oplacenia

            rollover_credit = max(0, dostepny_kredyt - pobor_z_sieci)

        stats["calkowity_koszt"] = total_cost
        stats["niewykorzystany_kredyt_koncowy"] = rollover_credit
    else:
        stats["calkowity_koszt"] = sum(
            zone_stats["koszt_poboru"] for zone_stats in stats["strefy"].values()
        )

    oryginalny_pobor = sum(d.pobor_przed for d in data)
    calkowity_pobor_z_sieci = sum(
        zone_stats["pobor_z_sieci"] for zone_stats in stats["strefy"].values()
    )
    stats["oszczednosc"] = oryginalny_pobor - calkowity_pobor_z_sieci

    return stats, pd.DataFrame(wyniki_symulacji)


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
        required_capacities = [
            hourly_df[hourly_df["date"] == day]["pobor"].sum()
            for day in net_export_days["date"]
        ]
        capacity_for_export_days = (
            max(required_capacities) if required_capacities else 0
        )
    net_import_days = daily_data[daily_data["pobor"] > daily_data["oddanie"]]
    capacity_for_import_days = 0
    if not net_import_days.empty:
        hourly_df["zone"] = hourly_df["timestamp"].apply(
            lambda ts: tariff_manager.get_zone_and_price(ts, tariff)[0]
        )
        pobor_w_strefie_wysokiej = (
            hourly_df[
                (hourly_df["date"].isin(net_import_days["date"]))
                & (hourly_df["zone"] == "wysoka")
            ]
            .groupby("date")["pobor_przed"]
            .sum()
        )
        capacity_for_import_days = (
            pobor_w_strefie_wysokiej.max() if not pobor_w_strefie_wysokiej.empty else 0
        )
    optimal_capacity = max(capacity_for_export_days, capacity_for_import_days)
    print("\n--- Kalkulacja optymalnej pojemności magazynu ---")
    print(
        f"Pojemność wymagana dla dni z nadprodukcją: {capacity_for_export_days:.3f} kWh"
    )
    print(
        f"Pojemność wymagana dla arbitrażu taryfowego: {capacity_for_import_days:.3f} kWh"
    )
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
    print(
        f"Liczba dni z nadprodukcją energii: {net_export_days_count} z {total_days} dni"
    )
    print(f"Procent dni z nadprodukcją energii: {percentage:.2f}%")
    print("-----------------------------------")


def find_missing_hours(
    data: List[EnergyData], start_date_str: Optional[str], end_date_str: Optional[str]
):
    if not data or not (start_date_str or end_date_str):
        return
    df = pd.DataFrame(data).set_index("timestamp")
    start_time = pd.to_datetime(start_date_str) if start_date_str else df.index.min()
    end_time = (
        pd.to_datetime(end_date_str).replace(hour=23, minute=59)
        if end_date_str
        else df.index.max()
    )
    expected_range = pd.date_range(start=start_time, end=end_time, freq="h")
    missing_timestamps = expected_range.difference(df.index)
    if not missing_timestamps.empty:
        print("\n--- UWAGA: Wykryto brakujące godziny w danych ---")
        if len(missing_timestamps) > 24:
            print(
                f"Wykryto {len(missing_timestamps)} brakujących godzin. Wyświetlanie może być skrócone."
            )
        for ts in missing_timestamps[:24]:
            print(f"Brak danych dla godziny: {ts.strftime('%Y-%m-%d %H:%M')}")
        if len(missing_timestamps) > 24:
            print("...")
        print("-------------------------------------------------")
