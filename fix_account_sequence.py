#!/usr/bin/env python3
"""
Skrypt do naprawienia sekwencji PostgreSQL dla tabeli account.

Problem:
    Gdy migracja wstawia rekordy z jawnie podanym ID (np. id=1 dla Aquatest),
    sekwencja PostgreSQL nie jest automatycznie aktualizowana. To powoduje błąd
    "duplicate key value violates unique constraint" przy próbie dodania kolejnego profilu.

Rozwiązanie:
    Resetuje sekwencję account_id_seq do wartości MAX(id) + 1

Użycie:
    python fix_account_sequence.py
"""

import sys
from InvoiceTracker.models import db
from InvoiceTracker.app import create_app
from sqlalchemy import text


def main():
    print("=" * 70)
    print("🔧 Naprawa sekwencji PostgreSQL dla tabeli 'account'")
    print("=" * 70)

    app = create_app()

    with app.app_context():
        try:
            # Pobierz obecny stan sekwencji
            result = db.session.execute(text("SELECT last_value FROM account_id_seq")).fetchone()
            current_seq_value = result[0] if result else None

            # Pobierz maksymalne ID z tabeli
            result = db.session.execute(text("SELECT MAX(id) FROM account")).fetchone()
            max_id = result[0] if result and result[0] else 0

            print(f"\n📊 Obecny stan:")
            print(f"   Sekwencja account_id_seq: {current_seq_value}")
            print(f"   Maksymalne ID w tabeli:  {max_id}")

            # Sprawdź czy naprawa jest potrzebna
            if current_seq_value is not None and current_seq_value >= max_id:
                print(f"\n✅ Sekwencja jest OK! Nie wymaga naprawy.")
                print(f"   Następny wygenerowany ID będzie: {current_seq_value + 1}")
                return 0

            print(f"\n⚠️  Sekwencja wymaga naprawy!")
            print(f"   Sekwencja ({current_seq_value}) < MAX ID ({max_id})")
            print(f"   To spowoduje błąd 'duplicate key' przy dodawaniu nowego profilu.")

            response = input(f"\n❓ Naprawić sekwencję? [t/N]: ")
            if response.lower() != 't':
                print("\n❌ Anulowano.")
                return 1

            # Napraw sekwencję
            print(f"\n⏳ Resetowanie sekwencji...")
            result = db.session.execute(
                text("SELECT setval('account_id_seq', (SELECT MAX(id) FROM account))")
            )
            new_seq_value = result.fetchone()[0]
            db.session.commit()

            print(f"\n✅ Sekwencja została naprawiona!")
            print(f"   Nowa wartość sekwencji: {new_seq_value}")
            print(f"   Następny wygenerowany ID będzie: {new_seq_value + 1}")

            # Weryfikacja
            result = db.session.execute(text("SELECT last_value FROM account_id_seq")).fetchone()
            verified_value = result[0]

            if verified_value == new_seq_value:
                print(f"\n🎉 Weryfikacja OK - sekwencja działa poprawnie!")
            else:
                print(f"\n⚠️  Weryfikacja nieudana - sekwencja: {verified_value}")
                return 1

            print("\n" + "=" * 70)
            print("✅ SUKCES!")
            print("=" * 70)
            print(f"\nKolejne kroki:")
            print(f"1. Możesz teraz bezpiecznie uruchomić: python add_profile.py")
            print(f"2. Nowy profil zostanie utworzony z ID = {new_seq_value + 1}")
            print("")

            return 0

        except Exception as e:
            print(f"\n❌ BŁĄD podczas naprawy sekwencji: {e}")
            import traceback
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n❌ BŁĄD: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
