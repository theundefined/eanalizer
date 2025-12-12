# eanalizer/config.py

import configparser
import getpass
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import platformdirs
import requests

APP_NAME = "eanalizer"
CONFIG_FILE_NAME = "config.ini"


@dataclass
class AppConfig:
    """Dataclass to hold all application configuration."""

    config_file_path: Path
    data_dir: Path
    tariffs_file: Path
    cache_dir: Path

    # Enea credentials can be optional
    email: Optional[str] = None
    password: Optional[str] = None
    customer_id: Optional[str] = None

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def save(self):
        """Saves the current configuration to the config file."""
        parser = configparser.ConfigParser()
        # Read existing file to not lose other sections
        if self.config_file_path.is_file():
            parser.read(self.config_file_path)

        if "paths" not in parser:
            parser["paths"] = {}
        parser["paths"]["data_dir"] = str(self.data_dir)

        if self.email and self.password and self.customer_id:
            if "enea_credentials" not in parser:
                parser["enea_credentials"] = {}
            parser["enea_credentials"]["email"] = self.email
            parser["enea_credentials"]["password"] = self.password
            parser["enea_credentials"]["customer_id"] = self.customer_id

        self.config_file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_file_path.open("w") as f:
            parser.write(f)


def _get_config_file_path() -> Path:
    """Determines the correct path for the config file."""
    # If running from source (local development), place config in project root.
    if Path.cwd().joinpath("pyproject.toml").is_file():
        return Path.cwd() / CONFIG_FILE_NAME
    # Otherwise, use the standard user config directory (for pipx installation).
    return (
        Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / CONFIG_FILE_NAME
    )


def _prompt_for_paths(config_file_path: Path) -> Path:
    """Prompts the user for the data directory path."""
    print(f"Plik konfiguracyjny nie zostal znaleziony w: {config_file_path}")
    print("Prosze podac sciezke do katalogu, w ktorym beda przechowywane dane.")

    # Suggest a default data directory
    if Path.cwd().joinpath("pyproject.toml").is_file():
        default_data_dir = Path.cwd() / "data"
    else:
        default_data_dir = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))

    print(f"Sugerowana lokalizacja (wcisnij Enter, aby uzyc): {default_data_dir}")

    while True:
        try:
            data_dir_str = input(f"Katalog na dane [{default_data_dir}]: ")
            if not data_dir_str:
                data_dir = default_data_dir
            else:
                data_dir = Path(data_dir_str).expanduser().resolve()

            data_dir.mkdir(parents=True, exist_ok=True)
            print(f"Katalog danych ustawiono na: {data_dir}")
            return data_dir
        except Exception as e:
            print(f"Nie mozna utworzyc katalogu: {e}. Prosze podac inna sciezke.")


def _prompt_for_enea_credentials() -> dict:
    """Interactively prompts the user for Enea credentials and verifies them."""
    print("\nProsze podac swoje dane logowania do https://ebok.enea.pl/logowanie")
    email = input("Email: ")
    password = getpass.getpass("Haslo: ")

    # Verification logic copied from the original downloader
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Referer": "https://ebok.enea.pl/logowanie",
    }
    with requests.Session() as session:
        try:
            login_page = session.get("https://ebok.enea.pl/logowanie", headers=headers)
            login_page.raise_for_status()
            token_match = re.search(r'name="token" value="(.*?)"', login_page.text)
            if not token_match:
                raise ConnectionError(
                    "Blad: Nie mozna znalezc tokena CSRF na stronie logowania."
                )
            token = token_match.group(1)

            login_data = {
                "email": email,
                "password": password,
                "token": token,
                "btnSubmit": "",
            }
            login_response = session.post(
                "https://ebok.enea.pl/logowanie", data=login_data, headers=headers
            )
            login_response.raise_for_status()
            if "Lista kontrahentów" not in login_response.text:
                raise ValueError(
                    "Logowanie nie powiodlo sie. Sprawdz swoje dane uwierzytelniajace."
                )

            customers = re.findall(
                r'<span>\s*(\d+)\s*</span>.*?href="/dashboard/select-current-client/([a-f0-9\-]+)"',
                login_response.text,
                re.DOTALL,
            )
            if not customers:
                raise ValueError(
                    "Blad: Nie znaleziono profili klientow dla tego konta."
                )

            print("Weryfikacja, ktore profile posiadaja dane godzinowe...")
            valid_customers = []
            for id, guid in customers:
                print(f"Sprawdzanie profilu {id}... ", end="")
                try:
                    # Select the client to set the context
                    headers["Referer"] = "https://ebok.enea.pl/dashboard/many-clients"
                    client_selection_url = (
                        f"https://ebok.enea.pl/dashboard/select-current-client/{guid}"
                    )
                    client_response = session.get(client_selection_url, headers=headers)
                    client_response.raise_for_status()

                    # Check the summary balancing chart page for the required data
                    headers["Referer"] = "https://ebok.enea.pl/dashboard"
                    summary_page = session.get(
                        "https://ebok.enea.pl/meter/summaryBalancingChart",
                        headers=headers,
                    )
                    summary_page.raise_for_status()

                    if 'data-point-of-delivery-id="' in summary_page.text:
                        valid_customers.append((id, guid))
                        print("OK")
                    else:
                        print("Brak danych godzinowych.")

                except requests.exceptions.RequestException as e:
                    print(f"Nie udalo sie zweryfikowac profilu {id}: {e}")

            if not valid_customers:
                raise ValueError(
                    "Blad: Nie znaleziono profili klientow z dostepnymi danymi godzinnymi."
                )

            customer_id = None
            if len(valid_customers) == 1:
                customer_id = valid_customers[0][0]
                print(
                    f"Znaleziono jeden prawidlowy profil klienta: {customer_id}. Wybieram automatycznie."
                )
            else:
                print(
                    "Znaleziono wiele prawidlowych profili klientow. Prosze wybrac jeden:"
                )
                for i, (id, guid) in enumerate(valid_customers):
                    print(f"[{i + 1}] {id}")
                while True:
                    try:
                        choice = int(input("Wybierz opcje: "))
                        if 1 <= choice <= len(valid_customers):
                            customer_id = valid_customers[choice - 1][0]
                            break
                        else:
                            print("Nieprawidlowy wybor.")
                    except ValueError:
                        print("Nieprawidlowe dane.")

            return {"email": email, "password": password, "customer_id": customer_id}

        except (requests.exceptions.RequestException, ConnectionError, ValueError) as e:
            print(f"Blad podczas weryfikacji danych: {e}")
            return {}


def load_config(
    require_credentials=False, prompt_for_missing=True
) -> AppConfig:
    """
    Loads the application configuration or prompts the user to create one.
    """
    config_file = _get_config_file_path()
    parser = configparser.ConfigParser()

    data_dir = None
    creds = {}

    if not config_file.is_file():
        if not prompt_for_missing:
            raise FileNotFoundError("Config file not found and prompting is disabled.")
        data_dir = _prompt_for_paths(config_file)
    else:
        parser.read(str(config_file)) # Ensure path is a string for older python versions
        data_dir_str = parser.get("paths", "data_dir", fallback=None)
        if data_dir_str:
            data_dir = Path(data_dir_str)
        elif prompt_for_missing:
            data_dir = _prompt_for_paths(config_file)
        else:
            raise ValueError("data_dir not found in config and prompting is disabled.")

        creds = (
            dict(parser.items("enea_credentials"))
            if parser.has_section("enea_credentials")
            else {}
        )

    if require_credentials and not all(
        k in creds for k in ["email", "password", "customer_id"]
    ):
        if not prompt_for_missing:
            raise ValueError("Credentials required but not found, and prompting is disabled.")
        print("Brakujace dane logowania Enea w pliku konfiguracyjnym.")
        new_creds = _prompt_for_enea_credentials()
        if new_creds:
            creds = new_creds
        else:
            # Failed to get credentials, exit or handle error
            raise SystemExit(
                "Nie udalo sie pobrac i zweryfikowac danych logowania. Koniec pracy."
            )

    # Create default tariff file if it doesn't exist in the data directory
    tariffs_file = data_dir / "tariffs.csv"
    if not tariffs_file.is_file():
        print(f"Tworzenie domyslnego pliku taryf w: {tariffs_file}")
        tariffs_file.parent.mkdir(parents=True, exist_ok=True)
        tariffs_file.write_text(
            "tariff,zone_name,day_type,start_hour,end_hour,price_per_kwh\n"
            "G11,stala,all,0,24,0.97\n"
            "G12,wysoka,all,6,13,1.06\n"
            "G12,wysoka,all,15,22,1.06\n"
            "G12,niska,all,0,6,0.75\n"
            "G12,niska,all,13,15,0.75\n"
            "G12,niska,all,22,24,0.75\n"
            "G12w,wysoka,weekday,6,21,1.08\n"
            "G12w,niska,weekday,0,6,0.76\n"
            "G12w,niska,weekday,21,24,0.76\n"
            "G12w,niska,weekend,0,24,0.76\n"
        )

    app_cfg = AppConfig(
        config_file_path=config_file,
        data_dir=data_dir,
        tariffs_file=tariffs_file,
        cache_dir=data_dir / "cache" / "rce_prices",
        email=creds.get("email"),
        password=creds.get("password"),
        customer_id=creds.get("customer_id"),
    )

    app_cfg.save()  # Save any changes (new paths or credentials)
    return app_cfg


# A global config instance can still be useful for simple access,
# but now it must be loaded explicitly by each entry point.
# For example, in cli.py: `app_config = load_config()`
# This avoids running I/O on module import.
# The old `app_config = load_or_create_config()` is removed.
