# eanalizer/downloader.py

import json
import re
import requests
from datetime import datetime, timedelta

from .config import AppConfig


class EneaDownloader:
    def __init__(self, config: AppConfig):
        """Initializes the downloader with a complete application configuration."""
        if not all([config.email, config.password, config.customer_id]):
            raise ValueError("Enea credentials are not fully configured.")
        self.config = config

    def download_data(self):
        """
        Main method to perform the download of Enea energy data.
        """
        # Ensure data directory exists
        self.config.data_dir.mkdir(exist_ok=True)

        current_year = datetime.now().year
        filename = self.config.data_dir / f"{self.config.customer_id}_dane_dobowo_godzinowe_{current_year}.csv"

        # Check if the file for the current year needs to be downloaded
        if filename.is_file():
            file_mod_time = datetime.fromtimestamp(filename.stat().st_mtime)
            if datetime.now() - file_mod_time < timedelta(hours=1):
                print(f"Plik {filename} jest nowszy niż 1 godzina. Kończenie.")
                return
            else:
                with open(filename, "r", encoding="utf-8") as f:
                    try:
                        content = f.read()
                        if "---" not in content:
                            print(f"Plik {filename} już istnieje i jest prawidłowy. Kończenie.")
                            return
                    except UnicodeDecodeError:
                        pass  # File will be re-downloaded

        # URLs
        login_url = "https://ebok.enea.pl/logowanie"
        summary_balancing_chart_url = "https://ebok.enea.pl/meter/summaryBalancingChart"

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "Referer": login_url,
        }

        with requests.Session() as session:
            # Get CSRF token
            try:
                print("Pobieranie strony logowania...")
                login_page = session.get(login_url, headers=headers)
                login_page.raise_for_status()
                token_match = re.search(r'name="token" value="(.*?)"', login_page.text)
                if not token_match:
                    raise ConnectionError("Nie można znaleźć tokena CSRF.")
                token = token_match.group(1)
            except requests.exceptions.RequestException as e:
                raise ConnectionError(f"Błąd podczas pobierania strony logowania: {e}") from e

            # Login
            login_data = {
                "email": self.config.email,
                "password": self.config.password,
                "token": token,
                "btnSubmit": "",
            }
            try:
                print("Logowanie...")
                login_response = session.post(login_url, data=login_data, headers=headers)
                login_response.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise ConnectionError(f"Błąd podczas logowania: {e}") from e

            # Get client GUID
            try:
                print("Wyszukiwanie identyfikatora klienta...")
                client_guid_match = re.search(
                    rf'<span>\s*{self.config.customer_id}\s*</span>.*?href="/dashboard/select-current-client/([a-f0-9\-]+)"',
                    login_response.text,
                    re.DOTALL,
                )
                if not client_guid_match:
                    raise ValueError(f"Nie można znaleźć identyfikatora dla klienta {self.config.customer_id}")
                client_guid = client_guid_match.group(1)
            except Exception as e:
                raise ValueError(f"Błąd podczas wyszukiwania identyfikatora klienta: {e}") from e

            # Select client
            try:
                print("Wybieranie klienta...")
                headers["Referer"] = "https://ebok.enea.pl/dashboard/many-clients"
                client_selection_url = f"https://ebok.enea.pl/dashboard/select-current-client/{client_guid}"
                client_response = session.get(client_selection_url, headers=headers)
                client_response.raise_for_status()
            except requests.exceptions.RequestException as e:
                raise ConnectionError(f"Błąd podczas wybierania klienta: {e}") from e

            # Get pointOfDeliveryId and available years
            try:
                print("Pobieranie danych o punkcie poboru i dostępnych latach...")
                headers["Referer"] = "https://ebok.enea.pl/dashboard"
                summary_page = session.get(summary_balancing_chart_url, headers=headers)
                summary_page.raise_for_status()

                pod_id_match = re.search(r'data-point-of-delivery-id="(.*?)"', summary_page.text)
                if not pod_id_match:
                    raise ValueError("Nie można znaleźć pointOfDeliveryId.")
                point_of_delivery_id = pod_id_match.group(1)

                min_year_match = re.search(r'data-min-date-value="(\d{4})"', summary_page.text)
                max_year_match = re.search(r'data-max-date-value="(\d{4})"', summary_page.text)
                if not min_year_match or not max_year_match:
                    raise ValueError("Nie można znaleźć zakresu lat.")

                min_year = int(min_year_match.group(1))
                max_year = int(max_year_match.group(1))
                print(f"Znaleziono dostępne lata: {min_year}-{max_year}")
            except (requests.exceptions.RequestException, ValueError) as e:
                raise ConnectionError(f"Błąd podczas pobierania metadanych: {e}") from e

            # Download CSV for each year
            for year in range(min_year, max_year + 1):
                self._download_year_csv(session, year, point_of_delivery_id, summary_balancing_chart_url)

    def _download_year_csv(self, session, year, point_of_delivery_id, referer_url):
        filename = self.config.data_dir / f"{self.config.customer_id}_dane_dobowo_godzinowe_{year}.csv"

        # Skip if file is recent (only for current year) or valid
        if filename.is_file():
            if year == datetime.now().year:
                if datetime.now() - datetime.fromtimestamp(filename.stat().st_mtime) < timedelta(hours=1):
                    print(f"Plik {filename} jest nowszy niż 1 godzina. Pomijanie.")
                    return
            with open(filename, "r", encoding="utf-8") as f:
                if "---" not in f.read():
                    print(f"Plik {filename} już istnieje i jest prawidłowy. Pomijanie.")
                    return

        csv_data = {
            "duration": "year",
            "date": year,
            "pointOfDeliveryId": point_of_delivery_id,
        }
        try:
            print(f"Pobieranie CSV za rok {year}...")
            headers = session.headers.copy()
            headers["Referer"] = referer_url
            csv_response = session.post(
                "https://ebok.enea.pl/meter/summaryBalancingChart/csv",
                data=csv_data,
                headers=headers,
            )
            csv_response.raise_for_status()

            json_data = csv_response.json()
            csv_content = json_data["data"]

            with open(filename, "w") as f:
                f.write(csv_content)
            print(f"Pomyślnie zapisano {filename}")

        except (
            requests.exceptions.RequestException,
            json.JSONDecodeError,
            KeyError,
        ) as e:
            print(f"Błąd podczas pobierania lub zapisywania danych za rok {year}: {e}")
