# eanalizer/enea_browser_login.py
"""
Logowanie do ebok.enea.pl w małym, wbudowanym oknie przeglądarki (Qt
WebEngine, czyli Chromium) - używane, odkąd Enea chroni formularz logowania
reCAPTCHA Enterprise (październik 2026).

Okno niczego nie wysyła za użytkownika: e-mail i hasło z konfiguracji są
tylko wstępnie wpisywane w formularz (jak robi to menedżer haseł), a
"Zaloguj" i kod 2FA obsługuje użytkownik - CAPTCHA ocenia zwykłą
przeglądarkę tak, jak w każdej innej. My tylko
zbieramy ciasteczka sesji (także HttpOnly) z magazynu ciasteczek silnika i
zamykamy okno, gdy przeglądarka wyląduje na zalogowanym ebok.enea.pl.

Profil przeglądarki jest trwały (katalog cache): zachowuje m.in. zgodę na
ciasteczka i ciasteczka Google, co sprzyja ocenie reCAPTCHA przy kolejnych
logowaniach. Ciasteczek sesyjnych Chromium po restarcie nie przywraca, więc
nie należy zakładać, że okno przejdzie przez logowanie samo.

PyQt6 jest zależnością opcjonalną (`pip install -e '.[browser]'`) i jest
importowany wyłącznie wewnątrz `login_via_browser` - reszta pakietu i testy
nie wymagają Qt.
"""

import argparse
import http.cookiejar
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

from . import enea_auth

INSTALL_HINT = (
    "pip install 'eanalizer[browser]' (w kopii repozytorium: "
    ".venv/bin/python -m pip install -e '.[browser]')"
)
ALLOWED_DOMAIN = enea_auth.ENEA_DOMAIN
WINDOW_TITLE = "eanalizer - logowanie do Enea eBOK"


def unavailable_reason():
    """Zwraca powód, dla którego okno logowania nie może zostać otwarte, albo None."""
    if importlib.util.find_spec("PyQt6") is None or (
        importlib.util.find_spec("PyQt6.QtWebEngineWidgets") is None
    ):
        return (
            "Logowanie w oknie przeglądarki wymaga dodatkowych pakietów (PyQt6, "
            f"PyQt6-WebEngine). Zainstaluj je poleceniem: {INSTALL_HINT}"
        )
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        return "Brak środowiska graficznego (DISPLAY/WAYLAND_DISPLAY) - nie można otworzyć okna logowania."
    return None


def is_allowed_navigation(url) -> bool:
    """Główna ramka okna może nawigować tylko po https://*.enea.pl."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == ALLOWED_DOMAIN or host.endswith("." + ALLOWED_DOMAIN)
    )


def make_cookie(name, value, domain, path, secure, http_only, expires):
    """Tworzy http.cookiejar.Cookie z wartości odczytanych z QNetworkCookie.

    `expires` to znacznik czasu w sekundach albo None dla ciasteczka sesyjnego.
    """
    return http.cookiejar.Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=domain.startswith("."),
        domain_initial_dot=domain.startswith("."),
        path=path or "/",
        path_specified=True,
        secure=secure,
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": None} if http_only else {},
    )


class CookieTracker:
    """
    Bieżący stan ciasteczek budowany z sygnałów cookieAdded/cookieRemoved.

    Przy nadpisaniu ciasteczka silnik zgłasza usunięcie starej wersji i dodanie
    nowej, ale kolejność sygnałów nie jest gwarantowana - usunięcie kasuje więc
    wpis tylko wtedy, gdy wciąż ma on usuwaną wartość.
    """

    def __init__(self):
        self._cookies = {}

    @staticmethod
    def _key(cookie):
        return (cookie.name, cookie.domain, cookie.path)

    def added(self, cookie):
        self._cookies[self._key(cookie)] = cookie

    def removed(self, cookie):
        current = self._cookies.get(self._key(cookie))
        if current is not None and current.value == cookie.value:
            del self._cookies[self._key(cookie)]

    def enea_cookies(self):
        return [c for c in self._cookies.values() if enea_auth.is_enea_cookie(c)]


# Pola formularza na moja.enea.pl to kontrolowane inputy Reacta: wartość
# trzeba ustawić natywnym setterem i zgłosić zdarzenie "input", inaczej React
# jej nie zobaczy. Login przed hasłem - zmiana loginu czyści hasło. Formularz
# renderuje się leniwie, więc czekamy na pola do ~15 s. Formularza nie
# wysyłamy - "Zaloguj" klika użytkownik.
_AUTOFILL_TEMPLATE = """
(function () {
    var creds = %s;
    var setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, "value").set;
    function fill(input, value) {
        input.focus();
        setter.call(input, value);
        input.dispatchEvent(new Event("input", {bubbles: true}));
        input.dispatchEvent(new Event("change", {bubbles: true}));
        input.blur();
    }
    var attempts = 0;
    var timer = setInterval(function () {
        var login = document.querySelector('input[name="userLogin"]');
        var password = document.querySelector('input[name="userPassword"]');
        if (login && password) {
            clearInterval(timer);
            if (!login.value) { fill(login, creds.login); }
            if (!password.value) { fill(password, creds.password); }
        } else if (++attempts > 60) {
            clearInterval(timer);
        }
    }, 250);
})();
"""


def build_autofill_script(email, password):
    """Skrypt JS wypełniający (bez wysyłania) formularz logowania Enei."""
    # json.dumps daje poprawny literał JS - bez ryzyka wstrzyknięcia przez
    # cudzysłowy/ukośniki w haśle.
    return _AUTOFILL_TEMPLATE % json.dumps({"login": email, "password": password})


def is_login_form_url(url) -> bool:
    """Strona z formularzem e-mail/hasło (a nie np. z polem na kod 2FA)."""
    parsed = urlparse(url)
    return is_allowed_navigation(url) and parsed.path.lower().rstrip("/").endswith(
        "/logowanie"
    )


def _cookie_from_qt(qt_cookie):
    expires = None
    if not qt_cookie.isSessionCookie():
        expires = qt_cookie.expirationDate().toSecsSinceEpoch()
    return make_cookie(
        name=bytes(qt_cookie.name()).decode("utf-8", "replace"),
        value=bytes(qt_cookie.value()).decode("utf-8", "replace"),
        domain=qt_cookie.domain(),
        path=qt_cookie.path(),
        secure=qt_cookie.isSecure(),
        http_only=qt_cookie.isHttpOnly(),
        expires=expires,
    )


def _run_login_window(
    profile_dir, start_url=enea_auth.LOGIN_URL, debug=False, credentials=None
):
    """
    Otwiera okno logowania (w bieżącym procesie) i czeka, aż użytkownik się
    zaloguje. Zwraca parę (lista ciasteczek *.enea.pl jako
    http.cookiejar.Cookie, User-Agent okna) albo None, jeśli użytkownik
    zamknął okno przed zalogowaniem. `credentials` (e-mail, hasło) służą do
    wstępnego wypełnienia formularza.

    Qt WebEngine nie znosi ponownego tworzenia okna/profilu w tym samym
    procesie (segfault), więc wywołujemy to wyłącznie w procesie potomnym -
    patrz `login_via_browser`.
    """
    if not debug:
        # Chromium w Qt sypie na stderr mnóstwem nieistotnych komunikatów (GPU itp.).
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--log-level=3")
    # QtWebEngineWidgets musi zostać zaimportowany przed utworzeniem QApplication.
    from PyQt6 import sip
    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication

    class EneaOnlyPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            if is_main_frame and not is_allowed_navigation(url.toString()):
                if debug:
                    print(f"[debug] Zablokowano nawigację poza enea.pl: {url.toString()}")
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        def createWindow(self, window_type):
            return None  # bez wyskakujących okien

    app = QApplication.instance() or QApplication([sys.argv[0]])

    profile_dir = os.fspath(profile_dir)
    os.makedirs(profile_dir, exist_ok=True)
    profile = QWebEngineProfile("eanalizer-enea", app)
    profile.setPersistentStoragePath(profile_dir)
    profile.setCachePath(os.path.join(profile_dir, "cache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
    )

    tracker = CookieTracker()

    store = profile.cookieStore()
    store.cookieAdded.connect(lambda c: tracker.added(_cookie_from_qt(c)))
    store.cookieRemoved.connect(lambda c: tracker.removed(_cookie_from_qt(c)))

    page = EneaOnlyPage(profile)
    view = QWebEngineView()
    view.setPage(page)
    view.setWindowTitle(WINDOW_TITLE)
    view.resize(1000, 800)

    result = {"logged_in": False, "finishing": False}

    def finish():
        result["logged_in"] = True
        view.close()

    def on_load_finished(ok):
        url = page.url().toString()
        if debug:
            print(f"[debug] Okno logowania: załadowano {url} (ok={ok})")
        if ok and credentials and is_login_form_url(url):
            page.runJavaScript(build_autofill_script(*credentials))
        if ok and enea_auth.is_authenticated_url(url) and not result["finishing"]:
            result["finishing"] = True
            # Chwila na dostarczenie ostatnich sygnałów cookieAdded. Zbieramy
            # tylko ciasteczka ustawione w tej sesji okna (wczytanych z dysku
            # Qt nie zgłasza) - to wystarcza, bo EBOK_SESSION i ciasteczka
            # Keycloaka serwer ustawia na nowo przy każdym logowaniu.
            QTimer.singleShot(1000, finish)

    page.loadFinished.connect(on_load_finished)
    page.load(QUrl(start_url))
    view.show()
    print("Otwarto okno logowania Enea - zaloguj się w nim (okno zamknie się samo).")
    app.exec()

    # Stan zebrany przed sprzątaniem - niszczenie profilu może emitować
    # cookieRemoved dla ciasteczek sesyjnych.
    collected = tracker.enea_cookies()
    user_agent = profile.httpUserAgent()
    store.cookieAdded.disconnect()
    store.cookieRemoved.disconnect()
    # Kolejność sprzątania ma znaczenie: strona musi zniknąć przed profilem.
    sip.delete(view)
    sip.delete(page)
    sip.delete(profile)

    if debug:
        print(
            "[debug] Ciasteczka z okna logowania: "
            + ", ".join(f"{c.name} ({c.domain})" for c in collected)
        )
    if not result["logged_in"]:
        return None
    return collected, user_agent


def cookie_to_dict(cookie):
    return {
        "name": cookie.name,
        "value": cookie.value,
        "domain": cookie.domain,
        "path": cookie.path,
        "secure": cookie.secure,
        "http_only": cookie.has_nonstandard_attr("HttpOnly"),
        "expires": cookie.expires,
    }


def cookie_from_dict(data):
    return make_cookie(**data)


def login_via_browser(profile_dir, debug=False, email=None, password=None):
    """
    Uruchamia okno logowania w osobnym procesie (`python -m
    eanalizer.enea_browser_login`) i odbiera z niego ciasteczka przez plik
    tymczasowy. Zwraca parę (ciasteczka, User-Agent okna) albo None, jeśli
    użytkownik zamknął okno przed zalogowaniem.

    E-mail i hasło (do wypełnienia formularza) idą do procesu potomnego przez
    stdin, a nie w argumentach - te byłyby widoczne w `ps`.
    """
    stdin_data = json.dumps(
        {"email": email, "password": password} if email and password else {}
    )
    with tempfile.TemporaryDirectory(prefix="eanalizer-login-") as tmp:
        result_path = os.path.join(tmp, "wynik.json")
        command = [sys.executable, "-m", __name__, os.fspath(profile_dir), result_path]
        if debug:
            command.append("--debug")
        completed = subprocess.run(command, check=False, input=stdin_data, text=True)
        if not os.path.isfile(result_path):
            raise ConnectionError(
                "Okno logowania zakończyło się błędem "
                f"(kod wyjścia {completed.returncode})."
            )
        with open(result_path, encoding="utf-8") as f:
            data = json.load(f)
    if not data.get("logged_in"):
        return None
    return [cookie_from_dict(c) for c in data["cookies"]], data["user_agent"]


def main(argv=None):
    """Punkt wejścia procesu potomnego: okno logowania -> plik JSON z wynikiem."""
    parser = argparse.ArgumentParser(description="Okno logowania do Enea eBOK.")
    parser.add_argument("profile_dir")
    parser.add_argument("result_path")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    try:
        stdin_creds = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        stdin_creds = {}
    credentials = None
    if stdin_creds.get("email") and stdin_creds.get("password"):
        credentials = (stdin_creds["email"], stdin_creds["password"])

    result = _run_login_window(
        args.profile_dir, debug=args.debug, credentials=credentials
    )
    if result is None:
        data = {"logged_in": False}
    else:
        cookies, user_agent = result
        data = {
            "logged_in": True,
            "cookies": [cookie_to_dict(c) for c in cookies],
            "user_agent": user_agent,
        }
    # Plik zawiera tokeny sesji - tylko dla bieżącego użytkownika.
    fd = os.open(args.result_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)


def authenticate_session(session, profile_dir, debug=False, email=None, password=None):
    """
    Loguje `session` (requests) przez okno przeglądarki i weryfikuje wynik
    zwykłym zapytaniem na LOGIN_URL. Zwraca uwierzytelnioną odpowiedź.
    """
    reason = unavailable_reason()
    if reason:
        raise enea_auth.RecaptchaRequiredError(
            f"{reason}\n\nAlternatywnie:\n{enea_auth.COOKIE_IMPORT_HELP}"
        )
    login_result = login_via_browser(
        profile_dir, debug=debug, email=email, password=password
    )
    if login_result is None:
        raise ConnectionError("Okno logowania zostało zamknięte przed zalogowaniem.")
    imported, browser_user_agent = login_result
    for cookie in imported:
        session.cookies.set_cookie(cookie)
    if debug:
        print(f"[debug] User-Agent okna: {browser_user_agent}")
        print(f"[debug] User-Agent requests: {session.headers.get('User-Agent')}")
    response = session.get(enea_auth.LOGIN_URL)
    if not enea_auth.looks_authenticated(response) and browser_user_agent:
        # Ciasteczka F5 (TS*) mogą być powiązane z User-Agentem przeglądarki.
        print(
            "Sesja z okna nie działa z domyślnym User-Agentem - ponawiam z "
            "User-Agentem okna logowania."
        )
        session.headers["User-Agent"] = browser_user_agent
        response = session.get(enea_auth.LOGIN_URL)
        if enea_auth.looks_authenticated(response):
            print("Sesja działa z User-Agentem okna logowania.")
    if not enea_auth.looks_authenticated(response):
        raise ConnectionError(
            "Logowanie w przeglądarce zakończyło się, ale sesja nie działa w "
            f"enea-downloaderze (trafiono na {response.url}). Uruchom ponownie z "
            "--debug i zgłoś wynik."
        )
    print("Zalogowano pomyślnie (sesja z okna przeglądarki).")
    return response


if __name__ == "__main__":
    main()
