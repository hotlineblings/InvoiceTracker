"""
Funkcje pomocnicze aplikacji.
"""
from .constants import STAGE_URL_MAPPING, STAGE_MAPPING_PROGRESS


def map_stage(stage):
    """
    Mapuje skróty etapów (z URL) na pełne nazwy.

    Args:
        stage: Skrót etapu (np. "przeds", "7dni") lub pełna nazwa

    Returns:
        Pełna nazwa etapu lub oryginalna wartość jeśli nie znaleziono mapowania
    """
    return STAGE_URL_MAPPING.get(stage, stage)


def stage_to_number(text):
    """
    Konwertuje nazwę etapu na numer 1-5 (dla progress bar).

    Args:
        text: Nazwa etapu (może zawierać dodatkowy tekst po " (")

    Returns:
        Numer etapu (1-5) lub 0 jeśli nie rozpoznano
    """
    stage_key = str(text).split(" (")[0]
    return STAGE_MAPPING_PROGRESS.get(stage_key, 0)


def stage_from_log_text(text):
    """
    Wyciąga numer etapu z tekstu logu powiadomienia.

    Args:
        text: Tekst z logu (np. "Wezwanie do zapłaty (14 dni)")

    Returns:
        Numer etapu (1-5) lub 0 jeśli nie rozpoznano
    """
    return stage_to_number(text)
