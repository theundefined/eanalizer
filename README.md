# e-analizer

Aplikacja do analizy zużycia energii elektrycznej na podstawie danych od operatora (Enea).
W większości stworzona przy użyciu [asystenta AI Gemini](https://gemini.google.com/).

## Główne funkcjonalności

-   **Wszechstronna Analiza**: Obliczaj koszty energii w oparciu o różne taryfy (G11, G12, G12w), symuluj system net-metering lub fizyczny magazyn energii.
-   **Net-billing**: Rozliczaj prosumenta w systemie net-billing - depozyt prosumencki wyceniany po cenach RCEm lub RCE (pobieranych z PSE), z współczynnikiem 1,23, 12-miesięczną ważnością depozytu i zwrotem nadpłaty.
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

    Logowanie Enea wymaga weryfikacji dwuskładnikowej (kod SMS lub e-mail) - `enea-downloader-cli` poprosi o wpisanie kodu w terminalu. Po udanym logowaniu sesja jest zapisywana w katalogu cache, więc kolejne uruchomienia mogą pominąć logowanie i 2FA, dopóki zapisana sesja pozostaje ważna.

    Od października 2026 formularz logowania Enei jest chroniony reCAPTCHA, więc logowanie hasłem z samego terminala nie jest możliwe. `enea-downloader-cli` otwiera wtedy małe okno przeglądarki (pozwalające poruszać się tylko po stronach `*.enea.pl`), z e-mailem i hasłem z konfiguracji wpisanymi już w formularz - wystarczy kliknąć „Zaloguj” i podać kod SMS/e-mail. Formularz nie jest wysyłany automatycznie. Po zalogowaniu okno zamyka się samo, a pobieranie rusza dalej. Okno wymaga jednorazowej instalacji dodatkowych pakietów (PyQt6 + PyQt6-WebEngine, ok. 130 MB):

    ```bash
    pip install 'eanalizer[browser]'                  # instalacja z PyPI
    .venv/bin/python -m pip install -e '.[browser]'   # kopia repozytorium (skrypty ./enea-downloader-cli)
    ```

    Gdy okna nie da się otworzyć (np. serwer bez środowiska graficznego), zaloguj się na [ebok.enea.pl](https://ebok.enea.pl) w zwykłej przeglądarce, wyeksportuj ciasteczka do pliku `cookies.txt` (format Netscape, np. rozszerzeniem „Get cookies.txt LOCALLY” → „Export All Cookies”) i przekaż go flagą `--import-cookies`. Wczytywane są wyłącznie ciasteczka domen `*.enea.pl`. Sesja trafia do katalogu cache, więc wyeksportowany plik można od razu usunąć.

    ```bash
    ./enea-downloader-cli
    ./enea-downloader-cli --import-cookies ~/Pobrane/cookies.txt
    ```

    | Flaga       | Skrót | Opis                                                                                                   |
    | ----------- | ----- | -------------------------------------------------------------------------------------------------------- |
    | `--force`   | `-f`  | Wymusza ponowne pobranie danych, nawet jeśli są aktualne.                                                  |
    | `--report`  | `-r`  | Tylko wyświetla zakres danych z plików na dysku (bez pobierania).                                          |
    | `--import-cookies PLIK` |  | Importuje sesję z pliku `cookies.txt` wyeksportowanego z przeglądarki po zalogowaniu na ebok.enea.pl (alternatywa dla okna logowania, np. bez środowiska graficznego). |
    | `--debug`   |       | Wypisuje dodatkowe informacje diagnostyczne o logowaniu i zapisuje zrzut ciasteczek sesji (nazwa/domena/wygaśnięcie) do katalogu cache. |

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

**6. Analiza ostatnich 365 dni danych (bez podawania konkretnych dat)**
```bash
./eanalizer-cli --taryfa G12w --okres ostatnie-365-dni
```

**7. Rozliczenie w systemie net-billing (wycena miesięczna RCEm)**
```bash
./eanalizer-cli --taryfa G12w --z-netbilling --okres poprzedni-rok
```

**8. Porównanie taryf w net-billingu z wyceną godzinową (RCE) i magazynem 10 kWh**
```bash
./eanalizer-cli --porownaj-taryfy --z-netbilling --wycena-netbilling rce --magazyn-fizyczny 10
```

**9. Zbiorcze zestawienie miesięczne (pobrane/wysłane, przed i po bilansowaniu)**
```bash
./eanalizer-cli --taryfa G12w --okres biezacy-rok --miesieczne --eksport-miesieczny dane_miesieczne.csv
```

### Pełna lista opcji

| Flaga                             | Skrót | Opis                                                                                              |
| --------------------------------- | ----- | ------------------------------------------------------------------------------------------------- |
| `--pliki <pliki...>`               | `-p`  | Wskazuje konkretne pliki CSV do analizy.                                                            |
| `--katalog <katalog>`             | `-k`  | Wskazuje katalog, z którego mają być wczytane wszystkie pliki CSV (domyślnie: `$HOME/.local/share/eanalizer/`).                |
| `--taryfa <nazwa>`                | `-t`  | Określa taryfę do analizy (np. `G11`, `G12w`). Domyślnie `G11`.                                       |
| `--data-start <RRRR-MM-DD>`       |       | Data początkowa analizy.                                                                           |
| `--data-koniec <RRRR-MM-DD>`      |       | Data końcowa analizy.                                                                              |
| `--okres <nazwa>`                 |       | Predefiniowany okres analizy (`ostatnie-30-dni`, `ostatnie-90-dni`, `ostatnie-365-dni`, `biezacy-miesiac`, `poprzedni-miesiac`, `biezacy-rok`, `poprzedni-rok`), liczony wstecz od ostatniej dostępnej daty w danych, a nie od dzisiejszej daty. Wzajemnie wykluczający się z `--data-start`/`--data-koniec`/`--ostatnie-dni`. |
| `--ostatnie-dni <N>`              |       | Analizuje N ostatnich dni danych, liczonych wstecz od ostatniej dostępnej daty w danych. Wzajemnie wykluczający się z `--data-start`/`--data-koniec`/`--okres`.                                                                        |
| `--magazyn-fizyczny <kWh>`        |       | Uruchamia symulację z fizycznym magazynem energii o podanej pojemności.                             |
| `--sprawnosc-magazynu <0.0-1.0>`  |       | Sprawność magazynu fizycznego (domyślnie `0.9`).                                                      |
| `--z-netmetering`                 |       | Włącza obliczenia dla wirtualnego magazynu (net-metering).                                          |
| `--wspolczynnik-netmetering <0.7/0.8>` |  | Współczynnik dla energii oddawanej w net-meteringu (domyślnie `0.8`).                                 |
| `--z-netbilling`                  |       | Rozlicza koszty w systemie net-billing (depozyt prosumencki). Wzajemnie wykluczający się z `--z-netmetering` i `--z-cenami-rce`. Działa też z `--magazyn-fizyczny` i `--porownaj-taryfy`. |
| `--wycena-netbilling <rcem/rce>`  |       | Wycena energii oddanej w net-billingu: `rcem` - miesięczna cena RCEm (domyślnie), `rce` - godzinowe ceny RCE (od 07.2024; wcześniejsze miesiące zawsze wg RCEm). |
| `--z-cenami-rce`                  |       | Używa rzeczywistych cen rynkowych (RCE) zamiast stałych cen taryfowych.                               |
| `--porownaj-taryfy`               |       | Uruchamia porównanie kosztów dla wszystkich dostępnych taryf.                                         |
| `--oblicz-optymalny-magazyn`      |       | Oblicza i wyświetla optymalną pojemność magazynu dla dwóch scenariuszy.                             |
| `--eksport-symulacji <plik.csv>`  |       | Eksportuje godzinowe wyniki symulacji magazynu do pliku CSV.                                         |
| `--eksport-dzienny <plik.csv>`    |       | Eksportuje zagregowane dane dzienne do pliku CSV.                                                     |
| `--miesieczne`                    |       | Wyświetla tabelę z zagregowanymi danymi miesięcznymi (pobrane/wysłane, przed i po bilansowaniu).      |
| `--eksport-miesieczny <plik.csv>` |       | Eksportuje zagregowane dane miesięczne do pliku CSV.                                                   |
| `--verbose`                       | `-v`  | Włącza tryb szczegółowy, np. dla porównania taryf.                                                  |

> **Uwaga:** `--z-cenami-rce` to uproszczony model, w którym zarówno pobór, jak i oddanie wyceniane są po RCE - do rzeczywistego rozliczenia prosumenta użyj `--z-netbilling`. `--z-cenami-rce` nie obsługuje symulacji magazynu ani net-meteringu (`--magazyn-fizyczny`, `--z-netmetering`, `--sprawnosc-magazynu`) ani eksportu/obliczania optymalnego magazynu. `--porownaj-taryfy` nie obsługuje eksportu ani obliczania optymalnego magazynu. Te flagi, jeśli podane w niewspieranym trybie, zostaną zignorowane, o czym program wypisze stosowne ostrzeżenie.

### Net-billing - przyjęte zasady rozliczenia

Rozliczenie (`--z-netbilling`) odwzorowuje zasady z ustawy OZE i warunków Enei dla prosumentów net-billing:

-   Energia pobrana z sieci (po bilansowaniu godzinowym) jest kupowana po cenach z `tariffs.csv` - osobno część energetyczna (`energy_price`) i dystrybucyjna (`dist_price`).
-   Energia oddana tworzy depozyt prosumencki: ilość × RCEm danego miesiąca (wycena `rcem`) lub suma godzinowych iloczynów ilość × RCE (wycena `rce`, ujemne ceny liczone jako 0). Ceny RCEm pobierane są ze strony PSE (z uwzględnieniem korekt), a RCE z API PSE; obie są cachowane w katalogu cache.
-   Od 02.2025 wartość depozytu jest mnożona przez współczynnik 1,23.
-   Depozyt z danego miesiąca jest dostępny od kolejnego miesiąca przez 12 miesięcy i pokrywa **wyłącznie koszt energii** - opłaty dystrybucyjne i stałe płacone są zawsze. Najstarsze środki wykorzystywane są w pierwszej kolejności.
-   Niewykorzystany depozyt po 12 miesiącach jest zwracany do 20% wartości depozytu miesięcznego (30% przy wycenie godzinowej RCE od 02.2025); zwrot nadpłaty liczony jest dla depozytów wygasających od 07.2024. Reszta przepada.

Ograniczenia: dla wszystkich lat stosowane są ceny z bieżącego `tariffs.csv`, a opłaty stałe liczone są za pełne miesiące.

### Strefy czasowe taryf Enea

Domyślny `tariffs.csv` odwzorowuje strefy z taryfy ENEA Operator: G12 - strefa nocna 13:00-15:00 i 22:00-6:00; G12w - szczyt 6:00-21:00 w dni robocze, poza szczytem 21:00-6:00 oraz całe weekendy i święta. Starsze wersje programu tworzyły plik z błędnymi godzinami (G12 bez okna 13-15, G12w ze szczytem do 22:00) - program ostrzeże o tym przy uruchomieniu; wystarczy usunąć `tariffs.csv`, aby przy kolejnym uruchomieniu powstał poprawny plik.

## Rozwój i Testowanie

Repozytorium jest skonfigurowane do pracy z `pre-commit` w celu automatycznego formatowania i sprawdzania kodu.

1.  **Instalacja narzędzi deweloperskich:**
    ```bash
    .venv/bin/pip install -e ".[dev]"
    ```
2.  **Instalacja pre-commit hook:**
    ```bash
    pre-commit install
    ```
3.  **Uruchamianie testów:**
    ```bash
    .venv/bin/python -m unittest discover tests
    ```