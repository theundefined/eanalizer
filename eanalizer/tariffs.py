import pandas as pd
import holidays
from datetime import datetime
from typing import Optional, Tuple


class TariffManager:
    def __init__(self, config_path: str, years: range):
        self.tariffs_df = pd.read_csv(config_path)
        self.holidays = holidays.Poland(years=years)

    def get_zone_and_price(
        self, timestamp: datetime, tariff: str
    ) -> Optional[Tuple[str, float]]:
        """Zwraca nazwę strefy i cenę dla podanego znacznika czasu i taryfy."""
        day_type = (
            "weekend"
            if timestamp.weekday() >= 5 or timestamp in self.holidays
            else "weekday"
        )
        hour = timestamp.hour

        # Dla G11 i innych taryf z jednym typem dnia 'all'
        rules = self.tariffs_df[self.tariffs_df["tariff"] == tariff]
        if "all" in rules["day_type"].unique():
            day_type = "all"

        # Filtrujemy reguły dla podanego dnia i taryfy
        applicable_rules = rules[rules["day_type"] == day_type]

        for _, rule in applicable_rules.iterrows():
            if rule["start_hour"] <= hour < rule["end_hour"]:
                return rule["zone_name"], rule["price_per_kwh"]

        return None, 0.0  # Zwracamy None, jeśli żadna reguła nie pasuje
