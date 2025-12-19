import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import pandas as pd
import urllib.request
from pathlib import Path  # Import Path

API_URL_TEMPLATE = "https://api.raporty.pse.pl/api/rce-pln?$filter=business_date+eq+'{date_str}'&$orderby=business_date+asc&$first=20000"
DATA_START_DATE = datetime(2024, 7, 1)


def _fetch_daily_rce_from_api(date_str: str) -> Optional[List[Dict]]:
    """Pobiera dane RCE dla jednego dnia z API PSE używając standardowych bibliotek."""
    url = API_URL_TEMPLATE.format(date_str=date_str)
    print(f"Pobieranie danych RCE dla {date_str} z API PSE...")
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                data = response.read()
                json_data = json.loads(data)
                return json_data.get("value", [])
            else:
                print(f"Błąd: API zwróciło status {response.status} dla daty {date_str}")
                return None
    except Exception as e:
        print(f"Błąd podczas połączenia z API dla {date_str}: {e}")
        return None


def get_hourly_rce_prices(start_date: datetime, end_date: datetime, cache_dir: Path) -> Dict[datetime, float]:
    """Pobiera, cachuje i przetwarza ceny RCE, zwracając słownik cen godzinowych."""
    cache_dir.mkdir(parents=True, exist_ok=True)  # Use the passed cache_dir
    all_prices: Dict[datetime, float] = {}
    current_date = start_date

    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        cache_path = cache_dir / f"{date_str}.json"  # Use the passed cache_dir

        daily_data = None
        if cache_path.is_file():  # Use Path.is_file()
            with open(cache_path, "r") as f:
                daily_data = json.load(f)
        elif current_date >= DATA_START_DATE:
            daily_data = _fetch_daily_rce_from_api(date_str)
            if daily_data:
                with open(cache_path, "w") as f:
                    json.dump(daily_data, f)
            else:
                with open(cache_path, "w") as f:
                    json.dump([], f)

        if daily_data:
            df = pd.DataFrame(daily_data)
            if not df.empty and "dtime" in df.columns and "rce_pln" in df.columns:
                df["dtime"] = df["dtime"].str.replace("a", "").str.replace("b", "")
                df["dtime"] = pd.to_datetime(df["dtime"])
                hourly_prices = df.set_index("dtime")["rce_pln"].resample("h").mean() / 1000
                for ts, price in hourly_prices.items():
                    all_prices[ts] = price

        current_date += timedelta(days=1)

    return all_prices
