import argparse
import glob
import gettext
import locale
import os
from pathlib import Path

import pandas as pd

from .config import has_legacy_default_tariffs, load_config
from .core import (
    PREDEFINED_PERIODS,
    aggregate_daily_data,
    aggregate_monthly_data,
    analyze_daily_trends,
    calculate_optimal_capacity,
    export_to_csv,
    filter_data_by_date,
    find_missing_hours,
    print_analysis_summary,
    print_monthly_summary,
    resolve_predefined_period,
    run_full_analysis,
    run_rce_analysis,
    run_tariff_comparison,
)
from .data_loader import load_from_enea_csv
from .netbilling import WYCENY, print_net_billing_summary, settle_net_billing
from .price_fetcher import get_hourly_rce_prices, get_monthly_rcem_prices
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
        translation = gettext.translation(
            APP_NAME, localedir=LOCALE_DIR, languages=[language]
        )
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
    parser.add_argument(
        "--data-start", help=_("Start date of the analysis (format YYYY-MM-DD).")
    )
    parser.add_argument(
        "--data-koniec", help=_("End date of the analysis (format YYYY-MM-DD).")
    )
    parser.add_argument(
        "--okres",
        choices=PREDEFINED_PERIODS,
        help=_(
            "Predefined analysis period, counted backwards from the last "
            "available date in the data (not today's date). Mutually "
            "exclusive with --data-start/--data-koniec/--ostatnie-dni."
        ),
    )
    parser.add_argument(
        "--ostatnie-dni",
        type=int,
        help=_(
            "Analyzes the last N days of data, counted backwards from the "
            "last available date in the data (not today's date). Mutually "
            "exclusive with --data-start/--data-koniec/--okres."
        ),
    )
    parser.add_argument(
        "--magazyn-fizyczny",
        type=float,
        help=_("Capacity of the physical storage in kWh (e.g., 10.0)."),
    )
    parser.add_argument(
        "--sprawnosc-magazynu",
        type=float,
        default=0.9,
        help=_(
            "Efficiency of the physical storage (round-trip, default: 0.90, i.e., 90%%)."
        ),
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
        "--miesieczne",
        action="store_true",
        help=_("Displays a table with aggregated monthly data."),
    )
    parser.add_argument(
        "--eksport-miesieczny",
        help=_("Path to the CSV file with aggregated monthly data."),
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
        "--z-netbilling",
        action="store_true",
        help=_(
            "Settles costs in the net-billing system (prosumer deposit valued "
            "at RCEm/RCE market prices)."
        ),
    )
    parser.add_argument(
        "--wycena-netbilling",
        choices=WYCENY,
        default="rcem",
        help=_(
            "Valuation of exported energy in net-billing: rcem (monthly price, "
            "default) or rce (hourly prices, from 07.2024)."
        ),
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

    if args.okres and args.ostatnie_dni:
        parser.error(_("Nie można jednocześnie użyć --okres i --ostatnie-dni."))
    if (args.okres or args.ostatnie_dni is not None) and (
        args.data_start or args.data_koniec
    ):
        parser.error(
            _(
                "Flagi --okres/--ostatnie-dni nie mogą być używane razem z "
                "--data-start/--data-koniec."
            )
        )
    if args.ostatnie_dni is not None and args.ostatnie_dni <= 0:
        parser.error(_("--ostatnie-dni musi być liczbą całkowitą dodatnią."))
    if args.z_netbilling and args.z_netmetering:
        parser.error(_("Nie można jednocześnie użyć --z-netbilling i --z-netmetering."))
    if args.z_netbilling and args.z_cenami_rce:
        parser.error(_("Nie można jednocześnie użyć --z-netbilling i --z-cenami-rce."))

    app_cfg = load_config()
    if has_legacy_default_tariffs(app_cfg.tariffs_file):
        print(
            _(
                "Uwaga: plik taryf {} zawiera nieaktualne strefy czasowe (G12 bez "
                "strefy nocnej 13-15, G12w ze szczytem do 22 zamiast do 21). Usuń "
                "go, aby przy następnym uruchomieniu utworzyć poprawny plik domyślny."
            ).format(app_cfg.tariffs_file)
        )

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

    if args.okres or args.ostatnie_dni is not None:
        try:
            args.data_start, args.data_koniec = resolve_predefined_period(
                all_energy_data, okres=args.okres, ostatnie_dni=args.ostatnie_dni
            )
        except ValueError as e:
            print(str(e))
            return
        print(
            _(
                "Wybrany okres: {} — {} (na podstawie ostatniej dostępnej daty w danych)."
            ).format(args.data_start, args.data_koniec)
        )

    # Data filtering
    filtered_data = filter_data_by_date(
        all_energy_data, args.data_start, args.data_koniec
    )
    if not filtered_data:
        print(_("No data in the given date range for further analysis."))
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

    net_billing = None
    if args.z_netbilling:
        start_ts = filtered_data[0].timestamp
        end_ts = filtered_data[-1].timestamp
        months = [
            str(p) for p in pd.period_range(start=start_ts, end=end_ts, freq="M")
        ]
        rce_prices = {}
        if args.wycena_netbilling == "rce":
            rce_prices = get_hourly_rce_prices(
                start_ts, end_ts, cache_dir=app_cfg.cache_dir
            )
        net_billing = {
            "rce_prices": rce_prices,
            "rcem_prices": get_monthly_rcem_prices(months, cache_dir=app_cfg.cache_dir),
            "wycena": args.wycena_netbilling,
        }

    # --- Main analysis logic ---
    if args.z_cenami_rce:
        if capacity > 0 or net_metering_ratio is not None:
            print(
                _(
                    "Uwaga: tryb --z-cenami-rce nie obsługuje symulacji magazynu ani "
                    "net-meteringu; flagi --magazyn-fizyczny/--z-netmetering/"
                    "--sprawnosc-magazynu zostaną zignorowane."
                )
            )
        if (
            args.oblicz_optymalny_magazyn
            or args.eksport_dzienny
            or args.eksport_symulacji
            or args.miesieczne
            or args.eksport_miesieczny
        ):
            print(
                _(
                    "Uwaga: tryb --z-cenami-rce nie obsługuje eksportu danych ani "
                    "obliczania optymalnego magazynu; te opcje zostaną zignorowane."
                )
            )
        start_date = filtered_data[0].timestamp
        end_date = filtered_data[-1].timestamp
        hourly_prices = get_hourly_rce_prices(
            start_date, end_date, cache_dir=app_cfg.cache_dir
        )
        run_rce_analysis(filtered_data, hourly_prices)
    elif args.porownaj_taryfy:
        if (
            args.oblicz_optymalny_magazyn
            or args.eksport_dzienny
            or args.eksport_symulacji
            or args.miesieczne
            or args.eksport_miesieczny
        ):
            print(
                _(
                    "Uwaga: tryb --porownaj-taryfy nie obsługuje eksportu danych ani "
                    "obliczania optymalnego magazynu; te opcje zostaną zignorowane."
                )
            )
        run_tariff_comparison(
            data=filtered_data,
            tariff_manager=tariff_manager,
            capacity=capacity,
            net_metering_ratio=net_metering_ratio,
            storage_efficiency=storage_efficiency,
            verbose=args.verbose,
            net_billing=net_billing,
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
        if net_billing is not None:
            nb_summary = settle_net_billing(
                simulation_df,
                tariff_manager,
                args.taryfa,
                rce_prices=net_billing["rce_prices"],
                rcem_prices=net_billing["rcem_prices"],
                wycena=net_billing["wycena"],
                fixed_fee=summary.get("oplaty_stale", 0.0),
            )
            print_net_billing_summary(nb_summary, args.taryfa, capacity)
        else:
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

        if args.miesieczne or args.eksport_miesieczny:
            monthly_data_df = aggregate_monthly_data(filtered_data)
            if args.miesieczne:
                print_monthly_summary(monthly_data_df)
            if args.eksport_miesieczny:
                export_to_csv(monthly_data_df, args.eksport_miesieczny)

        if args.eksport_symulacji and simulation_df is not None:
            export_to_csv(simulation_df, args.eksport_symulacji)


if __name__ == "__main__":
    main()
