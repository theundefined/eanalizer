# eanalizer/downloader_cli.py

from .config import load_config
from .downloader import EneaDownloader


def main():
    """
    CLI entry point for the Enea Downloader.
    Loads configuration (prompting if necessary) and runs the downloader.
    """
    try:
        # Load configuration, ensuring credentials are required and prompted for if missing.
        app_cfg = load_config(require_credentials=True)

        # Instantiate the downloader with the loaded config and run it.
        downloader = EneaDownloader(app_cfg)
        downloader.download_data()

    except (ValueError, ConnectionError, SystemExit) as e:
        print(f"\nBłąd: {e}")
        # SystemExit is raised by config loader on failure to get credentials
    except Exception as e:
        print(f"\nWystąpił nieoczekiwany błąd: {e}")


if __name__ == "__main__":
    main()
