"""
Stałe aplikacji.
Definicje etapów powiadomień i mapowania.
"""

# ===== CANONICAL SOURCE OF TRUTH =====
# Definicja oficjalnej struktury 5 etapów powiadomień
# Każdy profil MUSI mieć dokładnie te same nazwy w bazie danych
# Lista krotek zachowuje kolejność wyświetlania
CANONICAL_NOTIFICATION_STAGES = [
    ("Przypomnienie o zbliżającym się terminie płatności", -1),
    ("Powiadomienie o upływie terminu płatności", 7),
    ("Wezwanie do zapłaty", 14),
    ("Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności", 21),
    ("Przekazanie sprawy do windykatora zewnętrznego", 30),
]

# Etykiety etapów (dla UI)
STAGE_LABELS = {
    "Przypomnienie o zbliżającym się terminie płatności": "Przypomnienie o zbliżającym się terminie płatności",
    "Powiadomienie o upływie terminu płatności": "Powiadomienie o upływie terminu płatności",
    "Wezwanie do zapłaty": "Wezwanie do zapłaty",
    "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności":
        "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności",
    "Przekazanie sprawy do windykatora zewnętrznego": "Przekazanie sprawy do windykatora zewnętrznego"
}

# Mapowanie etapów na numery (dla progress bar)
STAGE_MAPPING_PROGRESS = {
    "Przypomnienie o zbliżającym się terminie płatności": 1,
    "Powiadomienie o upływie terminu płatności": 2,
    "Wezwanie do zapłaty": 3,
    "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
    "Przekazanie sprawy do windykatora zewnętrznego": 5
}

# Mapowanie skrótów URL na pełne nazwy etapów
STAGE_URL_MAPPING = {
    "przeds": "Przypomnienie o zbliżającym się terminie płatności",
    "7dni": "Powiadomienie o upływie terminu płatności",
    "14dni": "Wezwanie do zapłaty",
    "21dni": "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności",
    "30dni": "Przekazanie sprawy do windykatora zewnętrznego"
}
