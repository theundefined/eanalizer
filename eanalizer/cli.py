import argparse
import glob
import os
from .data_loader import load_from_enea_csv
from .core import calculate_basic_stats, filter_data_by_date, aggregate_daily_data, export_to_csv, analyze_daily_trends

def main():
    """Główna funkcja uruchomieniowa dla CLI."""
    parser = argparse.ArgumentParser(description="Analizator danych energetycznych.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-p", "--pliki", nargs='+', help="Lista plików z danymi do analizy.")
    group.add_argument("-k", "--katalog", help="Ścieżka do katalogu, z którego zostaną wczytane wszystkie pliki .csv.")

    parser.add_argument("--data-start", help="Data początkowa analizy (format RRRR-MM-DD).")
    parser.add_argument("--data-koniec", help="Data końcowa analizy (format RRRR-MM-DD).")
    parser.add_argument("--eksport-dzienny", help="Ścieżka do pliku CSV, do którego zostaną zapisane zagregowane dane dzienne.")
    
    args = parser.parse_args()
    
    files_to_process = []
    if args.pliki:
        files_to_process = args.pliki
    elif args.katalog:
        path = os.path.join(args.katalog, '*.csv')
        files_to_process = sorted(glob.glob(path)) # Sortujemy dla pewności

    if not files_to_process:
        print("Nie znaleziono plików do przetworzenia.")
        return

    print(f"Znaleziono {len(files_to_process)} plików do przetworzenia:")
    for f in files_to_process:
        print(f" - {f}")

    # 1. Wczytanie i połączenie danych ze wszystkich plików
    all_energy_data = []
    for file_path in files_to_process:
        all_energy_data.extend(load_from_enea_csv(file_path))
    
    all_energy_data.sort(key=lambda x: x.timestamp)
    print(f"\nŁącznie wczytano {len(all_energy_data)} rekordów.")

    # 2. Filtrowanie danych wg zakresu dat
    filtered_data = filter_data_by_date(all_energy_data, args.data_start, args.data_koniec)
    
    # 3. Przeprowadzenie analizy na odfiltrowanych danych
    calculate_basic_stats(filtered_data)

    # 4. Agregacja dzienna, analiza trendów i eksport (jeśli zażądano)
    daily_data_df = aggregate_daily_data(filtered_data)
    analyze_daily_trends(daily_data_df)

    if args.eksport_dzienny:
        export_to_csv(daily_data_df, args.eksport_dzienny)

if __name__ == "__main__":
    main()
