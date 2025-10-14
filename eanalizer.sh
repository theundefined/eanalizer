#!/bin/bash

# Znajdź absolutną ścieżkę do katalogu, w którym znajduje się ten skrypt
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Zmień bieżący katalog na katalog, w którym jest skrypt. To kluczowe!
cd "$SCRIPT_DIR" || exit

# --- Od tego momentu wszystko działa tak, jakbyśmy byli w katalogu projektu ---

# Sprawdź, czy katalog .venv istnieje
if [ ! -d ".venv" ]; then
    echo "Wirtualne środowisko (.venv) nie znalezione. Tworzenie..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "Błąd: Nie udało się utworzyć wirtualnego środowiska. Upewnij się, że masz zainstalowany pakiet python3-venv." >&2
        exit 1
    fi
    
    echo "Instalowanie zależności w .venv..."
    .venv/bin/pip install -e .
    if [ $? -ne 0 ]; then
        echo "Błąd: Nie udało się zainstalować zależności." >&2
        exit 1
    fi
    echo "Środowisko gotowe."
fi

# Uruchom główny skrypt Pythona, przekazując mu wszystkie argumenty ($@)
.venv/bin/python -m eanalizer.cli "$@"
