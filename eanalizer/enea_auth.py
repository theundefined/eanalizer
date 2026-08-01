# eanalizer/enea_auth.py
"""
Wspólna logika logowania do ebok.enea.pl, używana zarówno przez EneaDownloader
jak i przez interaktywną konfigurację danych logowania (config.py).

Od sierpnia 2026 Enea wymaga logowania przez OIDC/Keycloak (eumowy.enea.pl)
z weryfikacją dwuskładnikową (SMS/e-mail) zamiast bezpośredniego POST-a na
ebok.enea.pl/logowanie. ebok.enea.pl inicjuje ten flow i jest jego
redirect_uri, więc `requests` dostaje state/nonce za darmo podążając za
przekierowaniami - nie ma potrzeby ręcznej implementacji PKCE.
"""

import json
from urllib.parse import parse_qs, urlparse

LOGIN_URL = "https://ebok.enea.pl/logowanie"
EUMOWY_LOGIN_API = "https://eumowy.enea.pl/api/login/login"
EUMOWY_CODE_CHECK_API = "https://eumowy.enea.pl/api/login/code/check"
MAX_2FA_ATTEMPTS = 5


def looks_authenticated(response) -> bool:
    """Sprawdza, czy odpowiedź wylądowała na ebok.enea.pl (a nie na formularzu logowania eumowy)."""
    parsed = urlparse(response.url)
    return parsed.netloc == "ebok.enea.pl" and "logowanie" not in parsed.path.lower()


def interactive_login(session, email, password, login_page_response):
    """
    Loguje się do ebok.enea.pl przez OIDC (eumowy.enea.pl): email/hasło + kod
    weryfikacyjny (SMS/e-mail) wpisany interaktywnie w terminalu. Zwraca
    finalną, uwierzytelnioną odpowiedź (wylądowaną na ebok.enea.pl).

    `login_page_response` to odpowiedź z GET na LOGIN_URL wykonanego przez
    wywołującego - jeśli sesja jest już zalogowana, zostaje zwrócona od razu
    bez żadnej dodatkowej interakcji.
    """
    if looks_authenticated(login_page_response):
        return login_page_response

    parsed = urlparse(login_page_response.url)
    if "eumowy.enea.pl" not in parsed.netloc:
        raise ConnectionError(
            f"Nieoczekiwany adres strony logowania: {login_page_response.url}"
        )

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
        "Origin": "https://eumowy.enea.pl",
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
        EUMOWY_LOGIN_API,
        params=oidc_params,
        data=json.dumps(login_payload),
        headers=api_headers,
    )
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
        session.post(
            EUMOWY_CODE_CHECK_API,
            params=oidc_params,
            data=json.dumps({"emailAddress": email, "code": code}),
            headers=api_headers,
        )
        final_response = session.get(LOGIN_URL)
        if looks_authenticated(final_response):
            print("Zalogowano pomyślnie.")
            return final_response
        print("Nieprawidłowy lub wygasły kod, spróbuj ponownie.")

    raise ConnectionError(
        "Nie udało się zweryfikować kodu 2FA po maksymalnej liczbie prób."
    )
