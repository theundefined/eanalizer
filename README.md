# e-analizer

Aplikacja do analizy zużycia energii elektrycznej na podstawie danych od operatora.
W większości stworzona przy użyciu GEMINI

## Instalacja

1.  Upewnij się, że masz zainstalowany pakiet `python3-venv`:
    ```bash
    sudo apt install python3.12-venv
    ```
2.  (Opcjonalnie) Skrypt `eanalizer-cli` przy pierwszym uruchomieniu automatycznie tworzy wirtualne środowisko i instaluje zależności. Poniższy krok jest przeznaczony dla deweloperów lub w przypadku manualnej instalacji:
    ```bash
    python3 -m venv .venv
    .venv/bin/pip install -e .
    ```

## Dane

Dane o zużyciu energii w formacie CSV można pozyskać na dwa sposoby:

1.  **Manualnie**: Pobierz dane z portalu [Enea eBOK](https://ebok.enea.pl/meter/summaryBalancingChart) dla każdego roku osobno i umieść je w katalogu `data`.
2.  **Automatycznie**: Użyj programu `enea_downloader`, który jest dostępny do pobrania na stronie z wydaniami (Releases) tego repozytorium. Program automatycznie pobierze dane po podaniu loginu i hasła do serwisu Enea.

## Użycie

Program najłatwiej uruchomić za pomocą skryptu `eanalizer-cli`, który automatycznie zarządza wirtualnym środowiskiem. Po prostu wywołaj go, podając odpowiednie flagi.

### Podstawowa analiza (ceny taryfowe)
Analiza dla taryfy `G12w` z włączonymi obliczeniami net-meteringu.
```bash
./eanalizer-cli --katalog data --taryfa G12w --z-netmetering
```

### Analiza finansowa (ceny rynkowe RCE)
Analiza dla okresu od 1 do 3 lipca 2024 z użyciem rzeczywistych, pobieranych z API cen RCE.
```bash
./eanalizer-cli --katalog data --data-start 2024-07-01 --data-koniec 2024-07-03 --z-cenami-rce
```

### Symulacja fizycznego magazynu energii
Symulacja magazynu o pojemności 10 kWh dla taryfy `G12w` z eksportem wyników do pliku.
```bash
./eanalizer-cli --katalog data --taryfa G12w --magazyn-fizyczny 10 --eksport-symulacji symulacja.csv
```

### Obliczanie optymalnej pojemności magazynu
```bash
./eanalizer-cli --katalog data --taryfa G12w --oblicz-optymalny-magazyn
```

### Inne popularne opcje

*   `--eksport-dzienny <plik.csv>`: Zapisuje dzienne podsumowanie zużycia do pliku CSV.
*   `--wspolczynnik-netmetering 0.7`: Zmienia domyślny współczynnik net-meteringu (0.8) na inny.
