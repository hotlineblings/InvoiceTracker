#!/usr/bin/env python3
"""
Skrypt do edycji istniejącego profilu/konta w systemie multi-tenancy.

Użycie:
    1. Uruchom: python list_profiles.py (aby zobaczyć ID profili)
    2. Edytuj PROFILE_ID i dane poniżej
    3. Uruchom: python edit_profile.py
    4. Dane zostaną zaktualizowane z automatycznym szyfrowaniem
"""

import sys
from InvoiceTracker.models import db, Account
from InvoiceTracker.app import create_app

# ========================================
# EDYTUJ DANE PROFILU TUTAJ:
# ========================================

PROFILE_ID = 2  # <-- ID profilu do edycji (użyj list_profiles.py aby sprawdzić)

# Które pola chcesz zaktualizować? (True = tak, False = nie)
UPDATE_NAME = False
UPDATE_INFAKT_API_KEY = True
UPDATE_EMAIL_FROM = True
UPDATE_SMTP_SERVER = False
UPDATE_SMTP_PORT = False
UPDATE_SMTP_USERNAME = True
UPDATE_SMTP_PASSWORD = True
UPDATE_IS_ACTIVE = False

# NOWE WARTOŚCI (edytuj tylko te, które mają UPDATE_* = True)
NEW_NAME = "Pozytron Szkolenia"  # Jeśli UPDATE_NAME = True

NEW_INFAKT_API_KEY = "017c14c6e2781510be7c539642e6472156fb19db"  # Jeśli UPDATE_INFAKT_API_KEY = True

NEW_EMAIL_FROM = "rozliczenia@pozytron.pl"  # Jeśli UPDATE_EMAIL_FROM = True

NEW_SMTP_SERVER = "pozytron.pl"  # Jeśli UPDATE_SMTP_SERVER = True
NEW_SMTP_PORT = 587  # Jeśli UPDATE_SMTP_PORT = True
NEW_SMTP_USERNAME = "rozliczenia@pozytron.pl"  # Jeśli UPDATE_SMTP_USERNAME = True
NEW_SMTP_PASSWORD = "Cz@pr@ck@!23"  # Jeśli UPDATE_SMTP_PASSWORD = True

NEW_IS_ACTIVE = True  # Jeśli UPDATE_IS_ACTIVE = True

# ========================================
# KOD SKRYPTU - NIE EDYTUJ PONIŻEJ
# ========================================

def main():
    print("=" * 60)
    print("✏️  Edycja profilu w InvoiceTracker")
    print("=" * 60)

    app = create_app()

    with app.app_context():
        # Znajdź profil
        account = Account.query.get(PROFILE_ID)

        if not account:
            print(f"\n❌ BŁĄD: Nie znaleziono profilu o ID: {PROFILE_ID}")
            print(f"\n💡 Uruchom: python list_profiles.py aby zobaczyć dostępne profile")
            return 1

        print(f"\n📝 Edytowanie profilu: {account.name} (ID: {account.id})")
        print(f"   Obecny email: {account.email_from}")
        print(f"   Obecny status: {'Aktywny' if account.is_active else 'Nieaktywny'}")

        # Pokaż co zostanie zmienione
        changes = []
        if UPDATE_NAME:
            changes.append(f"   - Nazwa: '{account.name}' → '{NEW_NAME}'")
        if UPDATE_INFAKT_API_KEY:
            changes.append(f"   - InFakt API Key: ******* → *******")
        if UPDATE_EMAIL_FROM:
            changes.append(f"   - Email From: '{account.email_from}' → '{NEW_EMAIL_FROM}'")
        if UPDATE_SMTP_SERVER:
            changes.append(f"   - SMTP Server: '{account.smtp_server}' → '{NEW_SMTP_SERVER}'")
        if UPDATE_SMTP_PORT:
            changes.append(f"   - SMTP Port: {account.smtp_port} → {NEW_SMTP_PORT}")
        if UPDATE_SMTP_USERNAME:
            changes.append(f"   - SMTP Username: ******* → *******")
        if UPDATE_SMTP_PASSWORD:
            changes.append(f"   - SMTP Password: ******* → *******")
        if UPDATE_IS_ACTIVE:
            changes.append(f"   - Status: {'Aktywny' if account.is_active else 'Nieaktywny'} → {'Aktywny' if NEW_IS_ACTIVE else 'Nieaktywny'}")

        if not changes:
            print(f"\n⚠️  Brak zmian do zastosowania!")
            print(f"   Ustaw odpowiednie flagi UPDATE_* = True w skrypcie")
            return 1

        print(f"\n📋 Planowane zmiany:")
        for change in changes:
            print(change)

        # Walidacja placeholderów
        has_placeholders = False
        if UPDATE_INFAKT_API_KEY and "WPISZ_PRAWDZ" in NEW_INFAKT_API_KEY:
            print(f"\n⚠️  UWAGA: InFakt API Key wciąż jest placeholderem!")
            has_placeholders = True
        if UPDATE_SMTP_PASSWORD and "WPISZ_PRAWDZ" in NEW_SMTP_PASSWORD:
            print(f"\n⚠️  UWAGA: SMTP Password wciąż jest placeholderem!")
            has_placeholders = True

        if has_placeholders:
            print(f"\n💡 Profil zostanie zaktualizowany, ale nie będzie działać z placeholderami.")

        response = input("\n❓ Zastosować zmiany? [t/N]: ")
        if response.lower() != 't':
            print("\n❌ Anulowano.")
            return 1

        # Zastosuj zmiany
        print(f"\n⏳ Aktualizowanie profilu...")

        if UPDATE_NAME:
            account.name = NEW_NAME
        if UPDATE_INFAKT_API_KEY:
            account.infakt_api_key = NEW_INFAKT_API_KEY  # Automatyczne szyfrowanie
        if UPDATE_EMAIL_FROM:
            account.email_from = NEW_EMAIL_FROM
        if UPDATE_SMTP_SERVER:
            account.smtp_server = NEW_SMTP_SERVER
        if UPDATE_SMTP_PORT:
            account.smtp_port = NEW_SMTP_PORT
        if UPDATE_SMTP_USERNAME:
            account.smtp_username = NEW_SMTP_USERNAME  # Automatyczne szyfrowanie
        if UPDATE_SMTP_PASSWORD:
            account.smtp_password = NEW_SMTP_PASSWORD  # Automatyczne szyfrowanie
        if UPDATE_IS_ACTIVE:
            account.is_active = NEW_IS_ACTIVE

        db.session.commit()

        print(f"\n✅ Profil '{account.name}' został zaktualizowany!")
        print(f"   ID: {account.id}")
        print(f"   Email: {account.email_from}")
        print(f"   Status: {'Aktywny' if account.is_active else 'Nieaktywny'}")

        print("\n" + "=" * 60)
        print("🎉 SUKCES!")
        print("=" * 60)
        print(f"\nKolejne kroki:")
        print(f"1. Uruchom aplikację: flask run")
        print(f"2. Zaloguj się i wybierz profil '{account.name}'")
        print(f"3. Przetestuj synchronizację i wysyłkę emaili")
        print("")

        return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n❌ BŁĄD: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
