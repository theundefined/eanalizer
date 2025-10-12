from dataclasses import dataclass
from datetime import datetime

@dataclass
class EnergyData:
    timestamp: datetime
    pobor_przed: float      # Energia pobrana przed bilansowaniem
    oddanie_przed: float    # Energia oddana przed bilansowaniem
    pobor: float              # Energia pobrana po bilansowaniu (netto)
    oddanie: float            # Energia oddana po bilansowaniu (netto)