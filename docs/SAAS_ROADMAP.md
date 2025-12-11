# InvoiceTracker: Strategiczny Plan Transformacji do SaaS

> **Version**: 1.0
> **Last Updated**: 2025-12-03
> **Status**: Approved

## Wizja

Przeksztalcenie InvoiceTracker z wewnetrznego narzedzia B2B w **pelnoprawny self-serve SaaS** z:
- Automatycznym billingiem (usage-based pricing)
- Multi-provider (InFakt, Fakturownia, wFirma, iFirma)
- SendGrid API zamiast SMTP
- Profesjonalnymi dashboardami

---

## Obecny Stan: 53% SaaS-Ready

| Obszar | Status | Score |
|--------|--------|-------|
| Multi-tenancy | OK - Account isolation, tenant_context | 70% |
| User Management | Basic - brak rol, brak password reset | 55% |
| Billing | BRAK | 0% |
| Providers | Tylko InFakt | 25% |
| Email | SMTP per-account | 60% |
| Dashboards | Podstawowe | 50% |

---

## Fazy Implementacji

### FAZA A: Fundamenty Billingu (Priorytet 1)

**Cel**: Stripe + usage-based pricing

#### A1. Modele bazy danych

```
Plan
├── name (starter/business/enterprise)
├── invoices_per_month (limit)
├── stripe_price_id
├── price_monthly_grosz
└── features (JSON)

Subscription
├── account_id (1:1)
├── plan_id
├── stripe_customer_id
├── stripe_subscription_id
├── status (trialing/active/past_due/canceled)
├── trial_ends_at
└── current_period_end

UsageRecord
├── account_id
├── date
├── invoices_synced
├── emails_sent
└── month (index for aggregation)
```

#### A2. Stripe Integration

**Pliki do utworzenia:**
- `app/services/stripe_service.py` - Stripe API wrapper
- `app/blueprints/billing.py` - Checkout, portal, webhooks
- `app/middleware/plan_enforcement.py` - Limit checking

**Flow:**
1. User rejestruje sie -> Trial 14 dni (plan Starter)
2. `/billing/plans` -> Wybor planu
3. Stripe Checkout -> Platnosc
4. Webhook `checkout.session.completed` -> Aktywacja
5. Przy sync/mail -> `UsageRecord.increment()` + Stripe metering

#### A3. Migracje

```
2025120500_add_plan_model.py
2025120501_add_subscription_model.py
2025120502_add_usage_record.py
2025120503_seed_default_plans.py
```

---

### FAZA B: Multi-Provider (Priorytet 2)

**Cel**: 4 systemy fakturowania do wyboru

#### B1. Rozszerzenie Provider Interface

**Plik: `providers/base.py`**

```python
class InvoiceProvider(ABC):
    @classmethod
    @abstractmethod
    def get_credentials_schema(cls) -> type: ...

    @classmethod
    @abstractmethod
    def get_setup_fields(cls) -> list[dict]: ...

    @abstractmethod
    def test_connection(self) -> bool: ...
```

#### B2. Nowe Providery

| Provider | Plik | API Docs |
|----------|------|----------|
| InFakt | `providers/infakt.py` | (istniejacy) |
| Fakturownia | `providers/fakturownia.py` | app.fakturownia.pl/api |
| wFirma | `providers/wfirma.py` | doc.wfirma.pl |
| iFirma | `providers/ifirma.py` | ifirma.pl/api |

#### B3. Account Model Extension

```python
# Account model
provider_type = Column(String(50), default='infakt')
_provider_credentials_encrypted = Column(LargeBinary)  # JSON encrypted
```

#### B4. UI - Provider Selection

**Plik: `templates/settings/provider_setup.html`**

- Dropdown: wybor providera
- Dynamiczny formularz credentials (z `get_setup_fields()`)
- Przycisk "Testuj polaczenie"

---

### FAZA C: SendGrid Migration (Priorytet 3)

**Cel**: Centralna wysylka email z trackingiem

#### C1. SendGrid Service

**Plik: `app/services/sendgrid_service.py`**

```python
class SendGridService:
    def send_email(from_email, to_email, subject, body_html,
                   track_opens=True, track_clicks=True,
                   custom_args=None) -> dict

    def parse_webhook_event(payload) -> dict
```

#### C2. Email Backend Abstraction

**Plik: `app/services/send_email.py`** (modyfikacja)

```python
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'sendgrid')

def send_email_for_account(account, to_email, subject, body, ...):
    if EMAIL_BACKEND == 'sendgrid':
        return _send_via_sendgrid(...)
    else:
        return _send_via_smtp(...)  # legacy fallback
```

#### C3. Email Tracking Model

```
EmailEvent
├── account_id
├── message_id
├── invoice_number
├── event_type (delivered/open/click/bounce)
├── event_timestamp
└── recipient_email
```

#### C4. Migration Path

1. Deploy SendGrid obok SMTP
2. Nowe konta -> SendGrid
3. Istniejace konta -> migracja stopniowa
4. Sunset SMTP

---

### FAZA D: Password Reset (Priorytet 4)

**Cel**: Self-service recovery

#### D1. Model

```
PasswordResetToken
├── user_id
├── token_hash (SHA-256)
├── expires_at (24h)
└── used_at
```

#### D2. Flow

1. `/forgot-password` -> Email input
2. Generate secure token -> Send email (SendGrid)
3. `/reset-password/<token>` -> New password form
4. Validate token -> Update password -> Mark used

#### D3. Pliki

- `app/blueprints/auth.py` - Nowe endpointy
- `templates/forgot_password.html`
- `templates/reset_password.html`

---

### FAZA E: Odsetki i Koszty Windykacji (Priorytet 5)

**Cel**: Automatyczne naliczanie odsetek + staly koszt obslugi

#### E1. Jak to dziala (z perspektywy uzytkownika)

W szczegolach sprawy sa **dwa checkboxy**:

```
[ ] Dolicz odsetki ustawowe (rosna z kazdym dniem opoznienia)
[ ] Dolicz koszt obslugi windykacji (50 zl)
```

Gdy uzytkownik zaznaczy:
- **Odsetki** -> System liczy: (kwota_dlugu x stawka_dzienna x dni_opoznienia)
- **Koszt obslugi** -> Dodaje stala kwote (np. 50 zl) do sumy

#### E2. Model danych

```
Case (rozszerzenie)
├── include_interest: Boolean (default: False)
├── include_service_fee: Boolean (default: False)
├── interest_rate_type: String ('ustawowe', 'umowne', 'custom')
├── custom_interest_rate: Decimal (opcjonalnie)

AccountSettings (nowe pole)
├── default_service_fee_grosz: Integer (np. 5000 = 50 zl)

CaseFinancials (widok wyliczany - nie tabela)
├── base_debt: kwota z faktury
├── days_overdue: dni od payment_due_date
├── calculated_interest: odsetki
├── service_fee: koszt obslugi
├── total_debt: suma wszystkiego
```

#### E3. Wzor na odsetki ustawowe

```
Odsetki = (kwota_dlugu x stopa_roczna / 365) x dni_opoznienia

Stopa ustawowa za opoznienie (2024): 11.25% rocznie
Czyli: 0.0308% dziennie

Przyklad: 1000 zl x 30 dni = 9.24 zl odsetek
```

#### E4. Model biznesowy

| Element | Kto dostaje pieniadze |
|---------|----------------------|
| Splata glowna (faktura) | Klient (Twoj uzytkownik) |
| Odsetki | Klient (Twoj uzytkownik) |
| **Koszt obslugi windykacji** | **Ty (InvoiceTracker)** |

**To jest dodatkowy przychod** oprocz subskrypcji!

#### E5. Gdzie to widac

1. **Szczegoly sprawy** - checkboxy + wyliczona suma
2. **Email do dluznika** - "Do zaplaty: 1000 zl + odsetki 9.24 zl + koszt obslugi 50 zl = **1059.24 zl**"
3. **Dashboard** - suma naliczonych kosztow obslugi (Twoj zarobek)

#### E6. Ustawienia per konto

W Settings dodajemy:
- Domyslna stawka odsetek (ustawowe / umowne X%)
- Domyslny koszt obslugi (50 zl / 100 zl / wlasna kwota)
- Czy automatycznie zaznaczac checkboxy dla nowych spraw

---

### FAZA F: Bezpieczenstwo i RODO (Priorytet 6)

**Cel**: Email verification, Audit Log, Data export/delete

#### F1. Weryfikacja email przy rejestracji

**Jak to dziala:**
1. User rejestruje sie -> konto nieaktywne
2. System wysyla email "Potwierdz swoj adres"
3. User klika link -> konto aktywne
4. Bez potwierdzenia -> nie moze sie zalogowac

**Model:**
```
EmailVerificationToken
├── user_id
├── token_hash
├── expires_at (48h)
├── verified_at
```

**Zmiany w User:**
```
User
├── email_verified: Boolean (default: False)
├── email_verified_at: DateTime
```

#### F2. Historia zmian (Audit Log)

**Co zapisujemy:**
- Kto (user_id)
- Kiedy (timestamp)
- Co zmienil (model, pole, stara_wartosc, nowa_wartosc)
- Skad (IP address)

**Model:**
```
AuditLog
├── account_id
├── user_id
├── action: 'create' | 'update' | 'delete'
├── model_name: 'Case', 'Invoice', 'Settings'
├── model_id
├── changes: JSON ({"field": {"old": X, "new": Y}})
├── ip_address
├── created_at
```

**Gdzie widac:** Nowa zakladka "Historia zmian" w Settings

#### F3. Eksport i usuniecie danych (RODO)

**Eksport danych:**
- Przycisk "Pobierz moje dane" w ustawieniach
- Generuje ZIP z:
  - Dane konta (JSON)
  - Wszystkie sprawy (CSV)
  - Historia powiadomien (CSV)
  - Logi audytu (CSV)

**Usuniecie konta:**
- Przycisk "Usun konto" (wymaga wpisania hasla)
- 7 dni na anulowanie
- Po 7 dniach -> kasuje wszystko bezpowrotnie
- Email potwierdzajacy usuniecie

---

### FAZA G: Powiadomienia w aplikacji (Priorytet 7)

**Cel**: Alerty o waznych wydarzeniach wewnatrz aplikacji (bez emaili)

#### G1. Typy powiadomien

| Typ | Kiedy | Priorytet |
|-----|-------|-----------|
| sync_failed | Synchronizacja nie powiodla sie | Wysoki |
| sync_completed | Synchronizacja zakonczona (X nowych spraw) | Niski |
| plan_limit_warning | 80% limitu wykorzystane | Sredni |
| plan_limit_exceeded | Limit przekroczony | Wysoki |
| payment_failed | Platnosc za subskrypcje nie powiodla sie | Wysoki |
| case_paid | Sprawa oznaczona jako oplacona | Niski |

#### G2. Model

```
Notification
├── account_id
├── type: String
├── title: String
├── message: Text
├── priority: 'low' | 'medium' | 'high'
├── read_at: DateTime (null = nieprzeczytane)
├── created_at
```

#### G3. Gdzie widac

- **Dzwonek w nawigacji** z licznikiem nieprzeczytanych
- **Panel powiadomien** (dropdown po kliknieciu dzwonka)
- **Strona /notifications** z pelna historia

---

### FAZA H: Dashboards (Priorytet 8)

**Cel**: Wizualne KPI dla kazdego konta

#### H1. Co pokazujemy na dashboardzie

| Metryka | Co to znaczy |
|---------|--------------|
| Aktywne sprawy | Ile spraw czeka na zaplate |
| Recovery Rate | Jaki % spraw konczy sie zaplata |
| Suma dlugow | Ile pieniedzy jest "w grze" |
| Wyslane emaile | Ile przypomnien poszlo w tym miesiacu |
| Skutecznosc etapow | Ktory etap najczesciej "odblokowuje" platnosc |
| Wykorzystanie planu | 75/100 faktur w tym miesiacu |
| **Twoj zarobek** | Suma naliczonych kosztow obslugi (nowa metryka!) |

#### H2. Wykresy

- **Trend spraw** - ile nowych / zamknietych dziennie (linia)
- **Skutecznosc etapow** - ktory etap dziala najlepiej (slupki)
- **Rozklad dlugow** - po kwotach (kolowy)

#### H3. Eksport

- Przycisk "Pobierz raport CSV" z wyborem zakresu dat

---

## Krytyczne Pliki do Modyfikacji

| Plik | Zmiany |
|------|--------|
| `app/models.py` | +Plan, +Subscription, +UsageRecord, +PasswordResetToken, +EmailEvent |
| `app/providers/base.py` | +get_credentials_schema(), +get_setup_fields() |
| `app/providers/factory.py` | +PROVIDER_MAP rozszerzony |
| `app/services/send_email.py` | Backend abstraction (SendGrid/SMTP) |
| `app/__init__.py` | +billing_bp, +dashboard_bp registration |
| `app/blueprints/auth.py` | +forgot_password, +reset_password |

**Nowe pliki:**
- `app/providers/fakturownia.py`
- `app/providers/wfirma.py`
- `app/providers/ifirma.py`
- `app/services/stripe_service.py`
- `app/services/sendgrid_service.py`
- `app/services/analytics_service.py`
- `app/blueprints/billing.py`
- `app/blueprints/dashboard.py`
- `app/middleware/plan_enforcement.py`

---

## Environment Variables (nowe)

```bash
# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# SendGrid
SENDGRID_API_KEY=SG....
EMAIL_BACKEND=sendgrid

# Plans
DEFAULT_TRIAL_DAYS=14
```

---

## Kolejnosc Implementacji (8 faz)

```
[A] Billing ────────┐
                    │
[B] Multi-Provider ─┼──> [E] Odsetki/Koszty ──> [H] Dashboards
                    │
[C] SendGrid ───────┤
                    │
[D] Password Reset ─┼──> [F] RODO/Audit ──> [G] Powiadomienia
```

**Rekomendowana kolejnosc:**

| # | Faza | Co robimy |
|---|------|-----------|
| 1 | **A** | Stripe + plany + limity |
| 2 | **D** | Przypomnienie hasla |
| 3 | **F** | Email verification + Audit Log + RODO |
| 4 | **B** | Fakturownia, wFirma, iFirma |
| 5 | **C** | SendGrid (+ white-label) |
| 6 | **E** | Odsetki + koszty windykacji |
| 7 | **G** | Powiadomienia w aplikacji |
| 8 | **H** | Dashboardy z wykresami |

---

## Definicje Planow (propozycja)

| Plan | Faktury/mies. | Konta | Cena |
|------|---------------|-------|------|
| Starter | 100 | 1 | 49 PLN |
| Business | 500 | 3 | 149 PLN |
| Enterprise | Unlimited | Unlimited | 499 PLN |

---

## Decyzje o funkcjach (ZATWIERDZONE)

### DODAJEMY do MVP:
- [x] Potwierdzenie email przy rejestracji
- [x] Przypomnienie hasla
- [x] Historia zmian (Audit Log) - kto co kiedy zmienil
- [x] Eksport danych + usuniecie konta (RODO)
- [x] Powiadomienia wewnatrz aplikacji (nie email)
- [x] White-label w emailach (logo klienta) - przez SendGrid
- [x] Odsetki + Koszt windykacji
- [ ] Link platnosci w emailu - DO OCENY trudnosci

### POMIJAMY (swiadoma decyzja):
- Team management / zaproszenia (jeden login na konto)
- Role / uprawnienia (niepotrzebne przy jednym loginie)
- API publiczne (integrujemy tylko z wybranymi programami)
- Webhooks
- SMS
- Panel dla dluznika
- Aplikacja mobilna
