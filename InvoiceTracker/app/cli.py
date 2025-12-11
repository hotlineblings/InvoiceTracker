"""
Komendy CLI Flask.
Zarządzanie bazą danych, synchronizacją i diagnostyka.
"""
import os
import click
from datetime import datetime

from .extensions import db
from .models import Account, Case, Invoice, NotificationLog, SyncStatus, NotificationSettings, AccountScheduleSettings, User


def register_cli(app):
    """
    Rejestruje wszystkie komendy CLI w aplikacji Flask.

    Args:
        app: Instancja Flask application
    """

    @app.cli.command('archive-active-cases')
    def archive_active_cases_cli():
        """Archiwizuje wszystkie aktywne Cases dla Aquatest jako archived_before_reset"""
        print("=" * 80)
        print("ARCHIWIZACJA AKTYWNYCH SPRAW - Aquatest")
        print("=" * 80)

        # Pobierz konto Aquatest
        account = Account.query.filter_by(name='Aquatest').first()
        if not account:
            print("BLAD: Nie znaleziono konta 'Aquatest'")
            return

        print(f"\nZnaleziono konto: {account.name} (ID: {account.id})")

        # Znajdz wszystkie aktywne Cases
        active_cases = Case.query.filter_by(
            account_id=account.id,
            status='active'
        ).all()

        print(f"\nZnaleziono {len(active_cases)} aktywnych spraw do archiwizacji")

        if len(active_cases) == 0:
            print("\nBrak aktywnych spraw do archiwizacji")
            print("=" * 80)
            return

        # Potwierdz operacje
        print("\nUWAGA: Operacja zmieni status wszystkich aktywnych spraw na 'archived_before_reset'")
        confirm = input("Kontynuowac? (tak/nie): ").strip().lower()

        if confirm != 'tak':
            print("\nOperacja anulowana przez uzytkownika")
            print("=" * 80)
            return

        # Archiwizuj Cases
        archived_count = 0
        for case in active_cases:
            case.status = 'archived_before_reset'
            db.session.add(case)

            # Dodaj wpis do NotificationLog
            log_entry = NotificationLog(
                account_id=account.id,
                client_id=case.client_id,
                invoice_number=case.case_number,
                email_to="N/A",
                subject="Archiwizacja przed resetem",
                body=f"Sprawa {case.case_number} zarchiwizowana przed resetem systemu synchronizacji.",
                stage="Archiwizacja",
                mode="System",
                sent_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            archived_count += 1

        db.session.commit()

        print(f"\nZarchiwizowano {archived_count} spraw")
        print(f"   Nowy status: 'archived_before_reset'")
        print("\n" + "=" * 80)
        print("Archiwizacja zakonczona pomyslnie")
        print("=" * 80)

    @app.cli.command('test-sync-days')
    @click.argument('days', type=int)
    def test_sync_days_cli(days):
        """Test synchronizacji z invoice_fetch_days_before = <days>"""
        from .services.update_db import sync_new_invoices

        print("=" * 80)
        print(f"TEST SYNCHRONIZACJI z invoice_fetch_days_before = {days}")
        print("=" * 80)

        # Pobierz konto Aquatest
        account = Account.query.filter_by(name='Aquatest').first()
        if not account:
            print("BLAD: Nie znaleziono konta 'Aquatest'")
            return

        print(f"\nKonto: {account.name} (ID: {account.id})")

        # Pobierz ustawienia
        settings = AccountScheduleSettings.get_for_account(account.id)
        original_days = settings.invoice_fetch_days_before

        print(f"\nAktualne ustawienie: invoice_fetch_days_before = {original_days} dni")
        print(f"Testowe ustawienie: invoice_fetch_days_before = {days} dni")

        # Tymczasowo zmien ustawienie
        settings.invoice_fetch_days_before = days
        db.session.add(settings)
        db.session.commit()

        print(f"\nUruchamiam synchronizacje...")
        print("-" * 80)

        try:
            # Uruchom synchronizacje
            processed, new_cases, api_calls, duration = sync_new_invoices(account.id)

            print("\n" + "=" * 80)
            print("WYNIKI SYNCHRONIZACJI:")
            print("=" * 80)
            print(f"   Czas trwania: {duration:.2f}s")
            print(f"   Wywolan API: {api_calls}")
            print(f"   Przetworzonych faktur: {processed}")
            print(f"   Nowych spraw (Cases): {new_cases}")

        except Exception as e:
            print(f"\nBLAD podczas synchronizacji: {e}")
            import traceback
            print(traceback.format_exc())

        finally:
            # Przywroc oryginalne ustawienie
            settings.invoice_fetch_days_before = original_days
            db.session.add(settings)
            db.session.commit()

            print(f"\nPrzywrocono oryginalne ustawienie: invoice_fetch_days_before = {original_days} dni")

        print("\n" + "=" * 80)
        print("Test zakonczony")
        print("=" * 80)

    @app.cli.command('verify-sync-state')
    def verify_sync_state_cli():
        """Weryfikuje stan synchronizacji dla Aquatest"""
        print("=" * 80)
        print("WERYFIKACJA STANU SYNCHRONIZACJI - Aquatest")
        print("=" * 80)

        # Pobierz konto Aquatest
        account = Account.query.filter_by(name='Aquatest').first()
        if not account:
            print("BLAD: Nie znaleziono konta 'Aquatest'")
            return

        print(f"\nKonto: {account.name} (ID: {account.id})")

        # === AKTYWNE CASES ===
        print("\n" + "-" * 80)
        print("AKTYWNE SPRAWY (Cases):")
        print("-" * 80)

        active_cases = Case.query.filter_by(
            account_id=account.id,
            status='active'
        ).all()

        print(f"   Liczba aktywnych spraw: {len(active_cases)}")

        if active_cases:
            print(f"\n   Pierwsze 5 aktywnych spraw:")
            for case in active_cases[:5]:
                print(f"      - {case.case_number} (client: {case.client_company_name})")
            if len(active_cases) > 5:
                print(f"      ... i {len(active_cases) - 5} wiecej")

        # === ORPHANED INVOICES ===
        print("\n" + "-" * 80)
        print("ORPHANED INVOICES (faktury bez Case):")
        print("-" * 80)

        # Invoice ma teraz bezpośredni account_id - filtrujemy po profilu
        orphaned = Invoice.query.filter(
            Invoice.account_id == account.id,
            Invoice.case_id == None,
            Invoice.left_to_pay > 0,
            Invoice.status.in_(['sent', 'printed'])
        ).all()

        print(f"   Liczba orphaned invoices dla profilu {account.name}: {len(orphaned)}")

        if orphaned:
            print(f"\n   Szczegoly:")
            for inv in orphaned:
                print(f"      - {inv.invoice_number}: {inv.left_to_pay/100.0:.2f} PLN (termin: {inv.payment_due_date})")

        # === OSTATNIE SYNCHRONIZACJE ===
        print("\n" + "-" * 80)
        print("OSTATNIE 3 SYNCHRONIZACJE:")
        print("-" * 80)

        syncs = SyncStatus.query.filter_by(account_id=account.id)\
            .order_by(SyncStatus.timestamp.desc())\
            .limit(3)\
            .all()

        if not syncs:
            print("   Brak rekordow synchronizacji")
        else:
            for idx, sync in enumerate(syncs, 1):
                print(f"\n   #{idx} - {sync.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                print(f"      Typ: {sync.sync_type}")
                print(f"      Przetworzonych: {sync.processed}")
                print(f"      Nowych spraw: {sync.new_cases}")
                print(f"      API calls: {sync.api_calls}")
                print(f"      Czas: {sync.duration:.2f}s")

        # === PODSUMOWANIE ===
        print("\n" + "=" * 80)
        print("PODSUMOWANIE:")
        print("=" * 80)
        print(f"   Aktywne sprawy: {len(active_cases)}")
        print(f"   Orphaned invoices: {len(orphaned)}")
        print(f"   Ostatnich synchronizacji: {len(syncs)}")
        print("\n" + "=" * 80)

    @app.cli.command('sync-smtp-config')
    def sync_smtp_config_cli():
        """
        Synchronizuje konfiguracje SMTP z .env do bazy danych.
        Aktualizuje ustawienia SMTP dla profili Aquatest i Pozytron Szkolenia
        na podstawie zmiennych srodowiskowych z prefiksami.

        CRITICAL: Ten mechanizm zapewnia ze kazdy profil uzywa TYLKO swoich
        dedykowanych ustawien SMTP bez fallback do globalnych.
        """
        print("=" * 80)
        print("SYNCHRONIZACJA KONFIGURACJI SMTP z .env -> Database")
        print("=" * 80)

        # Definicja mapowania: nazwa profilu -> prefiks w .env
        PROFILE_CONFIGS = {
            'Aquatest': 'AQUATEST',
            'Pozytron Szkolenia': 'POZYTRON'
        }

        updated_count = 0
        errors = []

        for account_name, env_prefix in PROFILE_CONFIGS.items():
            print(f"\n{'-' * 80}")
            print(f"Profil: {account_name}")
            print(f"{'-' * 80}")

            # Pobierz konto z bazy
            account = Account.query.filter_by(name=account_name).first()
            if not account:
                error_msg = f"BLAD: Nie znaleziono konta '{account_name}' w bazie"
                print(error_msg)
                errors.append(error_msg)
                continue

            print(f"Znaleziono konto: {account.name} (ID: {account.id})")

            # Pobierz zmienne z .env
            smtp_server = os.getenv(f'{env_prefix}_SMTP_SERVER')
            smtp_port = os.getenv(f'{env_prefix}_SMTP_PORT')
            smtp_username = os.getenv(f'{env_prefix}_SMTP_USERNAME')
            smtp_password = os.getenv(f'{env_prefix}_SMTP_PASSWORD')
            email_from = os.getenv(f'{env_prefix}_EMAIL_FROM')

            # Walidacja - sprawdz czy wszystkie wymagane zmienne sa zdefiniowane
            missing_vars = []
            if not smtp_server:
                missing_vars.append(f'{env_prefix}_SMTP_SERVER')
            if not smtp_port:
                missing_vars.append(f'{env_prefix}_SMTP_PORT')
            if not smtp_username:
                missing_vars.append(f'{env_prefix}_SMTP_USERNAME')
            if not smtp_password:
                missing_vars.append(f'{env_prefix}_SMTP_PASSWORD')
            if not email_from:
                missing_vars.append(f'{env_prefix}_EMAIL_FROM')

            if missing_vars:
                error_msg = f"BLAD: Brakujace zmienne srodowiskowe: {', '.join(missing_vars)}"
                print(error_msg)
                errors.append(error_msg)
                continue

            # Wyswietl zmiany
            print(f"\nZmiany do zastosowania:")
            print(f"   - SMTP Server:   {smtp_server}")
            print(f"   - SMTP Port:     {smtp_port}")
            print(f"   - SMTP Username: {smtp_username}")
            print(f"   - SMTP Password: {'*' * len(smtp_password)} (zaszyfrowane)")
            print(f"   - Email From:    {email_from}")

            # Aktualizuj ustawienia
            try:
                account.smtp_server = smtp_server
                account.smtp_port = int(smtp_port)
                account.smtp_username = smtp_username  # Automatycznie szyfrowane przez setter
                account.smtp_password = smtp_password  # Automatycznie szyfrowane przez setter
                account.email_from = email_from

                db.session.add(account)
                db.session.commit()

                print(f"\nPomyslnie zaktualizowano konfiguracje SMTP dla {account_name}")
                updated_count += 1

            except Exception as e:
                db.session.rollback()
                error_msg = f"BLAD podczas aktualizacji {account_name}: {str(e)}"
                print(error_msg)
                errors.append(error_msg)

        # Podsumowanie
        print("\n" + "=" * 80)
        print("PODSUMOWANIE:")
        print("=" * 80)
        print(f"   Zaktualizowane profile: {updated_count}/{len(PROFILE_CONFIGS)}")

        if errors:
            print(f"\n   Bledy ({len(errors)}):")
            for error in errors:
                print(f"      {error}")
        else:
            print("\n   Synchronizacja przebiegla bez bledow!")
            print("\n   UWAGA: Kazdy profil uzywa TYLKO swoich dedykowanych ustawien SMTP.")
            print("   Brak mechanizmu fallback do globalnych ustawien.")

        print("\n" + "=" * 80)

    @app.cli.command('verify-notification-settings')
    def verify_notification_settings_cli():
        """
        Weryfikuje i naprawia ustawienia NotificationSettings dla wszystkich profili.
        Upewnia sie ze oba profile (Aquatest i Pozytron) maja identyczne 5 ustawien.
        """
        print("=" * 80)
        print("WERYFIKACJA I NAPRAWA NOTIFICATIONSETTINGS")
        print("=" * 80)

        # Pobierz wszystkie aktywne konta
        accounts = Account.query.filter_by(is_active=True).all()

        if not accounts:
            print("\nBrak aktywnych kont w bazie")
            return

        print(f"\nZnaleziono {len(accounts)} aktywnych kont")

        # Sprawdz kazde konto
        for account in accounts:
            print(f"\n{'-' * 80}")
            print(f"Profil: {account.name} (ID: {account.id})")
            print(f"{'-' * 80}")

            # Sprawdz istniejace ustawienia
            existing_settings = NotificationSettings.query.filter_by(account_id=account.id).all()
            print(f"\nIstniejace ustawienia: {len(existing_settings)}")

            if existing_settings:
                for setting in existing_settings:
                    print(f"  - \"{setting.stage_name}\": {setting.offset_days} dni (ID: {setting.id})")

            # Zainicjalizuj domyslne ustawienia jesli brak
            if len(existing_settings) < 5:
                print(f"\nWykryto {len(existing_settings)}/5 ustawien - inicjalizacja brakujacych...")
                NotificationSettings.initialize_default_settings(account.id)

                # Pobierz ponownie po inicjalizacji
                updated_settings = NotificationSettings.query.filter_by(account_id=account.id).all()
                print(f"Po inicjalizacji: {len(updated_settings)}/5 ustawien")

                for setting in updated_settings:
                    print(f"  - \"{setting.stage_name}\": {setting.offset_days} dni")
            else:
                print("Wszystkie 5 ustawien obecne")

        # Podsumowanie
        print("\n" + "=" * 80)
        print("PODSUMOWANIE:")
        print("=" * 80)

        for account in accounts:
            settings_count = NotificationSettings.query.filter_by(account_id=account.id).count()
            status = "OK" if settings_count == 5 else "UWAGA"
            print(f"  [{status}] {account.name}: {settings_count}/5 ustawien")

        print("\n" + "=" * 80)
        print("Weryfikacja zakonczona")
        print("=" * 80)

    @app.cli.command('normalize-all-notification-settings')
    def normalize_all_notification_settings_cli():
        """
        Normalizuje NotificationSettings dla WSZYSTKICH aktywnych profili.

        SELF-HEALING SYSTEM:
        - Usuwa stare/niepoprawne wpisy (np. stage_1, stage_2, stage_3, stage_4, stage_5)
        - Dodaje brakujace wpisy z domyslnymi wartosciami
        - Zapewnia ze kazdy profil ma dokladnie 5 poprawnych wpisow z CANONICAL_NOTIFICATION_STAGES

        Uzycie:
            flask normalize-all-notification-settings

        Na produkcji (Cloud Shell):
            gcloud app instances ssh
            cd /srv
            flask normalize-all-notification-settings
        """
        print("=" * 80)
        print("NORMALIZACJA NOTIFICATION SETTINGS - WSZYSTKIE PROFILE")
        print("=" * 80)

        # Pobierz wszystkie aktywne konta
        accounts = Account.query.filter_by(is_active=True).all()

        if not accounts:
            print("\nBrak aktywnych kont w bazie")
            return

        print(f"\nZnaleziono {len(accounts)} aktywnych profili")

        # Normalizuj kazdy profil
        for account in accounts:
            print(f"\n{'-' * 80}")
            print(f"Profil: {account.name} (ID: {account.id})")
            print(f"{'-' * 80}")

            try:
                # Wywolaj normalizacje (automatycznie czysci i dodaje)
                normalized_settings = NotificationSettings.normalize_for_account(account.id)

                print(f"Znormalizowano pomyslnie - {len(normalized_settings)}/5 ustawien:")
                for stage_name, offset_days in normalized_settings.items():
                    # Wyswietl skrocona nazwe (pierwsze 60 znakow)
                    short_name = stage_name[:60] + "..." if len(stage_name) > 60 else stage_name
                    print(f"  - {short_name}: {offset_days} dni")

            except Exception as e:
                print(f"BLAD podczas normalizacji {account.name}: {e}")
                import traceback
                print(traceback.format_exc())

        # Podsumowanie koncowe
        print("\n" + "=" * 80)
        print("PODSUMOWANIE KONCOWE:")
        print("=" * 80)

        for account in accounts:
            settings_count = NotificationSettings.query.filter_by(account_id=account.id).count()
            status = "OK" if settings_count == 5 else "UWAGA"
            print(f"  [{status}] {account.name}: {settings_count}/5 ustawien")

        print("\n" + "=" * 80)
        print("Normalizacja zakonczona")
        print("=" * 80)
        print("\nTeraz kazdy profil ma IDENTYCZNA strukture 5 etapow powiadomien")
        print("Panel ustawien dla wszystkich profili bedzie wygladal tak samo")

    # ==========================================================================
    # USER MANAGEMENT COMMANDS (Flask-Login integration)
    # ==========================================================================

    @app.cli.command('create-admin')
    @click.option('--email', prompt='Admin email', help='Email address for admin user')
    @click.option('--password', prompt='Admin password', hide_input=True,
                  confirmation_prompt=True, help='Password for admin user')
    @click.option('--grant-all-accounts', is_flag=True, default=True,
                  help='Grant access to all existing active accounts')
    def create_admin_cli(email, password, grant_all_accounts):
        """
        Creates admin user for the system.

        Usage:
            flask create-admin
            flask create-admin --email admin@example.com --password secret
            flask create-admin --no-grant-all-accounts
        """
        print("=" * 80)
        print("TWORZENIE UZYTKOWNIKA")
        print("=" * 80)

        # Check if user already exists
        existing = User.query.filter_by(email=email).first()
        if existing:
            print(f"\nBLAD: Uzytkownik z email '{email}' juz istnieje (ID: {existing.id})")
            return

        # Create user
        user = User(email=email)
        user.password = password  # Automatically hashed via setter
        user.is_active = True

        db.session.add(user)

        # Grant access to all accounts if requested
        if grant_all_accounts:
            accounts = Account.query.filter_by(is_active=True).all()
            for account in accounts:
                user.accounts.append(account)
            print(f"\nPrzyznano dostep do {len(accounts)} profili:")
            for account in accounts:
                print(f"   - {account.name}")
        else:
            print("\nNie przyznano dostepu do zadnych profili.")
            print("Uzyj 'flask grant-account-access' aby przyznac dostep.")

        db.session.commit()

        print(f"\nUtworzono uzytkownika: {email}")
        print(f"   ID: {user.id}")
        print(f"   Aktywny: {user.is_active}")
        print(f"   Liczba profili: {user.accounts.count()}")
        print("\n" + "=" * 80)

    @app.cli.command('grant-account-access')
    @click.argument('user_email')
    @click.argument('account_name')
    def grant_account_access_cli(user_email, account_name):
        """
        Grants a user access to a specific account.

        Usage:
            flask grant-account-access user@example.com "Aquatest"
        """
        user = User.query.filter_by(email=user_email).first()
        if not user:
            print(f"BLAD: Uzytkownik '{user_email}' nie istnieje")
            return

        account = Account.query.filter_by(name=account_name).first()
        if not account:
            print(f"BLAD: Konto '{account_name}' nie istnieje")
            print("\nDostepne konta:")
            for acc in Account.query.all():
                print(f"   - {acc.name}")
            return

        if user.has_access_to_account(account.id):
            print(f"Uzytkownik '{user_email}' juz ma dostep do '{account_name}'")
            return

        user.accounts.append(account)
        db.session.commit()

        print(f"Przyznano uzytkownikowi '{user_email}' dostep do '{account_name}'")

    @app.cli.command('revoke-account-access')
    @click.argument('user_email')
    @click.argument('account_name')
    def revoke_account_access_cli(user_email, account_name):
        """
        Revokes user's access to a specific account.

        Usage:
            flask revoke-account-access user@example.com "Aquatest"
        """
        user = User.query.filter_by(email=user_email).first()
        if not user:
            print(f"BLAD: Uzytkownik '{user_email}' nie istnieje")
            return

        account = Account.query.filter_by(name=account_name).first()
        if not account:
            print(f"BLAD: Konto '{account_name}' nie istnieje")
            return

        if not user.has_access_to_account(account.id):
            print(f"Uzytkownik '{user_email}' nie ma dostepu do '{account_name}'")
            return

        user.accounts.remove(account)
        db.session.commit()

        print(f"Odebrano uzytkownikowi '{user_email}' dostep do '{account_name}'")

    @app.cli.command('list-users')
    def list_users_cli():
        """Lists all users and their account access."""
        users = User.query.all()

        if not users:
            print("Brak uzytkownikow w systemie")
            print("\nUzyj 'flask create-admin' aby utworzyc pierwszego uzytkownika")
            return

        print("=" * 80)
        print("LISTA UZYTKOWNIKOW")
        print("=" * 80)

        for user in users:
            accounts = user.get_accessible_accounts()
            status = "Aktywny" if user.is_active else "Nieaktywny"
            last_login = user.last_login_at.strftime('%Y-%m-%d %H:%M') if user.last_login_at else 'nigdy'

            print(f"\n{user.email} (ID: {user.id}) - {status}")
            print(f"   Utworzony: {user.created_at.strftime('%Y-%m-%d %H:%M')}")
            print(f"   Ostatnie logowanie: {last_login}")
            print(f"   Dostepne profile ({len(accounts)}):")
            if accounts:
                for account in accounts:
                    print(f"      - {account.name}")
            else:
                print("      (brak)")

        print("\n" + "=" * 80)

    @app.cli.command('deactivate-user')
    @click.argument('user_email')
    def deactivate_user_cli(user_email):
        """
        Deactivates a user (prevents login).

        Usage:
            flask deactivate-user user@example.com
        """
        user = User.query.filter_by(email=user_email).first()
        if not user:
            print(f"BLAD: Uzytkownik '{user_email}' nie istnieje")
            return

        if not user.is_active:
            print(f"Uzytkownik '{user_email}' jest juz dezaktywowany")
            return

        user.is_active = False
        db.session.commit()

        print(f"Dezaktywowano uzytkownika '{user_email}'")
        print("Uzytkownik nie bedzie mogl sie zalogowac")

    @app.cli.command('activate-user')
    @click.argument('user_email')
    def activate_user_cli(user_email):
        """
        Activates a previously deactivated user.

        Usage:
            flask activate-user user@example.com
        """
        user = User.query.filter_by(email=user_email).first()
        if not user:
            print(f"BLAD: Uzytkownik '{user_email}' nie istnieje")
            return

        if user.is_active:
            print(f"Uzytkownik '{user_email}' jest juz aktywny")
            return

        user.is_active = True
        db.session.commit()

        print(f"Aktywowano uzytkownika '{user_email}'")

    # ==========================================================================
    # MULTI-PROVIDER MIGRATION COMMANDS
    # ==========================================================================

    @app.cli.command('migrate-credentials')
    @click.option('--dry-run', is_flag=True, default=False,
                  help='Preview changes without committing to database')
    def migrate_credentials_cli(dry_run):
        """
        Migruje credentials z _infakt_api_key_encrypted do provider_settings (JSON).

        Ten skrypt migruje dane z starego formatu (pojedyncza kolumna) do nowego formatu
        (zaszyfrowany JSON) umożliwiającego obsługę wielu providerów.

        Użycie lokalne:
            flask migrate-credentials
            flask migrate-credentials --dry-run

        Na GCP App Engine (Cloud Shell):
            gcloud app instances ssh <instance> --service default
            cd /srv
            flask migrate-credentials

        Skrypt jest idempotentny - można uruchomić wielokrotnie, pominie już zmigrowane konta.
        """
        print("=" * 60)
        print("MIGRACJA CREDENTIALS DO FORMATU MULTI-PROVIDER")
        if dry_run:
            print("MODE: DRY RUN (zmiany NIE zostana zapisane)")
        print("=" * 60)

        accounts = Account.query.all()
        print(f"\nZnaleziono {len(accounts)} kont do sprawdzenia.")

        migrated = 0
        skipped = 0
        no_credentials = 0
        errors = []

        for account in accounts:
            print(f"\nKonto: {account.name} (ID: {account.id})")

            # Sprawdź czy już zmigrowane (ma dane w nowym formacie)
            if account._provider_settings_encrypted:
                try:
                    existing_settings = account.provider_settings
                    if existing_settings and existing_settings.get('api_key'):
                        print(f"   Pominieto - juz zmigrowane (provider_settings zawiera api_key)")
                        skipped += 1
                        continue
                except Exception as e:
                    print(f"   BLAD deszyfrowania istniejacych provider_settings: {e}")
                    errors.append(f"{account.name}: {e}")
                    continue

            # Sprawdź czy ma dane w starym formacie
            if not account._infakt_api_key_encrypted:
                print(f"   Brak credentials do migracji")
                no_credentials += 1
                continue

            # Pobierz odszyfrowany klucz ze starej kolumny
            try:
                cipher = Account._get_cipher()
                api_key = cipher.decrypt(account._infakt_api_key_encrypted).decode()
            except Exception as e:
                print(f"   BLAD deszyfrowania starego klucza: {e}")
                errors.append(f"{account.name}: {e}")
                continue

            if not api_key:
                print(f"   Pusty klucz API")
                no_credentials += 1
                continue

            # Zapisz w nowym formacie
            if not dry_run:
                account.provider_settings = {'api_key': api_key}
                account.provider_type = 'infakt'

            migrated += 1
            # Maskuj klucz w logach (pokazuj tylko ostatnie 8 znaków)
            masked_key = f"***{api_key[-8:]}" if len(api_key) > 8 else "***"
            print(f"   {'[DRY RUN] ' if dry_run else ''}Zmigrowano: api_key ({masked_key})")

        # Commit wszystkich zmian
        if not dry_run:
            db.session.commit()
            print("\nZmiany zapisane w bazie danych.")
        else:
            db.session.rollback()
            print("\nDRY RUN - zmiany NIE zostaly zapisane.")

        print("\n" + "=" * 60)
        print("PODSUMOWANIE MIGRACJI")
        print("=" * 60)
        print(f"   Zmigrowano: {migrated}")
        print(f"   Pominieto (juz zmigrowane): {skipped}")
        print(f"   Brak credentials: {no_credentials}")
        print(f"   Bledy: {len(errors)}")
        print(f"   Razem: {len(accounts)}")

        if errors:
            print("\n   BLEDY:")
            for error in errors:
                print(f"      - {error}")

        if migrated > 0 and not dry_run:
            print("\nMigracja zakonczona pomyslnie!")
            print("\nKolejne kroki:")
            print("   1. Przetestuj sync dla kazdego konta")
            print("   2. Sprawdz logi aplikacji pod katem bledow")
        elif dry_run:
            print("\nAby wykonac migracje, uruchom bez --dry-run:")
            print("   flask migrate-credentials")

        print("\n" + "=" * 60)
