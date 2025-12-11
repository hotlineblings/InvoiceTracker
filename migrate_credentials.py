#!/usr/bin/env python3
"""
Migracja credentials z _infakt_api_key_encrypted do provider_settings (JSON).

Ten skrypt migruje dane z starego formatu (pojedyncza kolumna) do nowego formatu
(zaszyfrowany JSON) umożliwiającego obsługę wielu providerów.

UŻYCIE LOKALNE (development):
    1. Upewnij się, że migracja Alembic została wykonana: flask db upgrade
    2. Uruchom: python migrate_credentials.py
    3. Skrypt można uruchomić wielokrotnie - pominie już zmigrowane konta

UŻYCIE Z CLOUD SQL PROXY (produkcja GCP):
    1. Uruchom Cloud SQL Proxy:
       ./cloud_sql_proxy -instances=<PROJECT>:<REGION>:<INSTANCE>=tcp:5432

    2. Ustaw zmienne środowiskowe (lub użyj .env z ustawieniami produkcyjnymi):
       export SQLALCHEMY_DATABASE_URI="postgresql://user:pass@localhost:5432/dbname"
       export ENCRYPTION_KEY="<production_key>"

    3. Uruchom migrację:
       python migrate_credentials.py

ALTERNATYWNIE - Flask CLI (kompatybilne z GCP):
    flask migrate-credentials
    flask migrate-credentials --dry-run

UWAGA: Stara kolumna _infakt_api_key_encrypted NIE jest usuwana - pozostaje jako fallback.
"""
import os
import sys

# Dodaj ścieżkę projektu do PYTHONPATH
sys.path.insert(0, os.path.dirname(__file__))

from InvoiceTracker.app import create_app
from InvoiceTracker.app.extensions import db
from InvoiceTracker.app.models import Account


def migrate():
    """Migruje credentials z starego formatu do nowego JSON."""
    print("=" * 60)
    print("🔄 Migracja credentials do formatu Multi-Provider")
    print("=" * 60)

    app = create_app()

    with app.app_context():
        accounts = Account.query.all()
        print(f"\n📊 Znaleziono {len(accounts)} kont do sprawdzenia.")

        migrated = 0
        skipped = 0
        no_credentials = 0

        for account in accounts:
            print(f"\n📝 Konto: {account.name} (ID: {account.id})")

            # Sprawdź czy już zmigrowane (ma dane w nowym formacie)
            if account._provider_settings_encrypted:
                existing_settings = account.provider_settings
                if existing_settings and existing_settings.get('api_key'):
                    print(f"   ⏭️  Pominięto - już zmigrowane (provider_settings zawiera api_key)")
                    skipped += 1
                    continue

            # Sprawdź czy ma dane w starym formacie
            if not account._infakt_api_key_encrypted:
                print(f"   ⚠️  Brak credentials do migracji")
                no_credentials += 1
                continue

            # Pobierz odszyfrowany klucz ze starej kolumny
            # Użyj bezpośredniego dostępu, nie property (które już ma fallback)
            try:
                cipher = Account._get_cipher()
                api_key = cipher.decrypt(account._infakt_api_key_encrypted).decode()
            except Exception as e:
                print(f"   ❌ Błąd deszyfrowania: {e}")
                continue

            if not api_key:
                print(f"   ⚠️  Pusty klucz API")
                no_credentials += 1
                continue

            # Zapisz w nowym formacie
            account.provider_settings = {'api_key': api_key}
            account.provider_type = 'infakt'
            migrated += 1

            print(f"   ✅ Zmigrowano: api_key (***{api_key[-8:]})")

        # Commit wszystkich zmian
        db.session.commit()

        print("\n" + "=" * 60)
        print("📊 PODSUMOWANIE MIGRACJI")
        print("=" * 60)
        print(f"   ✅ Zmigrowano: {migrated}")
        print(f"   ⏭️  Pominięto (już zmigrowane): {skipped}")
        print(f"   ⚠️  Brak credentials: {no_credentials}")
        print(f"   📊 Razem: {len(accounts)}")

        if migrated > 0:
            print("\n🎉 Migracja zakończona pomyślnie!")
            print("\n💡 Kolejne kroki:")
            print("   1. Uruchom aplikację: python -m InvoiceTracker")
            print("   2. Przetestuj sync dla każdego konta")
        else:
            print("\n✅ Brak kont wymagających migracji.")


if __name__ == '__main__':
    try:
        migrate()
    except Exception as e:
        print(f"\n❌ BŁĄD: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
