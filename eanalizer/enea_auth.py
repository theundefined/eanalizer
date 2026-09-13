# eanalizer/enea_auth.py
"""
Wspólna logika logowania do ebok.enea.pl, używana zarówno przez EneaDownloader
jak i przez interaktywną konfigurację danych logowania (config.py).

Od sierpnia 2026 Enea wymaga logowania przez OIDC z weryfikacją
dwuskładnikową (SMS/e-mail) zamiast bezpośredniego POST-a na
ebok.enea.pl/logowanie. ebok.enea.pl inicjuje ten flow i jest jego
redirect_uri, więc `requests` dostaje state/nonce za darmo podążając za
przekierowaniami - nie ma potrzeby ręcznej implementacji PKCE.

We wrześniu 2026 Enea przeniosła front logowania z eumowy.enea.pl na
moja.enea.pl (301 redirect), przy niezmienionym kontrakcie OIDC i API
(identyczne query params i ścieżki /api/login/login, /api/login/code/check
- tylko inny host). Host API wyliczamy więc dynamicznie z faktycznego
adresu, na którym wylądował przekierowany GET na LOGIN_URL, zamiast go
zahardkodowywać - jeśli Enea znów przeniesie front logowania na inną
subdomenę, ten kod ma dalej działać bez zmian.
"""

import json
from urllib.parse import parse_qs, urlparse

LOGIN_URL = "https://ebok.enea.pl/logowanie"
MAX_2FA_ATTEMPTS = 5


def _debug_dump_response(label, response):
    """Wypisuje na konsolę surową treść odpowiedzi API - tylko do jednorazowej
    inspekcji pól zwracanych przez Enea (np. licznik SMS-ów). Treść może
    zawierać dane konta - nigdy nie jest zapisywana do pliku."""
    try:
        body = json.dumps(response.json(), ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        body = response.text
    print(f"[debug] Odpowiedź {label} (status {response.status_code}): {body}")


def looks_authenticated(response) -> bool:
    """Sprawdza, czy odpowiedź wylądowała na ebok.enea.pl (a nie na formularzu logowania eumowy)."""
    parsed = urlparse(response.url)
    return parsed.netloc == "ebok.enea.pl" and "logowanie" not in parsed.path.lower()


def interactive_login(session, email, password, login_page_response, debug=False):
    """
    Loguje się do ebok.enea.pl przez OIDC (host formularza logowania -
    obecnie moja.enea.pl - wyliczany dynamicznie z przekierowania): email/
    hasło + kod weryfikacyjny (SMS/e-mail) wpisany interaktywnie w
    terminalu. Zwraca finalną, uwierzytelnioną odpowiedź (wylądowaną na
    ebok.enea.pl).

    `debug=True` wypisuje na konsolę surową treść odpowiedzi JSON z
    /api/login/login i /api/login/code/check - przydatne do sprawdzenia,
    jakie pola (np. licznik pozostałych SMS-ów) faktycznie zwraca API Enei.

    `login_page_response` to odpowiedź z GET na LOGIN_URL wykonanego przez
    wywołującego - jeśli sesja jest już zalogowana, zostaje zwrócona od razu
    bez żadnej dodatkowej interakcji.
    """
    if looks_authenticated(login_page_response):
        return login_page_response

    parsed = urlparse(login_page_response.url)
    if not parsed.netloc.endswith("enea.pl"):
        raise ConnectionError(
            f"Nieoczekiwany adres strony logowania: {login_page_response.url}"
        )

    login_api_url = f"https://{parsed.netloc}/api/login/login"
    code_check_api_url = f"https://{parsed.netloc}/api/login/code/check"

    query = parse_qs(parsed.query)
    try:
        oidc_params = {
            "client_id": query["client_id"][0],
            "redirect_uri": query["redirect_uri"][0],
            "scope": query["scope"][0],
            "state": query["state"][0],
        }
    except KeyError as e:
        raise ConnectionError(
            f"Nie można odczytać parametrów logowania OIDC ze strony: {e}"
        ) from e

    api_headers = {
        "Content-Type": "text/plain;charset=UTF-8",
        "Origin": f"https://{parsed.netloc}",
        "Referer": login_page_response.url,
    }

    print("Logowanie (email/hasło)...")
    login_payload = {
        "login": email,
        "password": password,
        "client_id": oidc_params["client_id"],
        "redirect_uri": oidc_params["redirect_uri"],
    }
    login_resp = session.post(
        login_api_url,
        params=oidc_params,
        data=json.dumps(login_payload),
        headers=api_headers,
    )
    if debug:
        _debug_dump_response("login/login", login_resp)
    if login_resp.status_code != 200:
        raise ConnectionError(
            f"Logowanie nie powiodło się (status {login_resp.status_code}). "
            "Sprawdź email/hasło."
        )

    print("Wymagana weryfikacja dwuskładnikowa - sprawdź SMS lub e-mail od Enei.")
    for attempt in range(1, MAX_2FA_ATTEMPTS + 1):
        code = input(
            f"Podaj kod weryfikacyjny ({attempt}/{MAX_2FA_ATTEMPTS}): "
        ).strip()
        code_check_resp = session.post(
            code_check_api_url,
            params=oidc_params,
            data=json.dumps({"emailAddress": email, "code": code}),
            headers=api_headers,
        )
        if debug:
            _debug_dump_response("login/code/check", code_check_resp)
        final_response = session.get(LOGIN_URL)
        if looks_authenticated(final_response):
            print("Zalogowano pomyślnie.")
            return final_response
        print("Nieprawidłowy lub wygasły kod, spróbuj ponownie.")

    raise ConnectionError(
        "Nie udało się zweryfikować kodu 2FA po maksymalnej liczbie prób."
    )
