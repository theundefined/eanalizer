import pandas as pd
import holidays
from datetime import datetime
from typing import Dict, Any, Optional

class TariffManager:
    def __init__(self, config_path: str, years: range):
        self.tariffs_df = pd.read_csv(config_path)
        self.holidays = holidays.Poland(years=years)

    def get_zone(self, timestamp: datetime, tariff: str) -> Optional[str]:
        if tariff == 'G11':
            return 'stala'

        day_type = 'weekend' if timestamp.weekday() >= 5 or timestamp in self.holidays else 'weekday'
        hour = timestamp.hour

        # Filtrujemy definicje taryf dla podanego dnia i taryfy
        rules = self.tariffs_df[(self.tariffs_df['tariff'] == tariff) & (self.tariffs_df['day_type'] == day_type)]

        for _, rule in rules.iterrows():
            # Sprawdzamy, czy godzina miesci sie w zakresie [start, end)
            if rule['start_hour'] <= hour < rule['end_hour']:
                return rule['zone_name']
        
        return None # Zwracamy None, jeśli żadna reguła nie pasuje
