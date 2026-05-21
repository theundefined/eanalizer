# eanalizer/downloader_cli.py

import argparse
from .config import load_config
from .downloader import EneaDownloader


def main():
    """
    CLI entry point for the Enea Downloader.
    Loads configuration (prompting if necessary) and runs the downloader.
    """
    parser = argparse.ArgumentParser(
        description="Pobiera dane o zużyciu energii z eBOK Enea i raportuje zakres danych na dysku."
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Wymusza ponowne pobranie danych, nawet jeśli są aktualne.",
    )
    parser.add_argument(
        "-r",
        "--report",
        action="store_true",
        help="Tylko wyświetla zakres danych z plików na dysku (bez pobierania).",
    )

    args = parser.parse_args()

    try:
        # Load configuration. Credentials are required only if we are not in report-only mode.
        app_cfg = load_config(require_credentials=not args.report)

        # Instantiate the downloader with the loaded config and run it.
        downloader = EneaDownloader(app_cfg, force=args.force, report_only=args.report)
        downloader.download_data()

    except (ValueError, ConnectionError, SystemExit) as e:
        print(f"\nBłąd: {e}")
        # SystemExit is raised by config loader on failure to get credentials
    except Exception as e:
        print(f"\nWystąpił nieoczekiwany błąd: {e}")


if __name__ == "__main__":
    main()
