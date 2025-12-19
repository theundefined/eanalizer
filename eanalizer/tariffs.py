import pandas as pd
import holidays
from datetime import datetime
from typing import List, Optional, Tuple


class TariffManager:
    def __init__(self, config_path: str, years: range):
        self.tariffs_df = pd.read_csv(config_path)
        self.holidays = holidays.Poland(years=years)

    def get_zone_and_price(self, timestamp: datetime, tariff: str) -> Optional[Tuple[str, float, float]]:
        """Zwraca nazwę strefy, cenę za energię i cenę za dystrybucję dla podanego znacznika czasu i taryfy."""
        day_type = "weekend" if timestamp.weekday() >= 5 or timestamp in self.holidays else "weekday"
        hour = timestamp.hour

        rules = self.tariffs_df[self.tariffs_df["tariff"].str.lower() == tariff.lower()]
        if not rules.empty and "all" in rules["day_type"].unique():
            day_type = "all"

        applicable_rules = rules[rules["day_type"] == day_type]

        for _, rule in applicable_rules.iterrows():
            start = rule["start_hour"]
            end = rule["end_hour"]
            # Standard case: e.g., 8 <= 10 < 16
            if start < end and start <= hour < end:
                return rule["zone_name"], rule["energy_price"], rule["dist_price"]
            # Overnight case: e.g., 22 <= 23 < 24 or 0 <= 0 < 6
            elif start > end and (hour >= start or hour < end):
                return rule["zone_name"], rule["energy_price"], rule["dist_price"]

        return None, 0.0, 0.0

    def get_fixed_fee(self, tariff: str) -> float:
        """Zwraca stałą opłatę miesięczną dla danej taryfy."""
        rules = self.tariffs_df[self.tariffs_df["tariff"] == tariff]
        if not rules.empty:
            return rules.iloc[0]["dist_fee"]
        return 0.0

    def get_all_tariffs(self) -> List[str]:
        """Zwraca listę wszystkich dostępnych taryf."""
        return self.tariffs_df["tariff"].unique().tolist()
