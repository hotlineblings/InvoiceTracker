#!/usr/bin/env python3
"""
Skrypt do wyświetlania wszystkich profili/kont w systemie multi-tenancy.

Użycie:
    python list_profiles.py

Pokazuje:
    - ID profilu
    - Nazwę
    - Email (email_from)
    - Status aktywności
    - Liczbę spraw przypisanych do profilu

NIE pokazuje wrażliwych danych (API keys, hasła SMTP).
"""

import sys
from InvoiceTracker.models import db, Account, Case
from InvoiceTracker.app import create_app


def main():
    print("=" * 80)
    print("📋 Lista profili w InvoiceTracker")
    print("=" * 80)

    app = create_app()

    with app.app_context():
        # Pobierz wszystkie profile
        accounts = Account.query.order_by(Account.id).all()

        if not accounts:
            print("\n⚠️  Brak profili w bazie danych!")
            print("   Uruchom migrację: flask db upgrade")
            return 1

        print(f"\nZnaleziono {len(accounts)} profil(i):\n")

        # Nagłówek tabeli
        print(f"{'ID':<5} | {'Nazwa':<25} | {'Email From':<30} | {'Sprawy':<8} | {'Status':<10}")
        print("-" * 80)

        # Wyświetl każdy profil
        for account in accounts:
            # Policz sprawy przypisane do tego profilu
            active_cases = Case.query.filter_by(account_id=account.id, status='active').count()
            closed_cases = Case.query.filter(
                Case.account_id == account.id,
                Case.status != 'active'
            ).count()
            total_cases = active_cases + closed_cases

            # Status
            status_icon = "✓" if account.is_active else "✗"
            status_text = "Aktywny" if account.is_active else "Nieaktywny"
            status = f"{status_icon} {status_text}"

            # Formatuj cases
            cases_str = f"{active_cases}A/{closed_cases}Z" if total_cases > 0 else "0"

            # Wyświetl wiersz
            print(f"{account.id:<5} | {account.name:<25} | {account.email_from:<30} | {cases_str:<8} | {status:<10}")

        print("-" * 80)

        # Szczegóły dla każdego profilu (opcjonalnie)
        print("\n📊 Szczegóły profili:\n")

        for account in accounts:
            print(f"ID: {account.id} - {account.name}")
            print(f"   Email From: {account.email_from}")
            print(f"   SMTP Server: {account.smtp_server}:{account.smtp_port}")
            print(f"   SMTP Username: {account.smtp_username[:3]}***@{account.smtp_username.split('@')[1] if '@' in account.smtp_username else '***'}")
            print(f"   InFakt API Key: {account.infakt_api_key[:8]}..." if account.infakt_api_key else "   InFakt API Key: [BRAK]")
            print(f"   Status: {'🟢 Aktywny' if account.is_active else '🔴 Nieaktywny'}")
            print(f"   Utworzony: {account.created_at.strftime('%Y-%m-%d %H:%M') if account.created_at else 'N/A'}")

            # Statystyki spraw
            active_cases = Case.query.filter_by(account_id=account.id, status='active').count()
            closed_paid = Case.query.filter_by(account_id=account.id, status='closed_oplacone').count()
            closed_unpaid = Case.query.filter_by(account_id=account.id, status='closed_nieoplacone').count()

            print(f"   Sprawy:")
            print(f"      - Aktywne: {active_cases}")
            print(f"      - Zamknięte opłacone: {closed_paid}")
            print(f"      - Zamknięte nieopłacone: {closed_unpaid}")
            print("")

        print("=" * 80)
        print("\n💡 Użyj tych ID w skryptach:")
        print("   - edit_profile.py (edycja profilu)")
        print("   - Parametr PROFILE_ID w skryptach")
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
