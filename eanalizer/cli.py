import argparse
import glob
import os

from .data_loader import load_from_enea_csv
from .tariffs import TariffManager
from .price_fetcher import get_hourly_rce_prices
from .core import (
    filter_data_by_date,
    export_to_csv,
    simulate_physical_storage,
    run_analysis_with_tariffs,
    run_rce_analysis,
    find_missing_hours,
)
from .config import load_config


def main():
    """Glowna funkcja uruchomieniowa dla CLI."""
    parser = argparse.ArgumentParser(description="Analizator danych energetycznych.")

    # Grupa argumentow wykluczajacych sie: albo pliki, albo katalog
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-p",
        "--pliki",
        nargs="+",
        help="Lista pojedynczych plikow z danymi do analizy.",
    )
    group.add_argument(
        "-k",
        "--katalog",
        default=None,
        help="Sciezka do katalogu z plikami .csv. Nadpisuje sciezke z konfiguracji.",
    )

    parser.add_argument(
        "-t",
        "--taryfa",
        choices=["G11", "G12", "G12w"],
        default="G11",
        help="Okresla taryfe energetyczna (domyslnie: G11).",
    )
    parser.add_argument(
        "--data-start", help="Data poczatkowa analizy (format RRRR-MM-DD)."
    )
    parser.add_argument(
        "--data-koniec", help="Data koncowa analizy (format RRRR-MM-DD)."
    )
    parser.add_argument(
        "--magazyn-fizyczny",
        type=float,
        help="Uruchamia symulacje fizycznego magazynu o podanej pojemnosci w kWh.",
    )
    parser.add_argument(
        "--eksport-symulacji",
        help="Sciezka do pliku CSV z wynikami symulacji godzinowej.",
    )
    parser.add_argument(
        "--eksport-dzienny",
        help="Sciezka do pliku CSV z zagregowanymi danymi dziennymi.",
    )
    parser.add_argument(
        "--oblicz-optymalny-magazyn",
        action="store_true",
        help="Oblicza optymalna pojemnosc magazynu.",
    )
    parser.add_argument(
        "--z-cenami-rce",
        action="store_true",
        help="Uzyj rzeczywistych cen RCE zamiast stalych cen taryfowych.",
    )
    parser.add_argument(
        "--z-netmetering",
        action="store_true",
        help="Wlacza obliczenia dla wirtualnego magazynu net-metering.",
    )
    parser.add_argument(
        "--wspolczynnik-netmetering",
        type=float,
        default=0.8,
        choices=[0.7, 0.8],
        help="Wspolczynnik dla energii oddawanej w net-meteringu (domyslnie: 0.8).",
    )

    args = parser.parse_args()

    # Wczytaj konfiguracje aplikacji. Jesli nie istnieje, uzytkownik zostanie
    # poproszony o jej utworzenie.
    app_cfg = load_config()

    files_to_process = []
    if args.pliki:
        files_to_process = args.pliki
    else:
        # Uzyj katalogu podanego w argumencie lub tego z konfiguracji
        katalog = args.katalog if args.katalog is not None else str(app_cfg.data_dir)
        path = os.path.join(katalog, "*.csv")
        files_to_process = sorted(glob.glob(path))

    if not files_to_process:
        katalog_info = args.katalog if args.katalog is not None else app_cfg.data_dir
        print(f"Nie znaleziono plikow .csv do przetworzenia w: {katalog_info}")
        print("Uruchom 'enea-downloader-cli', aby pobrac dane.")
        return

    print(f"Znaleziono {len(files_to_process)} plikow do przetworzenia:")
    for f in files_to_process:
        print(f" - {f}")

    all_energy_data = []
    for file_path in files_to_process:
        all_energy_data.extend(load_from_enea_csv(file_path))

    all_energy_data.sort(key=lambda x: x.timestamp)

    if all_energy_data:
        print(f"\nLacznia wczytano {len(all_energy_data)} rekordow.")
        oldest_date = all_energy_data[0].timestamp
        newest_date = all_energy_data[-1].timestamp
        print(
            f"Najstarsze dane pochodza z: {oldest_date.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print(f"Najnowsze dane pochodza z: {newest_date.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("\nNie wczytano zadnych rekordow.")
        return

    filtered_data = filter_data_by_date(
        all_energy_data, args.data_start, args.data_koniec
    )

    if not filtered_data:
        print("Brak danych w podanym zakresie dat do dalszej analizy.")
        return

    if args.data_start or args.data_koniec:
        find_missing_hours(filtered_data, args.data_start, args.data_koniec)

    min_year = min(d.timestamp.year for d in filtered_data)
    max_year = max(d.timestamp.year for d in filtered_data)

    tariff_manager = TariffManager(
        str(app_cfg.tariffs_file), years=range(min_year, max_year + 1)
    )

    if args.z_cenami_rce:
        start_date = filtered_data[0].timestamp
        end_date = filtered_data[-1].timestamp
        hourly_prices = get_hourly_rce_prices(
            start_date, end_date, cache_dir=app_cfg.cache_dir
        )
        run_rce_analysis(filtered_data, hourly_prices)
    elif args.magazyn_fizyczny and args.magazyn_fizyczny > 0:
        print(
            f"\nUruchamiam symulacje fizycznego magazynu energii o pojemnosci {args.magazyn_fizyczny} kWh..."
        )
        net_metering_ratio = (
            args.wspolczynnik_netmetering if args.z_netmetering else None
        )
        summary, simulation_df = simulate_physical_storage(
            filtered_data,
            args.magazyn_fizyczny,
            tariff_manager,
            args.taryfa,
            net_metering_ratio=net_metering_ratio,
        )
        print("\n--- Wyniki symulacji magazynu fizycznego ---")
        for zone, stats in sorted(summary["strefy"].items()):
            print(
                f"\n--- STREFA: {zone.upper()} (cena: {stats['price']:.2f} zl/kWh) ---"
            )
            print(f"Energia pobrana z sieci: {stats['pobor_z_sieci']:.3f} kWh")
            print(f"Energia oddana do sieci:  {stats['oddanie_do_sieci']:.3f} kWh")
            if net_metering_ratio is not None:
                print(
                    f"Wytworzony kredyt w strefie ({int(net_metering_ratio * 100)}%): {stats.get('magazyn_w_strefie', 0):.3f} kWh"
                )
                print(
                    f"Kredyt z poprzedniej strefy: {stats.get('kredyt_z_poprzedniej', 0):.3f} kWh"
                )
                print(
                    f"Energia do oplacenia w strefie: {stats.get('energia_do_oplacenia', 0):.3f} kWh (koszt: {stats.get('koszt_poboru', 0):.2f} zl)"
                )
            else:
                print(f"Koszt poboru z sieci: {stats.get('koszt_poboru', 0):.2f} zl")
        print("\n---------------------------------------------")
        print(
            f"SUMARYCZNY KOSZT (z magazynem): {summary.get('calkowity_koszt', 0):.2f} zl"
        )
        if net_metering_ratio is not None:
            print(
                f"Niewykorzystany kredyt na koniec okresu: {summary.get('niewykorzystany_kredyt_koncowy', 0):.3f} kWh"
            )
        print(
            f"Zaoszczedzona energia dzieki magazynowi: {summary.get('oszczednosc', 0):.3f} kWh"
        )
        print("---------------------------------------------")
        if args.eksport_symulacji:
            export_to_csv(simulation_df, args.eksport_symulacji)
    else:
        net_metering_ratio = (
            args.wspolczynnik_netmetering if args.z_netmetering else None
        )
        run_analysis_with_tariffs(
            data=filtered_data,
            tariff=args.taryfa,
            tariff_manager=tariff_manager,
            should_calc_optimal_capacity=args.oblicz_optymalny_magazyn,
            daily_export_path=args.eksport_dzienny,
            net_metering_ratio=net_metering_ratio,
        )


if __name__ == "__main__":
    main()
