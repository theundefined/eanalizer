# e-analizer

Aplikacja do analizy zużycia energii elektrycznej na podstawie danych od operatora (Enea).
W większości stworzona przy użyciu [asystenta AI Gemini](https://gemini.google.com/).

## Główne funkcjonalności

-   **Wszechstronna Analiza**: Obliczaj koszty energii w oparciu o różne taryfy (G11, G12, G12w), symuluj system net-metering lub fizyczny magazyn energii.
-   **Analiza Rynkowa**: Wykorzystaj rzeczywiste, godzinowe ceny rynkowe (RCE) pobierane z API PSE do precyzyjnej analizy finansowej.
-   **Optymalizacja Magazynu**: Oblicz optymalną pojemność magazynu energii w dwóch scenariuszach: dla samowystarczalności oraz dla arbitrażu taryfowego.
-   **Porównanie Taryf**: Automatycznie porównaj koszty dla wszystkich dostępnych taryf, aby znaleźć najkorzystniejszą opcję dla Twojego profilu zużycia.
-   **Elastyczność i Eksport**: Filtruj dane według zakresu dat, eksportuj godzinowe wyniki symulacji oraz dzienne agregaty do plików CSV.
-   **Integralność Danych**: Automatycznie wykrywaj i raportuj brakujące dane godzinowe w analizowanym okresie.

## Instalacja

1.  Upewnij się, że masz zainstalowany menedżer pakietów `pip` oraz moduł `venv` dla Twojej wersji Pythona. W systemach bazujących na Debianie/Ubuntu:
    ```bash
    sudo apt update
    sudo apt install python3-pip python3-venv
    ```
2.  Skrypt `eanalizer-cli` przy pierwszym uruchomieniu automatycznie tworzy wirtualne środowisko i instaluje wszystkie potrzebne zależności.
3.  **Zalecana instalacja jako aplikacja CLI (przez pipx):**
    ```bash
    pipx install eanalizer
    ```
    lub
    **Instalacja w trybie deweloperskim (z edytowalnym kodem):**
    ```bash
    python3 -m venv .venv
    .venv/bin/pip install -e .
    ```

## Dane o zużyciu

Dane o zużyciu energii w formacie CSV można pozyskać na dwa sposoby:

1.  **Manualnie**: Pobierz pliki z danymi godzinowymi z portalu [Enea eBOK](https://ebok.enea.pl/meter/summaryBalancingChart) i umieść je w katalogu danych `eanalizer`.
2.  **Automatycznie**: Użyj dołączonego skryptu `enea-downloader-cli`, który po podaniu danych logowania do eBOK Enei automatycznie pobierze i zapisze wszystkie dostępne dane.

## Lokalizacja plików konfiguracyjnych i danych

Program `eanalizer` przechowuje swoje pliki w standardowych lokalizacjach systemowych:

*   **Konfiguracja (tariffs.csv)**: `~/.config/eanalizer/` (np. `tariffs.csv`)
*   **Dane (pobrane CSV)**: `~/.local/share/eanalizer/`
*   **Cache (ceny RCE)**: `~/.cache/eanalizer/`

Na innych systemach operacyjnych ścieżki mogą się różnić, zgodnie ze standardami `platformdirs`.

## Użycie

Program uruchamia się za pomocą skryptu `eanalizer-cli`, który automatycznie zarządza wirtualnym środowiskiem.

### Przykłady użycia

**1. Podstawowa analiza kosztów dla taryfy G12w z net-meteringiem**
```bash
./eanalizer-cli --taryfa G12w --z-netmetering
```

**2. Symulacja fizycznego magazynu energii**
Symulacja magazynu o pojemności 10 kWh i sprawności 90%.
```bash
./eanalizer-cli --taryfa G12w --magazyn-fizyczny 10 --sprawnosc-magazynu 0.9
```

**3. Porównanie wszystkich taryf w zadanym okresie**
```bash
./eanalizer-cli --porownaj-taryfy --data-start 2024-01-01 --data-koniec 2024-12-31
```

**4. Analiza finansowa w oparciu o ceny rynkowe (RCE)**
```bash
./eanalizer-cli --z-cenami-rce --data-start 2025-01-01 --data-koniec 2025-01-07
```

**5. Obliczenie optymalnej pojemności magazynu i eksport danych**
```bash
./eanalizer-cli --taryfa G12w --oblicz-optymalny-magazyn --eksport-dzienny dane_dzienne.csv
```

### Pełna lista opcji

| Flaga                             | Skrót | Opis                                                                                              |
| --------------------------------- | ----- | ------------------------------------------------------------------------------------------------- |
| `--pliki <pliki...>`               | `-p`  | Wskazuje konkretne pliki CSV do analizy.                                                            |
| `--katalog <katalog>`             | `-k`  | Wskazuje katalog, z którego mają być wczytane wszystkie pliki CSV (domyślnie: `$HOME/.local/share/eanalizer/`).                |
| `--taryfa <nazwa>`                | `-t`  | Określa taryfę do analizy (np. `G11`, `G12w`). Domyślnie `G11`.                                       |
| `--data-start <RRRR-MM-DD>`       |       | Data początkowa analizy.                                                                           |
| `--data-koniec <RRRR-MM-DD>`      |       | Data końcowa analizy.                                                                              |
| `--magazyn-fizyczny <kWh>`        |       | Uruchamia symulację z fizycznym magazynem energii o podanej pojemności.                             |
| `--sprawnosc-magazynu <0.0-1.0>`  |       | Sprawność magazynu fizycznego (domyślnie `0.9`).                                                      |
| `--z-netmetering`                 |       | Włącza obliczenia dla wirtualnego magazynu (net-metering).                                          |
| `--wspolczynnik-netmetering <0.7/0.8>` |  | Współczynnik dla energii oddawanej w net-meteringu (domyślnie `0.8`).                                 |
| `--z-cenami-rce`                  |       | Używa rzeczywistych cen rynkowych (RCE) zamiast stałych cen taryfowych.                               |
| `--porownaj-taryfy`               |       | Uruchamia porównanie kosztów dla wszystkich dostępnych taryf.                                         |
| `--oblicz-optymalny-magazyn`      |       | Oblicza i wyświetla optymalną pojemność magazynu dla dwóch scenariuszy.                             |
| `--eksport-symulacji <plik.csv>`  |       | Eksportuje godzinowe wyniki symulacji magazynu do pliku CSV.                                         |
| `--eksport-dzienny <plik.csv>`    |       | Eksportuje zagregowane dane dzienne do pliku CSV.                                                     |
| `--verbose`                       | `-v`  | Włącza tryb szczegółowy, np. dla porównania taryf.                                                  |

## Rozwój i Testowanie

Repozytorium jest skonfigurowane do pracy z `pre-commit` w celu automatycznego formatowania i sprawdzania kodu.

1.  **Instalacja narzędzi deweloperskich:**
    ```bash
    .venv/bin/pip install -r requirements-dev.txt
    ```
2.  **Instalacja pre-commit hook:**
    ```bash
    pre-commit install
    ```
3.  **Uruchamianie testów:**
    ```bash
    .venv/bin/python -m unittest discover tests
    ```