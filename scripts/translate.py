import polib

translations = {
    "Energy data analyzer.": "Analizator danych energetycznych.",
    "List of single data files to analyze.": "Lista pojedynczych plikow z danymi do analizy.",
    "Path to the directory with .csv files.": "Sciezka do katalogu z plikami .csv.",
    "Specifies the energy tariff for a single analysis (default: G11).": "Okresla taryfe energetyczna dla pojedynczej analizy (domyslnie: G11).",
    "Start date of the analysis (format YYYY-MM-DD).": "Data poczatkowa analizy (format RRRR-MM-DD).",
    "End date of the analysis (format YYYY-MM-DD).": "Data koncowa analizy (format RRRR-MM-DD).",
    "Capacity of the physical storage in kWh (e.g., 10.0).": "Pojemnosc fizycznego magazynu w kWh (np. 10.0).",
    "Efficiency of the physical storage (round-trip, default: 0.90, i.e., 90%%).": "Sprawność magazynu fizycznego (round-trip, domyslnie: 0.90, czyli 90%%).",
    "Path to the CSV file with hourly simulation results.": "Sciezka do pliku CSV z wynikami symulacji godzinowej.",
    "Path to the CSV file with aggregated daily data.": "Sciezka do pliku CSV z zagregowanymi danymi dziennymi.",
    "Calculates the optimal storage capacity.": "Oblicza optymalna pojemnosc magazynu.",
    "Use real RCE prices instead of fixed tariff prices.": "Uzyj rzeczywistych cen RCE zamiast stalych cen taryfowych.",
    "Enables calculations for the virtual net-metering storage.": "Wlacza obliczenia dla wirtualnego magazynu net-metering.",
    "Coefficient for energy returned in net-metering (default: 0.8).": "Wspolczynnik dla energii oddawanej w net-meteringu (domyslnie: 0.8).",
    "Runs a comparison of all available tariffs for the given period.": "Uruchamia porównanie wszystkich dostępnych taryf dla zadanego okresu.",
    "Enables verbose mode for tariff comparison.": "Włącza tryb szczegółowy dla porównania taryf.",
    "No .csv files found for processing in: {}": "Nie znaleziono plikow .csv do przetworzenia w: {}",
    "Found {} files to process:": "Znaleziono {} plikow do przetworzenia:",
    "Total loaded {} records.": "Lacznia wczytano {} rekordow.",
    "No data in the given date range for further analysis.": "Brak danych w podanym zakresie dat do dalszej analizy."
}

po = polib.pofile('locales/pl/LC_MESSAGES/eanalizer.po')

print("Translating file: locales/pl/LC_MESSAGES/eanalizer.po")
untranslated = []
for entry in po:
    if not entry.msgstr and entry.msgid in translations:
        entry.msgstr = translations[entry.msgid]
        print(f"Translated: '{entry.msgid}' -> '{entry.msgstr}'")
    elif not entry.msgstr:
        untranslated.append(entry.msgid)

if untranslated:
    print("\nWarning: The following strings are not translated:")
    for msgid in untranslated:
        print(f"  - {msgid}")

po.save()
print("\nTranslation complete.")