import argparse
import glob
import os
from datetime import datetime
from .data_loader import load_from_enea_csv
from .tariffs import TariffManager
from .price_fetcher import get_hourly_rce_prices
from .core import (
    filter_data_by_date, 
    export_to_csv, 
    simulate_physical_storage,
    run_analysis_with_tariffs,
    run_rce_analysis,
    find_missing_hours
)

def main():
    """Główna funkcja uruchomieniowa dla CLI."""
    parser = argparse.ArgumentParser(description="Analizator danych energetycznych.")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-p", "--pliki", nargs='+', help="Lista plików z danymi do analizy.")
    group.add_argument("-k", "--katalog", help="Ścieżka do katalogu, z którego zostaną wczytane wszystkie pliki .csv.")

    parser.add_argument("-t", "--taryfa", choices=['G11', 'G12', 'G12w'], default='G11', help="Określa taryfę energetyczną (domyślnie: G11).")
    parser.add_argument("--data-start", help="Data początkowa analizy (format RRRR-MM-DD).")
    parser.add_argument("--data-koniec", help="Data końcowa analizy (format RRRR-MM-DD).")

    parser.add_argument("--magazyn-fizyczny", type=float, help="Uruchamia symulację fizycznego magazynu o podanej pojemności w kWh.")
    parser.add_argument("--eksport-symulacji", help="Ścieżka do pliku CSV z wynikami symulacji godzinowej.")
    
    parser.add_argument("--eksport-dzienny", help="Ścieżka do pliku CSV z zagregowanymi danymi dziennymi.")
    parser.add_argument("--oblicz-optymalny-magazyn", action='store_true', help="Oblicza optymalną pojemność magazynu.")
    parser.add_argument("--z-cenami-rce", action='store_true', help="Użyj rzeczywistych cen RCE zamiast stałych cen taryfowych.")
    parser.add_argument("--z-netmetering", action='store_true', help="Włącza obliczenia dla wirtualnego magazynu net-metering.")
    parser.add_argument("--wspolczynnik-netmetering", type=float, default=0.8, choices=[0.7, 0.8], help="Współczynnik dla energii oddawanej w net-meteringu (domyślnie: 0.8).")

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
    
    if all_energy_data:
        print(f"\nŁącznie wczytano {len(all_energy_data)} rekordów.")
        oldest_date = all_energy_data[0].timestamp
        newest_date = all_energy_data[-1].timestamp
        print(f"Najstarsze dane pochodzą z: {oldest_date.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Najnowsze dane pochodzą z: {newest_date.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("\nNie wczytano żadnych rekordów.")

    filtered_data = filter_data_by_date(all_energy_data, args.data_start, args.data_koniec)
    
    if not filtered_data:
        print("Brak danych w podanym zakresie dat do dalszej analizy.")
        return

    if args.data_start or args.data_koniec:
        find_missing_hours(filtered_data, args.data_start, args.data_koniec)

    # --- GŁÓWNA LOGIKA PROGRAMU ---
    if args.z_cenami_rce:
        start_date = filtered_data[0].timestamp
        end_date = filtered_data[-1].timestamp
        hourly_prices = get_hourly_rce_prices(start_date, end_date)
        run_rce_analysis(filtered_data, hourly_prices)

    elif args.magazyn_fizyczny and args.magazyn_fizyczny > 0:
        min_year = min(d.timestamp.year for d in filtered_data) if filtered_data else datetime.now().year
        max_year = max(d.timestamp.year for d in filtered_data) if filtered_data else datetime.now().year
        tariff_manager = TariffManager('config/tariffs.csv', years=range(min_year, max_year + 1))

        print(f"\nUruchamiam symulację fizycznego magazynu energii o pojemności {args.magazyn_fizyczny} kWh...")
        net_metering_ratio = args.wspolczynnik_netmetering if args.z_netmetering else None
        summary, simulation_df = simulate_physical_storage(
            filtered_data, 
            args.magazyn_fizyczny, 
            tariff_manager, 
            args.taryfa,
            net_metering_ratio=net_metering_ratio
        )
        
        print("\n--- Wyniki symulacji magazynu fizycznego ---")
        for zone, stats in sorted(summary['strefy'].items()):
            print(f"\n--- STREFA: {zone.upper()} (cena: {stats['price']:.2f} zł/kWh) ---")
            print(f"Energia pobrana z sieci: {stats['pobor_z_sieci']:.3f} kWh")
            print(f"Energia oddana do sieci:  {stats['oddanie_do_sieci']:.3f} kWh")
            if net_metering_ratio is not None:
                print(f"Wytworzony kredyt w strefie ({int(net_metering_ratio*100)}%): {stats.get('magazyn_w_strefie', 0):.3f} kWh")
                print(f"Kredyt z poprzedniej strefy: {stats.get('kredyt_z_poprzedniej', 0):.3f} kWh")
                print(f"Energia do opłacenia w strefie: {stats.get('energia_do_oplacenia', 0):.3f} kWh (koszt: {stats.get('koszt_poboru', 0):.2f} zł)")
            else:
                print(f"Koszt poboru z sieci: {stats.get('koszt_poboru', 0):.2f} zł")

        print("\n---------------------------------------------")
        print(f"SUMARYCZNY KOSZT (z magazynem): {summary.get('calkowity_koszt', 0):.2f} zł")
        if net_metering_ratio is not None:
            print(f"Niewykorzystany kredyt na koniec okresu: {summary.get('niewykorzystany_kredyt_koncowy', 0):.3f} kWh")
        print(f"Zaoszczędzona energia dzięki magazynowi: {summary.get('oszczednosc', 0):.3f} kWh")
        print("---------------------------------------------")

        if args.eksport_symulacji:
            export_to_csv(simulation_df, args.eksport_symulacji)
    else:
        net_metering_ratio = args.wspolczynnik_netmetering if args.z_netmetering else None
        run_analysis_with_tariffs(
            data=filtered_data, 
            tariff=args.taryfa, 
            should_calc_optimal_capacity=args.oblicz_optymalny_magazyn, 
            daily_export_path=args.eksport_dzienny,
            net_metering_ratio=net_metering_ratio
        )

if __name__ == "__main__":
    main()