#!/usr/bin/env python3

import configparser
import json
import re
import requests
import os
import getpass
from datetime import datetime, timedelta

# Create data directory if it doesn't exist
os.makedirs("data", exist_ok=True)

# --- Configuration ---
def create_config():
    print("Plik konfiguracyjny nie został znaleziony. Proszę podać swoje dane logowania do https://ebok.enea.pl/logowanie")
    print("Twoje dane logowania zostaną zapisane w pliku config.ini")
    email = input("Email: ")
    password = getpass.getpass("Hasło: ")

    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        'Referer': 'https://ebok.enea.pl/logowanie'
    }
    with requests.Session() as session:
        try:
            login_page = session.get('https://ebok.enea.pl/logowanie', headers=headers)
            login_page.raise_for_status()
            token_match = re.search(r'name="token" value="(.*?)"', login_page.text)
            if not token_match:
                print("Błąd: Nie można znaleźć tokena CSRF na stronie logowania.")
                exit()
            token = token_match.group(1)
        except requests.exceptions.RequestException as e:
            print(f"Błąd podczas pobierania strony logowania: {e}")
            exit()

        login_data = {
            'email': email,
            'password': password,
            'token': token,
            'btnSubmit': ''
        }
        try:
            login_response = session.post('https://ebok.enea.pl/logowanie', data=login_data, headers=headers)
            login_response.raise_for_status()
            if "Lista kontrahentów" not in login_response.text:
                print("Logowanie nie powiodło się. Sprawdź swoje dane uwierzytelniające.")
                exit()
        except requests.exceptions.RequestException as e:
            print(f"Błąd podczas logowania: {e}")
            exit()

        # Find all available customer profiles
        customers = re.findall(r'<span>\s*(\d+)\s*</span>.*?href="/dashboard/select-current-client/([a-f0-9\-]+)"', login_response.text, re.DOTALL)

        if not customers:
            print("Błąd: Nie znaleziono profili klientów dla tego konta.")
            exit()

        print("Weryfikacja, które profile posiadają dane godzinowe...")
        valid_customers = []
        for id, guid in customers:
            print(f"Sprawdzanie profilu {id}... ", end="")
            try:
                # Select the client to set the context
                headers['Referer'] = 'https://ebok.enea.pl/dashboard/many-clients'
                client_selection_url = f'https://ebok.enea.pl/dashboard/select-current-client/{guid}'
                client_response = session.get(client_selection_url, headers=headers)
                client_response.raise_for_status()

                # Check the summary balancing chart page for the required data
                headers['Referer'] = 'https://ebok.enea.pl/dashboard'
                summary_page = session.get('https://ebok.enea.pl/meter/summaryBalancingChart', headers=headers)
                summary_page.raise_for_status()

                if 'data-point-of-delivery-id="' in summary_page.text:
                    valid_customers.append((id, guid))
                    print("OK")
                else:
                    print("Brak danych godzinowych.")

            except requests.exceptions.RequestException as e:
                print(f"Nie udało się zweryfikować profilu {id}: {e}")

        if not valid_customers:
            print("Błąd: Nie znaleziono profili klientów z dostępnymi danymi godzinnymi dla tego konta.")
            exit()

        customer_id = None
        if len(valid_customers) == 1:
            customer_id = valid_customers[0][0]
            print(f"Znaleziono jeden prawidłowy profil klienta: {customer_id}. Wybieram automatycznie.")
        else:
            print("Znaleziono wiele prawidłowych profili klientów. Proszę wybrać jeden:")
            for i, (id, guid) in enumerate(valid_customers):
                print(f"[{i + 1}] {id}")

            while True:
                try:
                    choice = int(input("Wybierz opcję: "))
                    if 1 <= choice <= len(valid_customers):
                        customer_id = valid_customers[choice - 1][0]
                        break
                    else:
                        print("Nieprawidłowy wybór. Proszę spróbować ponownie.")
                except ValueError:
                    print("Nieprawidłowe dane. Proszę podać numer.")

    # Create config file
    config = configparser.ConfigParser()
    config['credentials'] = {
        'email': email,
        'password': password,
        'customer_id': customer_id
    }
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    print("Plik konfiguracyjny został pomyślnie utworzony.")

if not os.path.exists('config.ini'):
    create_config()

# Read credentials from config.ini
config = configparser.ConfigParser()
config.read('config.ini')
email = config['credentials']['email']
password = config['credentials']['password']
customer_id = config['credentials']['customer_id']

# Check if the file for the current year needs to be downloaded
current_year = datetime.now().year
filename = f"data/{customer_id}_dane_dobowo_godzinowe_{current_year}.csv"
if os.path.exists(filename):
    file_mod_time = datetime.fromtimestamp(os.path.getmtime(filename))
    if datetime.now() - file_mod_time < timedelta(hours=1):
        print(f"Plik {filename} jest nowszy niż 1 godzina. Kończenie.")
        exit()
    else:
        with open(filename, 'r') as f:
            try:
                content = f.read()
                if '---' not in content:
                    print(f"Plik {filename} już istnieje i jest prawidłowy. Kończenie.")
                    exit()
            except UnicodeDecodeError:
                pass # File will be re-downloaded

# URLs
login_url = 'https://ebok.enea.pl/logowanie'
summary_balancing_chart_url = 'https://ebok.enea.pl/meter/summaryBalancingChart'
csv_download_url = 'https://ebok.enea.pl/meter/summaryBalancingChart/csv'

# Headers
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    'Referer': 'https://ebok.enea.pl/logowanie'
}

# Create a session to persist cookies
with requests.Session() as session:
    # Get the login page to extract the CSRF token
    try:
        print("Pobieranie strony logowania...")
        login_page = session.get(login_url, headers=headers)
        login_page.raise_for_status()
        token_match = re.search(r'name="token" value="(.*?)"', login_page.text)
        if not token_match:
            print("Błąd: Nie można znaleźć tokena CSRF na stronie logowania.")
            exit()
        token = token_match.group(1)
        print("Pomyślnie pobrano stronę logowania i token.")
    except requests.exceptions.RequestException as e:
        print(f"Błąd podczas pobierania strony logowania: {e}")
        exit()

    # Login
    login_data = {
        'email': email,
        'password': password,
        'token': token,
        'btnSubmit': ''
    }
    try:
        print("Logowanie...")
        login_response = session.post(login_url, data=login_data, headers=headers)
        login_response.raise_for_status()
        print("Pomyślnie zalogowano.")
    except requests.exceptions.RequestException as e:
        print(f"Błąd podczas logowania: {e}")
        print(login_response.text)
        exit()

    # Find the client selection guid
    try:
        print("Wyszukiwanie identyfikatora wyboru klienta...")
        client_guid_match = re.search(rf'<span>\s*{customer_id}\s*</span>.*?href="/dashboard/select-current-client/([a-f0-9\-]+)"', login_response.text, re.DOTALL)
        if not client_guid_match:
            print(f"Błąd: Nie można znaleźć identyfikatora klienta dla numeru klienta {customer_id}")
            exit()
        client_guid = client_guid_match.group(1)
        print(f"Znaleziono identyfikator klienta: {client_guid}")
    except Exception as e:
        print(f"Błąd podczas wyszukiwania identyfikatora klienta: {e}")
        exit()

    # Select the client
    try:
        print("Wybieranie klienta...")
        headers['Referer'] = 'https://ebok.enea.pl/dashboard/many-clients'
        client_selection_url = f'https://ebok.enea.pl/dashboard/select-current-client/{client_guid}'
        client_response = session.get(client_selection_url, headers=headers)
        client_response.raise_for_status()
        print("Pomyślnie wybrano klienta.")
    except requests.exceptions.RequestException as e:
        print(f"Błąd podczas wybierania klienta: {e}")
        print(client_response.text)
        exit()

    # Get the summary balancing chart page to find the pointOfDeliveryId and available years
    try:
        print("Pobieranie strony z wykresem bilansowania...")
        headers['Referer'] = 'https://ebok.enea.pl/dashboard'
        summary_page = session.get(summary_balancing_chart_url, headers=headers)
        summary_page.raise_for_status()

        point_of_delivery_id_match = re.search(r'data-point-of-delivery-id="(.*?)"', summary_page.text)
        if not point_of_delivery_id_match:
            print("Błąd: Nie można znaleźć pointOfDeliveryId na stronie wykresu bilansowania.")
            exit()
        point_of_delivery_id = point_of_delivery_id_match.group(1)
        print(f"Znaleziono pointOfDeliveryId: {point_of_delivery_id}")

        min_year_match = re.search(r'id="year-date-picker-input".*?data-min-date-value="(\d{4})"', summary_page.text)
        max_year_match = re.search(r'id="year-date-picker-input".*?data-max-date-value="(\d{4})"', summary_page.text)

        if not min_year_match or not max_year_match:
            print("Błąd: Nie można znaleźć minimalnego/maksymalnego roku na stronie wykresu bilansowania.")
            exit()

        min_year = int(min_year_match.group(1))
        max_year = int(max_year_match.group(1))
        print(f"Znaleziono dostępne lata: {min_year}-{max_year}")

    except requests.exceptions.RequestException as e:
        print(f"Błąd podczas pobierania strony z wykresem bilansowania: {e}")
        exit()

    # Download CSV for each year if it doesn't exist or is invalid
    for year in range(min_year, max_year + 1):
        filename = f"data/{customer_id}_dane_dobowo_godzinowe_{year}.csv"
        if os.path.exists(filename):
            if year == current_year:
                file_mod_time = datetime.fromtimestamp(os.path.getmtime(filename))
                if datetime.now() - file_mod_time < timedelta(hours=1):
                    print(f"Plik {filename} jest nowszy niż 1 godzina. Pomijanie pobierania.")
                    continue

            with open(filename, 'r') as f:
                try:
                    content = f.read()
                    if '---' not in content:
                        print(f"Plik {filename} już istnieje i jest prawidłowy. Pomijanie pobierania.")
                        continue
                    else:
                        print(f"Plik {filename} zawiera '---' i zostanie ponownie pobrany.")
                except UnicodeDecodeError:
                    print(f"Nie można odczytać pliku {filename} z powodu problemów z kodowaniem. Ponowne pobieranie.")


        csv_data = {
            'duration': 'year',
            'date': year,
            'pointOfDeliveryId': point_of_delivery_id
        }
        try:
            print(f"Pobieranie CSV za rok {year}...")
            headers['Referer'] = summary_balancing_chart_url
            csv_response = session.post(csv_download_url, data=csv_data, headers=headers)
            csv_response.raise_for_status()
            print(f"Pomyślnie pobrano dane CSV za rok {year}.")
        except requests.exceptions.RequestException as e:
            print(f"Błąd podczas pobierania CSV za rok {year}: {e}")
            print(csv_response.text)
            continue

        # Parse the JSON response and extract the CSV data
        try:
            json_data = csv_response.json()
            csv_content = json_data['data']
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Błąd podczas parsowania JSON lub wyodrębniania danych za rok {year}: {e}")
            continue

        # Save the CSV file
        with open(filename, 'w') as f:
            f.write(csv_content)

        print(f"Pomyślnie zapisano {filename}")