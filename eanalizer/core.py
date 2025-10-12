from typing import List, Optional, Dict, Tuple, Any
from datetime import datetime
from .models import EnergyData, SimulationResult
from .tariffs import TariffManager
import pandas as pd

def filter_data_by_date(data: List[EnergyData], start_date_str: Optional[str], end_date_str: Optional[str]) -> List[EnergyData]:
    """Filtruje listę danych na podstawie podanego zakresu dat."""
    if not start_date_str and not end_date_str:
        return data

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d') if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59) if end_date_str else None
    except ValueError:
        print("Błąd: Niepoprawny format daty. Użyj formatu RRRR-MM-DD.")
        return []

    if start_date and end_date and start_date > end_date:
        print("Błąd: Data początkowa nie może być późniejsza niż data końcowa.")
        return []

    print(f"\nFiltrowanie danych w zakresie od {start_date_str or 'początku'} do {end_date_str or 'końca'}...")
    
    filtered_list = data
    if start_date:
        filtered_list = [d for d in filtered_list if d.timestamp >= start_date]
    if end_date:
        filtered_list = [d for d in filtered_list if d.timestamp <= end_date]
    
    print(f"Po filtrowaniu pozostało {len(filtered_list)} rekordów.")
    return filtered_list

def run_analysis_with_tariffs(data: List[EnergyData], tariff: str, should_calc_optimal_capacity: bool, daily_export_path: Optional[str]):
    """Główna funkcja uruchamiająca wszystkie standardowe analizy z uwzględnieniem taryf."""
    if not data:
        print("Brak danych do analizy.")
        return

    min_year = min(d.timestamp.year for d in data)
    max_year = max(d.timestamp.year for d in data)
    tariff_manager = TariffManager('config/tariffs.csv', years=range(min_year, max_year + 1))

    zoned_data: Dict[str, List[EnergyData]] = {}
    for record in data:
        zone = tariff_manager.get_zone(record.timestamp, tariff)
        if zone not in zoned_data:
            zoned_data[zone] = []
        zoned_data[zone].append(record)

    print("\n--- Podstawowe statystyki dla wybranego okresu (z podziałem na strefy) ---")
    for zone, zone_data in sorted(zoned_data.items()):
        print(f"\n--- STREFA: {zone.upper()} ---")
        calculate_zoned_stats(zone_data)
    
    daily_data_df = aggregate_daily_data(data)
    analyze_daily_trends(daily_data_df)

    if should_calc_optimal_capacity:
        calculate_optimal_capacity(data, daily_data_df, tariff_manager, tariff)

    if daily_export_path:
        export_to_csv(daily_data_df, daily_export_path)

def calculate_zoned_stats(data: List[EnergyData]):
    """Oblicza i wyświetla statystyki dla pojedynczej strefy taryfowej."""
    total_pobrana_przed = sum(d.pobor_przed for d in data)
    total_oddana_przed = sum(d.oddanie_przed for d in data)
    total_pobrana_po = sum(d.pobor for d in data)
    total_oddana_po = sum(d.oddanie for d in data)
    energia_zbilansowana = total_oddana_przed - total_oddana_po
    magazyn_net_metering = (total_oddana_po * 0.8) - total_pobrana_po

    print(f"Ilość pobranej energii (przed bilansowaniem): {total_pobrana_przed:.3f} kWh")
    print(f"Ilość oddanej energii (przed bilansowaniem):  {total_oddana_przed:.3f} kWh")
    print("-----------------------------------------------------")
    print(f"Ilość pobranej energii (po bilansowaniu):   {total_pobrana_po:.3f} kWh")
    print(f"Ilość oddanej energii (po bilansowaniu):    {total_oddana_po:.3f} kWh")
    print("-----------------------------------------------------")
    print(f'Energia podlegająca autokonsumpcji poprzez bilansowanie godzinne: {energia_zbilansowana:.3f} kWh')
    print(f'Stan magazynu energii (net-billing): {magazyn_net_metering:.3f} kWh')

def simulate_physical_storage(data: List[EnergyData], capacity: float, tariff_manager: TariffManager, tariff: str) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """Przeprowadza symulację fizycznego magazynu energii godzina po godzinie, zliczając wyniki dla stref taryfowych."""
    if not data:
        return {}, pd.DataFrame()

    stan_magazynu = 0.0
    wyniki_symulacji = []

    stats: Dict[str, Any] = {
        'pobor_z_sieci': {},
        'oddanie_do_sieci': {},
    }

    for rekord in data:
        pobor_z_magazynu = 0.0
        oddanie_do_magazynu = 0.0
        pobor_z_sieci = 0.0
        oddanie_do_sieci = 0.0

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

        zone = tariff_manager.get_zone(rekord.timestamp, tariff)
        if zone:
            stats['pobor_z_sieci'][zone] = stats['pobor_z_sieci'].get(zone, 0) + pobor_z_sieci
            stats['oddanie_do_sieci'][zone] = stats['oddanie_do_sieci'].get(zone, 0) + oddanie_do_sieci

        wyniki_symulacji.append(SimulationResult(
            timestamp=rekord.timestamp,
            pobor_z_sieci=pobor_z_sieci,
            oddanie_do_sieci=oddanie_do_sieci,
            pobor_z_magazynu=pobor_z_magazynu,
            oddanie_do_magazynu=oddanie_do_magazynu,
            stan_magazynu=stan_magazynu
        ))

    oryginalny_pobor = sum(d.pobor_przed for d in data)
    calkowity_pobor_z_sieci = sum(stats['pobor_z_sieci'].values())
    stats['oszczednosc'] = oryginalny_pobor - calkowity_pobor_z_sieci

    return stats, pd.DataFrame(wyniki_symulacji)

def aggregate_daily_data(data: List[EnergyData]) -> pd.DataFrame:
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df['date'] = df['timestamp'].dt.date

    daily_df = df.groupby('date').agg(
        pobor_przed=('pobor_przed', 'sum'),
        oddanie_przed=('oddanie_przed', 'sum'),
        pobor=('pobor', 'sum'),
        oddanie=('oddanie', 'sum')
    ).reset_index()

    return daily_df

def export_to_csv(df: pd.DataFrame, file_path: str):
    if df.empty:
        print("Brak danych do wyeksportowania.")
        return
    
    try:
        df.to_csv(file_path, index=False, decimal=',', sep=';', float_format='%.3f')
        print(f"\nPomyślnie wyeksportowano dane do pliku: {file_path}")
    except Exception as e:
        print(f"\nBłąd podczas eksportowania pliku CSV: {e}")

def calculate_optimal_capacity(hourly_data: List[EnergyData], daily_data: pd.DataFrame, tariff_manager: TariffManager, tariff: str):
    if daily_data.empty or not hourly_data:
        return

    hourly_df = pd.DataFrame(hourly_data)
    hourly_df['date'] = hourly_df['timestamp'].dt.date

    # --- Scenariusz 1: Dni z nadprodukcją ---
    net_export_days = daily_data[daily_data['oddanie'] > daily_data['pobor']]
    capacity_for_export_days = 0
    if not net_export_days.empty:
        required_capacities = [hourly_df[hourly_df['date'] == day]['pobor'].sum() for day in net_export_days['date']]
        capacity_for_export_days = max(required_capacities) if required_capacities else 0

    # --- Scenariusz 2: Dni z deficytem (arbitraż taryfowy) ---
    net_import_days = daily_data[daily_data['pobor'] > daily_data['oddanie']]
    capacity_for_import_days = 0
    if not net_import_days.empty:
        hourly_df['zone'] = hourly_df['timestamp'].apply(lambda ts: tariff_manager.get_zone(ts, tariff))
        pobor_w_strefie_wysokiej = hourly_df[
            (hourly_df['date'].isin(net_import_days['date'])) & 
            (hourly_df['zone'] == 'wysoka')
        ].groupby('date')['pobor_przed'].sum()
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

    net_export_days_df = daily_df[daily_df['oddanie'] > daily_df['pobor']]
    net_export_days_count = len(net_export_days_df)
    total_days = len(daily_df)
    
    percentage = (net_export_days_count / total_days) * 100 if total_days > 0 else 0

    print("\n--- Analiza trendów dziennych ---")
    print(f"Liczba dni z nadprodukcją energii: {net_export_days_count} z {total_days} dni")
    print(f"Procent dni z nadprodukcją energii: {percentage:.2f}%")
    print("-----------------------------------")