#!/bin/bash

_eanalizer_completions()
{
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Główne opcje
    opts="--pliki --katalog --taryfa --data-start --data-koniec --magazyn-fizyczny --eksport-symulacji --eksport-dzienny --oblicz-optymalny-magazyn --z-cenami-rce --z-netmetering --wspolczynnik-netmetering"

    # Podpowiedzi dla konkretnych opcji
    case "${prev}" in
        --taryfa)
            COMPREPLY=( $(compgen -W "G11 G12 G12w" -- "${cur}") )
            return 0
            ;;
        --wspolczynnik-netmetering)
            COMPREPLY=( $(compgen -W "0.7 0.8" -- "${cur}") )
            return 0
            ;;
        --katalog|--pliki|--eksport-symulacji|--eksport-dzienny)
            COMPREPLY=( $(compgen -f -- "${cur}") ) # Uzupełnianie plików/katalogów
            return 0
            ;;
    esac

    # Domyślne uzupełnianie dla opcji
    if [[ ${cur} == -* ]] ; then
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
        return 0
    fi
}

# Zarejestruj funkcję uzupełniającą dla naszego skryptu
complete -F _eanalizer_completions eanalizer-cli
