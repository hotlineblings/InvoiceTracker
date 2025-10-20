#!/usr/bin/env python3
"""
Skrypt do weryfikacji integralności danych po synchronizacji multi-tenancy.

Sprawdza:
1. Czy są Case bez account_id (NULL)
2. Najnowsze Case - dla którego profilu
3. Ostatnie SyncStatus
4. Potencjalne problemy z danymi
"""

import sys
from datetime import datetime, timedelta
from InvoiceTracker.models import db, Case, SyncStatus, Account
from InvoiceTracker.app import create_app
from sqlalchemy import text


def main():
    print("=" * 80)
    print("🔍 Weryfikacja integralności danych synchronizacji")
    print("=" * 80)

    app = create_app()

    with app.app_context():
        print("\n📊 1. Sprawdzanie Case bez account_id...")
        print("-" * 80)

        # Sprawdź czy są Case z NULL account_id
        result = db.session.execute(
            text("SELECT COUNT(*) FROM \"case\" WHERE account_id IS NULL")
        ).fetchone()
        null_count = result[0] if result else 0

        if null_count > 0:
            print(f"❌ PROBLEM: Znaleziono {null_count} Case z account_id = NULL!")
            print("   To narusza constraint NOT NULL - synchronizacja była błędna.")

            # Pokaż te Case
            null_cases = db.session.execute(
                text("SELECT id, case_number, created_at FROM \"case\" WHERE account_id IS NULL LIMIT 10")
            ).fetchall()
            print("\n   Przykłady (max 10):")
            for case in null_cases:
                print(f"   - ID: {case[0]}, Number: {case[1]}, Created: {case[2]}")
        else:
            print("✅ OK: Wszystkie Case mają przypisany account_id")

        print("\n📊 2. Najnowsze Case (ostatnie 20)...")
        print("-" * 80)

        recent_cases = (
            Case.query
            .order_by(Case.created_at.desc())
            .limit(20)
            .all()
        )

        if not recent_cases:
            print("   Brak Case w bazie")
        else:
            print(f"{'ID':<8} | {'Case Number':<20} | {'Account ID':<12} | {'Profil':<20} | {'Created At':<20}")
            print("-" * 80)

            accounts_map = {acc.id: acc.name for acc in Account.query.all()}

            for case in recent_cases:
                account_name = accounts_map.get(case.account_id, "UNKNOWN")
                created_str = case.created_at.strftime('%Y-%m-%d %H:%M:%S') if case.created_at else 'N/A'
                print(f"{case.id:<8} | {case.case_number:<20} | {case.account_id:<12} | {account_name:<20} | {created_str:<20}")

        print("\n📊 3. Case utworzone w ciągu ostatnich 24h...")
        print("-" * 80)

        yesterday = datetime.utcnow() - timedelta(hours=24)
        recent_count_by_account = db.session.execute(
            text("""
                SELECT account_id, COUNT(*) as count
                FROM "case"
                WHERE created_at >= :since
                GROUP BY account_id
                ORDER BY account_id
            """),
            {"since": yesterday}
        ).fetchall()

        if not recent_count_by_account:
            print("   Brak nowych Case w ciągu ostatnich 24h")
        else:
            accounts_map = {acc.id: acc.name for acc in Account.query.all()}
            print(f"{'Account ID':<12} | {'Profil':<25} | {'Liczba nowych Case':<20}")
            print("-" * 80)
            for row in recent_count_by_account:
                acc_id = row[0]
                count = row[1]
                acc_name = accounts_map.get(acc_id, "UNKNOWN")
                print(f"{acc_id:<12} | {acc_name:<25} | {count:<20}")

        print("\n📊 4. Ostatnie synchronizacje (SyncStatus)...")
        print("-" * 80)

        recent_syncs = (
            SyncStatus.query
            .order_by(SyncStatus.timestamp.desc())
            .limit(10)
            .all()
        )

        if not recent_syncs:
            print("   Brak rekordów synchronizacji")
        else:
            print(f"{'ID':<6} | {'Type':<8} | {'Processed':<10} | {'New':<6} | {'Updated':<8} | {'Closed':<7} | {'Timestamp':<20}")
            print("-" * 80)
            for sync in recent_syncs:
                ts = sync.timestamp.strftime('%Y-%m-%d %H:%M:%S') if sync.timestamp else 'N/A'
                print(f"{sync.id:<6} | {sync.sync_type:<8} | {sync.processed:<10} | {sync.new_cases or 0:<6} | {sync.updated_cases or 0:<8} | {sync.closed_cases or 0:<7} | {ts:<20}")

        print("\n📊 5. Statystyki per-profil...")
        print("-" * 80)

        accounts = Account.query.order_by(Account.id).all()

        print(f"{'ID':<5} | {'Profil':<25} | {'Aktywne':<10} | {'Zamknięte':<10} | {'Razem':<10}")
        print("-" * 80)

        for account in accounts:
            active_count = Case.query.filter_by(account_id=account.id, status='active').count()
            closed_count = Case.query.filter(
                Case.account_id == account.id,
                Case.status != 'active'
            ).count()
            total_count = active_count + closed_count

            print(f"{account.id:<5} | {account.name:<25} | {active_count:<10} | {closed_count:<10} | {total_count:<10}")

        print("\n" + "=" * 80)

        # Podsumowanie
        if null_count > 0:
            print("⚠️  WYKRYTO PROBLEMY!")
            print(f"   - {null_count} Case bez account_id")
            print("\n🔧 Zalecane działania:")
            print("   1. Usuń błędne Case: DELETE FROM \"case\" WHERE account_id IS NULL")
            print("   2. Napraw kod synchronizacji przed następnym wywołaniem")
        else:
            print("✅ Integralność danych OK")
            print("\n💡 Uwaga: SyncStatus nie ma jeszcze pola account_id")
            print("   Wszystkie synchronizacje są globalne - wymaga naprawy.")

        print("=" * 80)
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
