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
DEFAULT_TARIFFS_FILE = "tariffs.csv"


@dataclass
class AppConfig:
    """Dataclass to hold all application configuration."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path

    # Enea credentials can be optional
    email: Optional[str] = None
    password: Optional[str] = None
    customer_id: Optional[str] = None

    @property
    def tariffs_file(self) -> Path:
        """Path to the tariffs CSV file."""
        return self.config_dir / DEFAULT_TARIFFS_FILE

    @property
    def config_file(self) -> Path:
        """Path to the main INI config file."""
        return self.config_dir / CONFIG_FILE_NAME

    def __post_init__(self):
        """Create directories if they don't exist."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def save(self):
        """Saves the current configuration to the config file."""
        parser = configparser.ConfigParser()
        # Read existing file to preserve other sections if they exist
        if self.config_file.is_file():
            parser.read(self.config_file, encoding="utf-8")

        if "paths" not in parser:
            parser["paths"] = {}
        parser["paths"]["config_dir"] = str(self.config_dir)
        parser["paths"]["data_dir"] = str(self.data_dir)
        parser["paths"]["cache_dir"] = str(self.cache_dir)

        if self.email and self.password and self.customer_id:
            if "enea_credentials" not in parser:
                parser["enea_credentials"] = {}
            parser["enea_credentials"]["email"] = self.email
            parser["enea_credentials"]["password"] = self.password
            parser["enea_credentials"]["customer_id"] = self.customer_id

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with self.config_file.open("w", encoding="utf-8") as f:
            parser.write(f)


def _get_default_dir(dir_type: str) -> Path:
    """
    Determines the default path for app directories based on environment.
    """
    is_dev_env = Path.cwd().joinpath("pyproject.toml").is_file()

    if dir_type == "config":
        return Path.cwd() / "config" if is_dev_env else Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))
    if dir_type == "data":
        return Path.cwd() / "data" if is_dev_env else Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
    if dir_type == "cache":
        return Path.cwd() / "cache" if is_dev_env else Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))

    raise ValueError(f"Unknown directory type: {dir_type}")


def _prompt_for_single_path(dir_type: str, description: str) -> Path:
    """Prompts the user for a single directory path with a default."""
    default_dir = _get_default_dir(dir_type)
    while True:
        try:
            path_str = input(f"{description} [{default_dir}]: ")
            path = Path(path_str) if path_str else default_dir
            path = path.expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            print(f"Ustawiono katalog '{dir_type}' na: {path}")
            return path
        except Exception as e:
            print(f"Nie mozna utworzyc katalogu: {e}. Prosze podac inna sciezke.")


def _prompt_for_paths(config_file_path: Path) -> dict:
    """Prompts the user for all required directory paths."""
    print(f"Plik konfiguracyjny nie zostal znaleziony lub jest niekompletny: {config_file_path}")
    print("Prosze podac sciezki do katalogow aplikacji.")

    config_dir = _prompt_for_single_path("config", "Katalog na konfiguracje (np. taryfy)")
    data_dir = _prompt_for_single_path("data", "Katalog na dane od Enea")
    cache_dir = _prompt_for_single_path("cache", "Katalog na pamiec podreczna (np. ceny RCE)")

    return {"config_dir": config_dir, "data_dir": data_dir, "cache_dir": cache_dir}


def _prompt_for_enea_credentials() -> dict:
    """Interactively prompts the user for Enea credentials and verifies them."""
    print("\nProsze podac swoje dane logowania do https://ebok.enea.pl/logowanie")
    email = input("Email: ")
    password = getpass.getpass("Haslo: ")

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
                raise ConnectionError("Blad: Nie mozna znalezc tokena CSRF na stronie logowania.")
            token = token_match.group(1)

            login_data = {
                "email": email,
                "password": password,
                "token": token,
                "btnSubmit": "",
            }
            login_response = session.post("https://ebok.enea.pl/logowanie", data=login_data, headers=headers)
            login_response.raise_for_status()
            if "Lista kontrahentów" not in login_response.text:
                raise ValueError("Logowanie nie powiodlo sie. Sprawdz swoje dane uwierzytelniajace.")

            customers = re.findall(
                r'<span>\s*(\d+)\s*</span>.*?href="/dashboard/select-current-client/([a-f0-9\-]+)"',
                login_response.text,
                re.DOTALL,
            )
            if not customers:
                raise ValueError("Blad: Nie znaleziono profili klientow dla tego konta.")

            print("Weryfikacja, ktore profile posiadaja dane godzinowe...")
            valid_customers = []
            for id, guid in customers:
                print(f"Sprawdzanie profilu {id}... ", end="")
                try:
                    headers["Referer"] = "https://ebok.enea.pl/dashboard/many-clients"
                    client_response = session.get(
                        f"https://ebok.enea.pl/dashboard/select-current-client/{guid}",
                        headers=headers,
                    )
                    client_response.raise_for_status()
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
                raise ValueError("Blad: Nie znaleziono profili klientow z dostepnymi danymi godzinnymi.")

            customer_id = None
            if len(valid_customers) == 1:
                customer_id = valid_customers[0][0]
                print(f"Znaleziono jeden prawidlowy profil klienta: {customer_id}. Wybieram automatycznie.")
            else:
                print("Znaleziono wiele prawidlowych profili klientow. Prosze wybrac jeden:")
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
        except (requests.exceptions.RequestException, ValueError, ConnectionError) as e:
            print(f"Blad podczas weryfikacji: {e}")
            raise SystemExit(1)


def load_config(require_credentials: bool = False, prompt_for_missing: bool = True) -> AppConfig:
    """Loads application config, prompting if missing/incomplete."""
    initial_config_dir = _get_default_dir("config")
    config_file = initial_config_dir / CONFIG_FILE_NAME
    parser = configparser.ConfigParser()

    paths = {}
    creds = {}

    config_is_valid = False
    if config_file.is_file():
        parser.read(str(config_file), encoding="utf-8")
        if parser.has_section("paths"):
            required_paths = ["config_dir", "data_dir", "cache_dir"]
            if all(parser.has_option("paths", p) for p in required_paths):
                paths = {p: Path(parser.get("paths", p)) for p in required_paths}
                config_is_valid = True
        if parser.has_section("enea_credentials"):
            creds = dict(parser.items("enea_credentials"))

    if not config_is_valid:
        if not prompt_for_missing:
            raise FileNotFoundError(f"Plik konfiguracyjny nie istnieje lub jest niekompletny: {config_file}")
        paths = _prompt_for_paths(config_file)

    if require_credentials and not all(k in creds for k in ["email", "password", "customer_id"]):
        if not prompt_for_missing:
            raise ValueError("Brakujące dane uwierzytelniające Enea.")
        print("Brak zapisanych danych logowania Enea lub są one niekompletne.")
        creds = _prompt_for_enea_credentials()

    app_cfg = AppConfig(
        config_dir=paths["config_dir"],
        data_dir=paths["data_dir"],
        cache_dir=paths["cache_dir"],
        email=creds.get("email"),
        password=creds.get("password"),
        customer_id=creds.get("customer_id"),
    )

    if not app_cfg.tariffs_file.is_file():
        print(f"Tworzenie domyslnego pliku taryf w: {app_cfg.tariffs_file}")
        # Ceny brutto (z VAT 23%) na podstawie taryfy ENEA Operator 2026.
        default_tariffs_content = (
            "tariff,zone_name,day_type,start_hour,end_hour,energy_price,dist_price,dist_fee\n"
            "G11,stala,all,0,24,0.61254,0.35547,43.4682\n"
            "G12,nocna,all,22,6,0.414387,0.165681,46.1004\n"
            "G12,dzienna,all,6,22,0.710817,0.395199,46.1004\n"
            "G12w,pozaszczytowa,weekday,0,6,0.426195,0.153381,55.0302\n"
            "G12w,szczytowa,weekday,6,22,0.801714,0.385728,55.0302\n"
            "G12w,pozaszczytowa,weekday,22,24,0.426195,0.153381,55.0302\n"
            "G12w,pozaszczytowa,weekend,0,24,0.426195,0.153381,55.0302\n"
        )
        app_cfg.tariffs_file.write_text(default_tariffs_content.replace("\\n", "\n"), encoding="utf-8")

    app_cfg.save()
    return app_cfg
