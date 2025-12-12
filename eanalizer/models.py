from dataclasses import dataclass
from datetime import datetime


@dataclass
class EnergyData:
    timestamp: datetime
    pobor_przed: float  # Energia pobrana przed bilansowaniem
    oddanie_przed: float  # Energia oddana przed bilansowaniem
    pobor: float  # Energia pobrana po bilansowaniu (netto)
    oddanie: float  # Energia oddana po bilansowaniu (netto)


@dataclass
class SimulationResult:
    timestamp: datetime
    pobor_z_sieci: float
    oddanie_do_sieci: float
    pobor_z_magazynu: float
    oddanie_do_magazynu: float
    stan_magazynu: float
