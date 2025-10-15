# Wytyczne dla dewelopera AI (AIDEV_GUIDELINES.md)

Ten plik zawiera zbiór zasad i dobrych praktyk, których należy przestrzegać podczas pracy nad projektem `eanalizer`. Celem jest zapewnienie wysokiej jakości kodu, unikanie regresji i utrzymanie spójności projektu.

## 1. Każda zmiana funkcjonalna wymaga testu

Przed uznaniem zadania za zakończone, każda nowa lub zmodyfikowana funkcjonalność w kodzie Python musi być pokryta odpowiednim testem jednostkowym. 

- **Nowa funkcja?** Dodaj nowy test.
- **Modyfikacja istniejącej funkcji?** Zaktualizuj istniejący test, aby odzwierciedlał zmiany.

## 2. Dokumentacja (`README.md`) musi być zawsze aktualna

Każda zmiana w interfejsie użytkownika (CLI), taka jak dodanie, usunięcie lub zmiana nazwy flagi/argumentu, musi być natychmiast odzwierciedlona w pliku `README.md`. Przykłady użycia powinny być aktualne i spójne.

## 3. Nigdy nie usuwaj testów

Istniejących testów nie wolno usuwać, chyba że funkcja, którą testują, została jawnie i celowo usunięta z programu. Nowe funkcjonalności wymagają **nowych** testów, a nie modyfikacji starych w sposób, który usuwa poprzednie przypadki testowe.

## 4. Zawsze uruchamiaj testy po każdej zmianie

Po **każdej** operacji modyfikującej kod (`.py`, `.sh`) lub konfigurację, należy uruchomić pełen zestaw testów, aby upewnić się, że nie wprowadzono żadnej regresji. Polecenie do uruchamiania testów:
```bash
.venv/bin/python -m unittest discover tests
```

## 5. Ostrożnie z refaktoryzacją i importami

- Po zmianie nazwy lub przeniesieniu funkcji, **zawsze sprawdzaj i poprawiaj** wszystkie instrukcje `import` w plikach, które z niej korzystały.
- Unikaj wielkich, niekontrolowanych operacji zapisu na plikach. Upewnij się, że nie usuwasz przypadkowo istniejącego, działającego kodu.

## 6. Zawsze używaj skryptu opakowującego

W dokumentacji i przykładach zawsze używaj skryptu `./eanalizer-cli` zamiast bezpośredniego wywołania `python -m ...`, aby zapewnić spójność i prostotę dla użytkownika.
