#!/usr/bin/env python3
"""
Skrypt do dodawania nowego profilu/konta do systemu multi-tenancy.

Użycie:
    1. Edytuj dane poniżej (nazwa, email, API key, SMTP)
    2. Uruchom: python add_profile.py
    3. Profil zostanie utworzony z automatycznym szyfrowaniem wrażliwych danych
"""

import sys
from InvoiceTracker.models import db, Account, NotificationSettings
from InvoiceTracker.app import create_app

# ========================================
# EDYTUJ DANE NOWEGO PROFILU TUTAJ:
# ========================================

PROFILE_NAME = "Pozytron Szkolenia"

# InFakt API
INFAKT_API_KEY = "WPISZ_PRAWDZIWY_KLUCZ_POZYTRON"  # <-- ZMIEŃ gdy dostaniesz klucz

# Email configuration
EMAIL_FROM = "kontakt@pozytron.pl"  # <-- ZMIEŃ na prawdziwy email

# SMTP configuration
SMTP_SERVER = "sgz.nazwa.pl"  # Możesz zmienić jeśli Pozytron ma inny serwer
SMTP_PORT = 587
SMTP_USERNAME = "kontakt@pozytron.pl"  # <-- ZMIEŃ na prawdziwy username
SMTP_PASSWORD = "WPISZ_PRAWDZIWE_HASLO_SMTP"  # <-- ZMIEŃ gdy dostaniesz hasło

IS_ACTIVE = True  # Czy profil ma być aktywny od razu?

# ========================================
# KOD SKRYPTU - NIE EDYTUJ PONIŻEJ
# ========================================

def main():
    print("=" * 60)
    print("🚀 Dodawanie nowego profilu do InvoiceTracker")
    print("=" * 60)

    app = create_app()

    with app.app_context():
        # Sprawdź czy profil już istnieje
        existing = Account.query.filter_by(name=PROFILE_NAME).first()
        if existing:
            print(f"\n⚠️  BŁĄD: Profil '{existing.name}' już istnieje!")
            print(f"    ID: {existing.id}")
            print(f"    Email: {existing.email_from}")
            print(f"\n💡 Użyj edit_profile.py aby edytować istniejący profil.")
            return 1

        # Walidacja - sprawdź czy dane zostały zmienione
        if "WPISZ_PRAWDZ" in INFAKT_API_KEY or "WPISZ_PRAWDZ" in SMTP_PASSWORD:
            print(f"\n⚠️  UWAGA: Używasz placeholderów!")
            print(f"    Profil zostanie utworzony, ale nie będzie działać dopóki nie uzupełnisz danych.")
            print(f"\n💡 Możesz edytować dane później używając edit_profile.py")
            response = input("\n    Kontynuować? [t/N]: ")
            if response.lower() != 't':
                print("\n❌ Anulowano.")
                return 1

        print(f"\n📝 Tworzenie profilu: {PROFILE_NAME}")
        print(f"   Email from: {EMAIL_FROM}")
        print(f"   SMTP server: {SMTP_SERVER}:{SMTP_PORT}")

        # Utwórz nowy profil
        new_account = Account(
            name=PROFILE_NAME,
            smtp_server=SMTP_SERVER,
            smtp_port=SMTP_PORT,
            is_active=IS_ACTIVE
        )

        # Ustaw zaszyfrowane wartości (automatyczne szyfrowanie przez property settery)
        new_account.infakt_api_key = INFAKT_API_KEY
        new_account.smtp_username = SMTP_USERNAME
        new_account.smtp_password = SMTP_PASSWORD
        new_account.email_from = EMAIL_FROM

        db.session.add(new_account)
        db.session.commit()

        print(f"\n✅ Utworzono profil: {new_account.name}")
        print(f"   ID: {new_account.id}")
        print(f"   Status: {'Aktywny' if new_account.is_active else 'Nieaktywny'}")

        # Skopiuj ustawienia powiadomień z profilu Aquatest
        print(f"\n📋 Kopiowanie ustawień powiadomień...")
        aquatest = Account.query.filter_by(name='Aquatest').first()

        if aquatest:
            aquatest_settings = NotificationSettings.query.filter_by(account_id=aquatest.id).all()
            copied_count = 0

            for setting in aquatest_settings:
                new_setting = NotificationSettings(
                    account_id=new_account.id,
                    stage_name=setting.stage_name,
                    offset_days=setting.offset_days
                )
                db.session.add(new_setting)
                copied_count += 1

            db.session.commit()
            print(f"✅ Skopiowano {copied_count} ustawień powiadomień z profilu 'Aquatest'")
        else:
            print("⚠️  Nie znaleziono profilu 'Aquatest' - ustawienia powiadomień NIE zostały skopiowane")
            print("   Będziesz musiał je skonfigurować ręcznie w /shipping_settings")

        print("\n" + "=" * 60)
        print("🎉 SUKCES! Profil został utworzony.")
        print("=" * 60)
        print(f"\nKolejne kroki:")
        print(f"1. Uruchom aplikację: flask run")
        print(f"2. Zaloguj się i wybierz profil '{PROFILE_NAME}'")
        if "WPISZ_PRAWDZ" in INFAKT_API_KEY or "WPISZ_PRAWDZ" in SMTP_PASSWORD:
            print(f"3. ⚠️  WAŻNE: Uzupełnij prawdziwe dane używając edit_profile.py")
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
