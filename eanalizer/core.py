from typing import List, Optional
from datetime import datetime
from .models import EnergyData
import pandas as pd

def filter_data_by_date(data: List[EnergyData], start_date_str: Optional[str], end_date_str: Optional[str]) -> List[EnergyData]:
    """Filtruje listę danych na podstawie podanego zakresu dat."""
    if not start_date_str and not end_date_str:
        print("Nie podano zakresu dat, analizuję cały zbiór.")
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

    print(f"Filtrowanie danych w zakresie od {start_date_str or 'początku'} do {end_date_str or 'końca'}...")
    
    filtered_list = data
    if start_date:
        filtered_list = [d for d in filtered_list if d.timestamp >= start_date]
    if end_date:
        filtered_list = [d for d in filtered_list if d.timestamp <= end_date]
    
    print(f"Po filtrowaniu pozostało {len(filtered_list)} rekordów.")
    return filtered_list

def calculate_basic_stats(data: List[EnergyData]):
    """Oblicza i wyświetla podstawowe statystyki dla podanego zestawu danych."""
    if not data:
        print("Brak danych do analizy (po filtrowaniu).")
        return

    total_pobrana_przed = sum(d.pobor_przed for d in data)
    total_oddana_przed = sum(d.oddanie_przed for d in data)
    total_pobrana_po = sum(d.pobor for d in data)
    total_oddana_po = sum(d.oddanie for d in data)
    energia_zbilansowana = total_oddana_przed - total_oddana_po
    magazyn_net_metering = (total_oddana_po * 0.8) - total_pobrana_po

    print("\n--- Podstawowe statystyki dla wybranego okresu ---")
    print(f"Ilość pobranej energii (przed bilansowaniem): {total_pobrana_przed:.3f} kWh")
    print(f"Ilość oddanej energii (przed bilansowaniem):  {total_oddana_przed:.3f} kWh")
    print("-----------------------------------------------------")
    print(f"Ilość pobranej energii (po bilansowaniu):   {total_pobrana_po:.3f} kWh")
    print(f"Ilość oddanej energii (po bilansowaniu):    {total_oddana_po:.3f} kWh")
    print("-----------------------------------------------------")
    print(f'Energia podlegająca autokonsumpcji poprzez bilansowanie godzinne: {energia_zbilansowana:.3f} kWh')
    print(f'Stan magazynu energii (net-metering): {magazyn_net_metering:.3f} kWh')
    print("-----------------------------------------------------")

def analyze_daily_trends(daily_df: pd.DataFrame):
    """Analizuje trendy w danych dziennych, np. liczbę dni z nadprodukcją."""
    if daily_df.empty:
        return

    # Dzień z nadprodukcją to taki, gdzie energia oddana (po bilansowaniu) jest większa niż pobrana
    net_export_days_df = daily_df[daily_df['oddanie'] > daily_df['pobor']]
    net_export_days_count = len(net_export_days_df)
    total_days = len(daily_df)
    
    percentage = (net_export_days_count / total_days) * 100 if total_days > 0 else 0

    print("\n--- Analiza trendów dziennych ---")
    print(f"Liczba dni z nadprodukcją energii: {net_export_days_count} z {total_days} dni")
    print(f"Procent dni z nadprodukcją energii: {percentage:.2f}%")
    print("-----------------------------------")

def aggregate_daily_data(data: List[EnergyData]) -> pd.DataFrame:
    """Agreguje dane godzinowe do postaci dziennych sum."""
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
    """Eksportuje DataFrame do pliku CSV."""
    if df.empty:
        print("Brak danych do wyeksportowania.")
        return
    
    try:
        df.to_csv(file_path, index=False, decimal=',', sep=';', float_format='%.3f')
        print(f"\nPomyślnie wyeksportowano dane dzienne do pliku: {file_path}")
    except Exception as e:
        print(f"\nBłąd podczas eksportowania pliku CSV: {e}")