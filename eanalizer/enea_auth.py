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

W październiku 2026 Enea dodała do formularza logowania reCAPTCHA Enterprise
(niewidoczną, score-based; klucz w <meta name="recaptcha-site-key">, akcja
"login_form", pole "recaptcha_token" w JSON-ie /api/login/login). Tokenu nie
da się uczciwie wygenerować poza prawdziwą przeglądarką, więc gdy CAPTCHA
jest włączona, logowanie wykonuje użytkownik: domyślnie we wbudowanym oknie
przeglądarki (`enea_browser_login`, opcjonalne PyQt6), a awaryjnie w swojej
przeglądarce, skąd importujemy gotową sesję z wyeksportowanego pliku
cookies.txt (`import_cookies_file`). To uniezależnia pobieranie od kolejnych zmian w
samym formularzu logowania - ważne jest tylko to, żeby sesja ebok.enea.pl
(i SSO) była prawidłowa. Gdy front ma CAPTCHA wyłączoną
(data-recaptchaEnabled="0"), oficjalny frontend wysyła literalnie "null" -
robimy to samo i logowanie hasłem + 2FA działa jak wcześniej.
"""

import http.cookiejar
import json
import re
from urllib.parse import parse_qs, urlparse

LOGIN_URL = "https://ebok.enea.pl/logowanie"
MAX_2FA_ATTEMPTS = 5
ENEA_DOMAIN = "enea.pl"

COOKIE_IMPORT_HELP = (
    "Enea wymaga reCAPTCHA przy logowaniu, więc enea-downloader nie może się "
    "zalogować sam. Zaloguj się w przeglądarce i przekaż sesję:\n"
    "  1. Zaloguj się na https://ebok.enea.pl (hasło + kod SMS/e-mail).\n"
    "  2. Wyeksportuj ciasteczka do pliku cookies.txt (format Netscape), np.\n"
    "     rozszerzeniem \"Get cookies.txt LOCALLY\" -> \"Export All Cookies\"\n"
    "     (potrzebne są też ciasteczka SSO z sso.moja.enea.pl, nie tylko z\n"
    "     bieżącej karty; z pliku wczytywane są wyłącznie ciasteczka *.enea.pl).\n"
    "  3. Uruchom: ./enea-downloader-cli --import-cookies ŚCIEŻKA/cookies.txt\n"
    "  4. Usuń wyeksportowany plik - sesja zostanie zapisana w katalogu cache."
)


class RecaptchaRequiredError(ConnectionError):
    """Logowanie hasłem jest zablokowane przez reCAPTCHA - trzeba zaimportować sesję z przeglądarki."""

    def __init__(self, message=COOKIE_IMPORT_HELP):
        super().__init__(message)


def recaptcha_enabled(login_page_response) -> bool:
    """Odczytuje flagę data-recaptchaEnabled z HTML-a strony logowania."""
    html = getattr(login_page_response, "text", None)
    if not isinstance(html, str):
        return False
    match = re.search(r'data-recaptchaEnabled="(\w*)"', html, re.IGNORECASE)
    return bool(match) and match.group(1) == "1"


def is_enea_cookie(cookie) -> bool:
    domain = cookie.domain.lstrip(".").lower()
    return domain == ENEA_DOMAIN or domain.endswith("." + ENEA_DOMAIN)


def save_session_cookies(session, path):
    """Zapisuje ciasteczka sesji (LWPCookieJar), by kolejne uruchomienia pominęły logowanie."""
    jar = http.cookiejar.LWPCookieJar(str(path))
    for cookie in session.cookies:
        jar.set_cookie(cookie)
    jar.save(ignore_discard=True, ignore_expires=True)
    return jar


def import_cookies_file(session, path):
    """
    Wczytuje ciasteczka *.enea.pl z pliku cookies.txt (format Netscape,
    eksportowany z przeglądarki) do `session`. Pozostałe domeny są pomijane.
    Zwraca listę wczytanych ciasteczek (do wypisania nazw/domen - bez wartości).
    """
    jar = http.cookiejar.MozillaCookieJar(str(path))
    try:
        # Ciasteczka sesyjne (EBOK_SESSION, KEYCLOAK_IDENTITY...) nie mają daty
        # wygaśnięcia - bez ignore_discard/ignore_expires zostałyby pominięte.
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, http.cookiejar.LoadError) as e:
        raise ValueError(f"Nie można wczytać pliku ciasteczek {path}: {e}") from e
    imported = [cookie for cookie in jar if is_enea_cookie(cookie)]
    for cookie in imported:
        session.cookies.set_cookie(cookie)
    return imported


def _debug_dump_response(label, response):
    """Wypisuje na konsolę surową treść odpowiedzi API - tylko do jednorazowej
    inspekcji pól zwracanych przez Enea (np. licznik SMS-ów). Treść może
    zawierać dane konta - nigdy nie jest zapisywana do pliku."""
    try:
        body = json.dumps(response.json(), ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        body = response.text
    print(f"[debug] Odpowiedź {label} (status {response.status_code}): {body}")


def is_authenticated_url(url) -> bool:
    """Czy adres to zalogowany ebok.enea.pl (a nie formularz logowania)."""
    parsed = urlparse(url)
    return parsed.netloc == "ebok.enea.pl" and "logowanie" not in parsed.path.lower()


def looks_authenticated(response) -> bool:
    """Sprawdza, czy odpowiedź wylądowała na ebok.enea.pl (a nie na formularzu logowania)."""
    return is_authenticated_url(response.url)


def login(session, email, password, login_page_response, browser_profile_dir=None, debug=False):
    """
    Loguje `session`: hasłem + 2FA w terminalu, a gdy Enea wymaga reCAPTCHA -
    przez okno przeglądarki (jeśli podano `browser_profile_dir`).
    """
    try:
        return interactive_login(
            session, email, password, login_page_response, debug=debug
        )
    except RecaptchaRequiredError:
        if browser_profile_dir is None:
            raise
        from . import enea_browser_login

        return enea_browser_login.authenticate_session(
            session, browser_profile_dir, debug=debug, email=email, password=password
        )


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

    if recaptcha_enabled(login_page_response):
        raise RecaptchaRequiredError()

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
        # Tak robi oficjalny frontend, gdy CAPTCHA jest wyłączona.
        "recaptcha_token": "null",
    }
    login_resp = session.post(
        login_api_url,
        params=oidc_params,
        data=json.dumps(login_payload),
        headers=api_headers,
    )
    if debug:
        _debug_dump_response("login/login", login_resp)
    if login_resp.status_code == 400 and "recaptcha" in login_resp.text.lower():
        raise RecaptchaRequiredError()
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
