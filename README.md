# e-analizer

Aplikacja do analizy zużycia energii elektrycznej na podstawie danych od operatora.

## Instalacja

1.  Upewnij się, że masz zainstalowany pakiet `python3-venv`:
    ```bash
    sudo apt install python3.12-venv
    ```
2.  Utwórz wirtualne środowisko:
    ```bash
    python3 -m venv .venv
    ```
3.  Zainstaluj program i jego zależności (w tym `pandas` i `holidays`):
    ```bash
    .venv/bin/pip install -e .
    ```

## Użycie

Program wymaga podania taryfy (`--taryfa`) oraz danych wejściowych (`--pliki` lub `--katalog`).

## Testowanie

Aby uruchomić zestaw testów jednostkowych, wykonaj polecenie w głównym katalogu projektu:
```bash
.venv/bin/python -m unittest discover tests
```


### Podstawowa analiza z podziałem na strefy
Analiza wszystkich plików `.csv` z katalogu `data` dla taryfy `G12w`. Wyniki zostaną przedstawione z podziałem na strefy `niska` i `wysoka`.
```bash
.venv/bin/python -m eanalizer.cli --katalog data --taryfa G12w
```

### Analiza w zadanym okresie
Analiza danych dla taryfy `G12` w okresie od 1 stycznia do 31 marca 2024.
```bash
.venv/bin/python -m eanalizer.cli --katalog data --taryfa G12 --data-start 2024-01-01 --data-koniec 2024-03-31
```

### Symulacja fizycznego magazynu energii (z uwzględnieniem taryf)
Symulacja magazynu o pojemności 10 kWh dla taryfy `G12w`. Wyniki (pobór/oddanie do sieci) zostaną pokazane z podziałem na strefy. Dodatkowo, szczegółowe wyniki godzinowe zostaną wyeksportowane do pliku `symulacja.csv`.
```bash
.venv/bin/python -m eanalizer.cli --katalog data --taryfa G12w --magazyn-fizyczny 10 --eksport-symulacji symulacja.csv
```

### Inne opcje

*   **Eksport danych dziennych:** Dodaj `--eksport-dzienny <nazwa_pliku>.csv` do polecenia standardowej analizy (bez symulacji magazynu fizycznego).
### Obliczanie optymalnej pojemności magazynu
Analiza wszystkich plików z katalogu `data` w celu znalezienia optymalnej pojemności magazynu, która uwzględnia zarówno dni z nadprodukcją, jak i arbitraż taryfowy.
```bash
.venv/bin/python -m eanalizer.cli --katalog data --taryfa G12w --oblicz-optymalny-magazyn
```
