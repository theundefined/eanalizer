import argparse
import glob
import os

from .data_loader import load_from_enea_csv
from .tariffs import TariffManager
from .price_fetcher import get_hourly_rce_prices
from .core import (
    filter_data_by_date,
    export_to_csv,
    run_full_analysis,
    print_analysis_summary,
    run_rce_analysis,
    find_missing_hours,
    run_tariff_comparison,
    analyze_daily_trends,
    calculate_optimal_capacity,
    aggregate_daily_data,
)
from .config import load_config


def main():
    """Glowna funkcja uruchomieniowa dla CLI."""
    parser = argparse.ArgumentParser(description="Analizator danych energetycznych.")

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
        help="Sciezka do katalogu z plikami .csv.",
    )

    parser.add_argument(
        "-t",
        "--taryfa",
        default="G11",
        help="Okresla taryfe energetyczna dla pojedynczej analizy (domyslnie: G11).",
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
        help="Pojemnosc fizycznego magazynu w kWh (np. 10.0).",
    )
    parser.add_argument(
        "--sprawnosc-magazynu",
        type=float,
        default=0.9,
        help="Sprawność magazynu fizycznego (round-trip, domyslnie: 0.90, czyli 90%%).",
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
    parser.add_argument(
        "--porownaj-taryfy",
        action="store_true",
        help="Uruchamia porównanie wszystkich dostępnych taryf dla zadanego okresu.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Włącza tryb szczegółowy dla porównania taryf.",
    )

    args = parser.parse_args()
    app_cfg = load_config()

    # Data loading
    files_to_process = []
    if args.pliki:
        files_to_process = args.pliki
    else:
        katalog = args.katalog if args.katalog is not None else str(app_cfg.data_dir)
        path = os.path.join(katalog, "*.csv")
        files_to_process = sorted(glob.glob(path))

    if not files_to_process:
        katalog_info = args.katalog if args.katalog is not None else app_cfg.data_dir
        print(f"Nie znaleziono plikow .csv do przetworzenia w: {katalog_info}")
        return

    print(f"Znaleziono {len(files_to_process)} plikow do przetworzenia:")
    all_energy_data = []
    for file_path in files_to_process:
        all_energy_data.extend(load_from_enea_csv(file_path))
    all_energy_data.sort(key=lambda x: x.timestamp)
    print(f"\nLacznia wczytano {len(all_energy_data)} rekordow.")

    # Data filtering
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

    # Determine analysis parameters
    net_metering_ratio = args.wspolczynnik_netmetering if args.z_netmetering else None
    capacity = (
        args.magazyn_fizyczny
        if args.magazyn_fizyczny and args.magazyn_fizyczny > 0
        else 0.0
    )
    storage_efficiency = args.sprawnosc_magazynu

    # --- Main analysis logic ---
    if args.z_cenami_rce:
        start_date = filtered_data[0].timestamp
        end_date = filtered_data[-1].timestamp
        hourly_prices = get_hourly_rce_prices(
            start_date, end_date, cache_dir=app_cfg.cache_dir
        )
        run_rce_analysis(filtered_data, hourly_prices)
    elif args.porownaj_taryfy:
        run_tariff_comparison(
            data=filtered_data,
            tariff_manager=tariff_manager,
            capacity=capacity,
            net_metering_ratio=net_metering_ratio,
            storage_efficiency=storage_efficiency,
            verbose=args.verbose,
        )
    else:
        # Single analysis run
        summary, simulation_df = run_full_analysis(
            data=filtered_data,
            capacity=capacity,
            tariff_manager=tariff_manager,
            tariff=args.taryfa,
            net_metering_ratio=net_metering_ratio,
            storage_efficiency=storage_efficiency,
        )
        print_analysis_summary(summary, capacity, args.taryfa, net_metering_ratio)

        # Post-analysis actions for single run
        daily_data_df = aggregate_daily_data(filtered_data)
        analyze_daily_trends(daily_data_df)

        if args.oblicz_optymalny_magazyn:
            calculate_optimal_capacity(
                filtered_data, daily_data_df, tariff_manager, args.taryfa
            )

        if args.eksport_dzienny:
            export_to_csv(daily_data_df, args.eksport_dzienny)

        if args.eksport_symulacji and simulation_df is not None:
            export_to_csv(simulation_df, args.eksport_symulacji)


if __name__ == "__main__":
    main()
