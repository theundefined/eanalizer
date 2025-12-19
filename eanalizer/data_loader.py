import pandas as pd
from typing import List
from .models import EnergyData
import io


def load_from_enea_csv(file_path: str) -> List[EnergyData]:
    """Wczytuje i parsuje dane z pliku CSV od Enei, uprzednio czyszcząc go z bajtów zerowych."""
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            file_content = f.read()

        cleaned_content = file_content.replace("\0", "")
        file_like_object = io.StringIO(cleaned_content)

        # Definiujemy nazwy wszystkich interesujących nas kolumn
        pobor_przed_col = "Wolumen energii elektrycznej pobranej z sieci przed bilansowaniem godzinowym"
        oddanie_przed_col = "Wolumen energii elektrycznej oddanej do sieci przed bilansowaniem godzinowym"
        pobor_po_col = "Wolumen energii elektrycznej pobranej z sieci po bilansowaniu godzinowym"
        oddanie_po_col = "Wolumen energii elektrycznej oddanej do sieci po bilansowaniu godzinowym"

        df = pd.read_csv(
            file_like_object,
            delimiter=";",
            dtype={
                "Data": str,
                pobor_przed_col: str,
                oddanie_przed_col: str,
                pobor_po_col: str,
                oddanie_po_col: str,
            },
        )

        df.rename(
            columns={
                "Data": "timestamp",
                pobor_przed_col: "pobor_przed",
                oddanie_przed_col: "oddanie_przed",
                pobor_po_col: "pobor",
                oddanie_po_col: "oddanie",
            },
            inplace=True,
        )

        # --- Ręczne czyszczenie i konwersja ---
        df["timestamp"] = df["timestamp"].str.replace("=", "").str.replace('"', "")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce").dt.floor("h")

        for col in ["pobor_przed", "oddanie_przed", "pobor", "oddanie"]:
            df[col] = pd.to_numeric(df[col].str.replace(",", "."), errors="coerce")

        df.dropna(
            subset=["timestamp", "pobor_przed", "oddanie_przed", "pobor", "oddanie"],
            inplace=True,
        )

        energy_data_list = [
            EnergyData(
                timestamp=row.timestamp,
                pobor_przed=row.pobor_przed,
                oddanie_przed=row.oddanie_przed,
                pobor=row.pobor,
                oddanie=row.oddanie,
            )
            for row in df.itertuples()
        ]

        print(f"Pomyślnie wczytano {len(energy_data_list)} rekordów z pliku: {file_path}")
        return energy_data_list

    except FileNotFoundError:
        print(f"Błąd: Plik nie został znaleziony: {file_path}")
        return []
    except Exception as e:
        print(f"Wystąpił nieoczekiwany błąd podczas wczytywania pliku: {e}")
        return []
