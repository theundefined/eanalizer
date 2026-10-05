import html
import json
import re
from datetime import datetime, timedelta
from typing import Dict, Iterable, Optional, List
import pandas as pd
import urllib.request
from pathlib import Path  # Import Path

API_URL_TEMPLATE = "https://api.raporty.pse.pl/api/rce-pln?$filter=business_date+eq+'{date_str}'&$orderby=business_date+asc&$first=20000"
DATA_START_DATE = datetime(2024, 7, 1)
RCEM_URL = "https://www.pse.pl/oire/rcem-rynkowa-miesieczna-cena-energii-elektrycznej"
RCEM_CACHE_FILE = "rcem.json"
RCEM_CACHE_MAX_AGE = timedelta(hours=12)
POLISH_MONTHS = [
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
]


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
                print(
                    f"Błąd: API zwróciło status {response.status} dla daty {date_str}"
                )
                return None
    except Exception as e:
        print(f"Błąd podczas połączenia z API dla {date_str}: {e}")
        return None


def get_hourly_rce_prices(
    start_date: datetime, end_date: datetime, cache_dir: Path
) -> Dict[datetime, float]:
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
            if daily_data is None:
                # Pobieranie się nie powiodło (błąd sieci/API) - nie zapisujemy
                # do cache, aby kolejne uruchomienie mogło spróbować ponownie.
                print(
                    f"Nie udało się pobrać cen RCE dla {date_str}; dzień zostanie pominięty w tym uruchomieniu."
                )
            else:
                # Udane zapytanie, nawet jeśli nie ma jeszcze opublikowanych cen.
                with open(cache_path, "w") as f:
                    json.dump(daily_data, f)

        if daily_data:
            df = pd.DataFrame(daily_data)
            if not df.empty and "dtime" in df.columns and "rce_pln" in df.columns:
                df["dtime"] = df["dtime"].str.replace("a", "").str.replace("b", "")
                # "dtime" w API PSE to KONIEC okresu (np. 00:15 dla 00:00-00:15),
                # a znaczniki czasu Enei oznaczają początek godziny - cofamy
                # o jeden kwadrans, żeby cena trafiła do właściwej godziny.
                df["dtime"] = pd.to_datetime(df["dtime"]) - pd.Timedelta(minutes=15)
                hourly_prices = (
                    df.set_index("dtime")["rce_pln"].resample("h").mean() / 1000
                )
                for ts, price in hourly_prices.items():
                    all_prices[ts] = price

        current_date += timedelta(days=1)

    return all_prices


def parse_rcem_html(page: str) -> Dict[str, float]:
    """
    Parsuje stronę PSE z RCEm (jedna tabela na rok) i zwraca słownik
    {"RRRR-MM": cena w zł/kWh}. Jeśli dla miesiąca opublikowano skorygowaną
    RCEm, używana jest wartość z najpóźniejszą datą publikacji.
    """
    month_re = re.compile(
        r"\b(" + "|".join(POLISH_MONTHS) + r")\b\**", re.IGNORECASE
    )
    entry_re = re.compile(r"(\d+(?:,\d+)?)\s+(\d{2})\.(\d{2})\.(\d{4})")
    prices: Dict[str, float] = {}

    for table in re.findall(r"<table.*?</table>", page, re.S | re.IGNORECASE):
        text = html.unescape(re.sub(r"<[^>]+>", " ", table))
        text = re.sub(r"\s+", " ", text)
        year_match = re.search(r"\b(20\d{2})\b", text)
        if not year_match:
            continue
        year = int(year_match.group(1))
        months = list(month_re.finditer(text))
        for i, month in enumerate(months):
            end = months[i + 1].start() if i + 1 < len(months) else len(text)
            entries = entry_re.findall(text[month.end() : end])
            if not entries:
                continue
            price, day, mon, yr = max(entries, key=lambda e: (e[3], e[2], e[1]))
            month_no = POLISH_MONTHS.index(month.group(1).lower()) + 1
            prices[f"{year}-{month_no:02d}"] = round(
                float(price.replace(",", ".")) / 1000, 6
            )
    return prices


def _fetch_rcem_page() -> Optional[str]:
    print("Pobieranie cen RCEm ze strony PSE...")
    request = urllib.request.Request(RCEM_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                print(f"Błąd: strona PSE zwróciła status {response.status}")
                return None
            return response.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Błąd podczas pobierania cen RCEm: {e}")
        return None


def get_monthly_rcem_prices(
    months: Iterable[str], cache_dir: Path
) -> Dict[str, float]:
    """
    Zwraca miesięczne ceny RCEm (zł/kWh) jako {"RRRR-MM": cena}. Ceny są
    cachowane w jednym pliku; strona PSE jest pobierana ponownie tylko wtedy,
    gdy w cache brakuje któregoś z potrzebnych miesięcy, a cache jest starszy
    niż RCEM_CACHE_MAX_AGE.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / RCEM_CACHE_FILE
    needed = set(months)

    cached: Dict[str, float] = {}
    fetched_at: Optional[datetime] = None
    if cache_path.is_file():
        try:
            content = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = content.get("prices", {})
            fetched_at = datetime.fromisoformat(content["fetched_at"])
        except (ValueError, KeyError, TypeError):
            cached, fetched_at = {}, None

    cache_is_fresh = (
        fetched_at is not None and datetime.now() - fetched_at < RCEM_CACHE_MAX_AGE
    )
    if needed - cached.keys() and not cache_is_fresh:
        page = _fetch_rcem_page()
        parsed = parse_rcem_html(page) if page else {}
        if parsed:
            cached = {**cached, **parsed}
            cache_path.write_text(
                json.dumps(
                    {"fetched_at": datetime.now().isoformat(), "prices": cached},
                    indent=1,
                ),
                encoding="utf-8",
            )
        elif page:
            print("Ostrzeżenie: nie udało się odczytać cen RCEm ze strony PSE.")

    return {m: cached[m] for m in needed if m in cached}
