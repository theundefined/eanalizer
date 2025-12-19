import argparse
import glob
import gettext
import locale
import os
from pathlib import Path

from .config import load_config
from .core import (
    aggregate_daily_data,
    analyze_daily_trends,
    calculate_optimal_capacity,
    export_to_csv,
    filter_data_by_date,
    find_missing_hours,
    print_analysis_summary,
    run_full_analysis,
    run_rce_analysis,
    run_tariff_comparison,
)
from .data_loader import load_from_enea_csv
from .price_fetcher import get_hourly_rce_prices
from .tariffs import TariffManager

# --- i18n setup ---
APP_NAME = "eanalizer"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"

_ = gettext.gettext

try:
    # Attempt to set the locale from the user's environment
    locale.setlocale(locale.LC_ALL, "")
    # Get the language code
    lang_code = locale.getlocale()[0]
    if lang_code:
        # e.g., 'en_US' -> 'en'
        language = lang_code.split("_")[0]
        # Find the .mo file
        translation = gettext.translation(APP_NAME, localedir=LOCALE_DIR, languages=[language])
        _ = translation.gettext
except (FileNotFoundError, locale.Error, IndexError):
    # Fallback if the .mo file is not found, locale is not supported, or lang_code is empty
    pass


# --- end i18n setup ---


def main():
    """Glowna funkcja uruchomieniowa dla CLI."""
    parser = argparse.ArgumentParser(description=_("Energy data analyzer."))

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-p",
        "--pliki",
        nargs="+",
        help=_("List of single data files to analyze."),
    )
    group.add_argument(
        "-k",
        "--katalog",
        default=None,
        help=_("Path to the directory with .csv files."),
    )

    parser.add_argument(
        "-t",
        "--taryfa",
        default="G11",
        help=_("Specifies the energy tariff for a single analysis (default: G11)."),
    )
    parser.add_argument("--data-start", help=_("Start date of the analysis (format YYYY-MM-DD)."))
    parser.add_argument("--data-koniec", help=_("End date of the analysis (format YYYY-MM-DD)."))
    parser.add_argument(
        "--magazyn-fizyczny",
        type=float,
        help=_("Capacity of the physical storage in kWh (e.g., 10.0)."),
    )
    parser.add_argument(
        "--sprawnosc-magazynu",
        type=float,
        default=0.9,
        help=_("Efficiency of the physical storage (round-trip, default: 0.90, i.e., 90%%)."),
    )
    parser.add_argument(
        "--eksport-symulacji",
        help=_("Path to the CSV file with hourly simulation results."),
    )
    parser.add_argument(
        "--eksport-dzienny",
        help=_("Path to the CSV file with aggregated daily data."),
    )
    parser.add_argument(
        "--oblicz-optymalny-magazyn",
        action="store_true",
        help=_("Calculates the optimal storage capacity."),
    )
    parser.add_argument(
        "--z-cenami-rce",
        action="store_true",
        help=_("Use real RCE prices instead of fixed tariff prices."),
    )
    parser.add_argument(
        "--z-netmetering",
        action="store_true",
        help=_("Enables calculations for the virtual net-metering storage."),
    )
    parser.add_argument(
        "--wspolczynnik-netmetering",
        type=float,
        default=0.8,
        choices=[0.7, 0.8],
        help=_("Coefficient for energy returned in net-metering (default: 0.8)."),
    )
    parser.add_argument(
        "--porownaj-taryfy",
        action="store_true",
        help=_("Runs a comparison of all available tariffs for the given period."),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=_("Enables verbose mode for tariff comparison."),
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
        print(_("No .csv files found for processing in: {}").format(katalog_info))
        return

    print(_("Found {} files to process:").format(len(files_to_process)))
    all_energy_data = []
    for file_path in files_to_process:
        all_energy_data.extend(load_from_enea_csv(file_path))
    all_energy_data.sort(key=lambda x: x.timestamp)
    print(_("\nTotal loaded {} records.").format(len(all_energy_data)))

    # Data filtering
    filtered_data = filter_data_by_date(all_energy_data, args.data_start, args.data_koniec)
    if not filtered_data:
        print(_("No data in the given date range for further analysis."))
        return
    if args.data_start or args.data_koniec:
        find_missing_hours(filtered_data, args.data_start, args.data_koniec)

    min_year = min(d.timestamp.year for d in filtered_data)
    max_year = max(d.timestamp.year for d in filtered_data)
    tariff_manager = TariffManager(str(app_cfg.tariffs_file), years=range(min_year, max_year + 1))

    # Determine analysis parameters
    net_metering_ratio = args.wspolczynnik_netmetering if args.z_netmetering else None
    capacity = args.magazyn_fizyczny if args.magazyn_fizyczny and args.magazyn_fizyczny > 0 else 0.0
    storage_efficiency = args.sprawnosc_magazynu

    # --- Main analysis logic ---
    if args.z_cenami_rce:
        start_date = filtered_data[0].timestamp
        end_date = filtered_data[-1].timestamp
        hourly_prices = get_hourly_rce_prices(start_date, end_date, cache_dir=app_cfg.cache_dir)
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
            calculate_optimal_capacity(filtered_data, daily_data_df, tariff_manager, args.taryfa)

        if args.eksport_dzienny:
            export_to_csv(daily_data_df, args.eksport_dzienny)

        if args.eksport_symulacji and simulation_df is not None:
            export_to_csv(simulation_df, args.eksport_symulacji)


if __name__ == "__main__":
    main()
