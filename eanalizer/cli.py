import argparse
import glob
import os
from datetime import datetime
from .data_loader import load_from_enea_csv
from .tariffs import TariffManager
from .core import (
    filter_data_by_date, 
    export_to_csv, 
    simulate_physical_storage,
    run_analysis_with_tariffs
)

def main():
    """Główna funkcja uruchomieniowa dla CLI."""
    parser = argparse.ArgumentParser(description="Analizator danych energetycznych.")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-p", "--pliki", nargs='+', help="Lista plików z danymi do analizy.")
    group.add_argument("-k", "--katalog", help="Ścieżka do katalogu, z którego zostaną wczytane wszystkie pliki .csv.")

    parser.add_argument("-t", "--taryfa", choices=['G11', 'G12', 'G12w'], required=True, help="Określa taryfę energetyczną do analizy.")
    parser.add_argument("--data-start", help="Data początkowa analizy (format RRRR-MM-DD).")
    parser.add_argument("--data-koniec", help="Data końcowa analizy (format RRRR-MM-DD).")

    parser.add_argument("--magazyn-fizyczny", type=float, help="Uruchamia symulację fizycznego magazynu o podanej pojemności w kWh.")
    parser.add_argument("--eksport-symulacji", help="Ścieżka do pliku CSV, do którego zostaną zapisane szczegółowe wyniki symulacji godzinowej.")
    
    parser.add_argument("--eksport-dzienny", help="Ścieżka do pliku CSV, do którego zostaną zapisane zagregowane dane dzienne (w trybie analizy standardowej).")
    parser.add_argument("--oblicz-optymalny-magazyn", action='store_true', help="Oblicza optymalną pojemność magazynu uwzględniając arbitraż taryfowy.")

    args = parser.parse_args()
    
    files_to_process = []
    if args.pliki:
        files_to_process = args.pliki
    elif args.katalog:
        path = os.path.join(args.katalog, '*.csv')
        files_to_process = sorted(glob.glob(path))

    if not files_to_process:
        print("Nie znaleziono plików do przetworzenia.")
        return

    print(f"Znaleziono {len(files_to_process)} plików do przetworzenia:")
    for f in files_to_process:
        print(f" - {f}")

    all_energy_data = []
    for file_path in files_to_process:
        all_energy_data.extend(load_from_enea_csv(file_path))
    
    all_energy_data.sort(key=lambda x: x.timestamp)
    print(f"\nŁącznie wczytano {len(all_energy_data)} rekordów.")

    filtered_data = filter_data_by_date(all_energy_data, args.data_start, args.data_koniec)
    
    if not filtered_data:
        print("Brak danych w podanym zakresie dat do dalszej analizy.")
        return

    if args.magazyn_fizyczny and args.magazyn_fizyczny > 0:
        min_year = min(d.timestamp.year for d in filtered_data)
        max_year = max(d.timestamp.year for d in filtered_data)
        tariff_manager = TariffManager('config/tariffs.csv', years=range(min_year, max_year + 1))

        print(f"\nUruchamiam symulację fizycznego magazynu energii o pojemności {args.magazyn_fizyczny} kWh...")
        summary, simulation_df = simulate_physical_storage(filtered_data, args.magazyn_fizyczny, tariff_manager, args.taryfa)
        
        print("\n--- Wyniki symulacji magazynu fizycznego ---")
        for zone, value in sorted(summary['pobor_z_sieci'].items()):
            print(f"Energia pobrana z sieci w strefie [{zone.upper()}]: {value:.3f} kWh")
        for zone, value in sorted(summary['oddanie_do_sieci'].items()):
            print(f"Energia oddana do sieci w strefie [{zone.upper()}]: {value:.3f} kWh")
        
        print("---------------------------------------------")
        print(f"Zaoszczędzona energia dzięki magazynowi: {summary.get('oszczednosc', 0):.3f} kWh")
        print("---------------------------------------------")

        if args.eksport_symulacji:
            export_to_csv(simulation_df, args.eksport_symulacji)
    else:
        run_analysis_with_tariffs(
            data=filtered_data, 
            tariff=args.taryfa, 
            should_calc_optimal_capacity=args.oblicz_optymalny_magazyn, 
            daily_export_path=args.eksport_dzienny
        )

if __name__ == "__main__":
    main()