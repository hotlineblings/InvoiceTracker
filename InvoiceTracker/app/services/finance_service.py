"""
Serwis obliczen finansowych.
Konwersje walut, obliczenia dlugu.

Wszystkie kwoty w bazie danych sa przechowywane w GROSZACH (int).
Konwersja: 1 PLN = 100 groszy
"""
import logging

log = logging.getLogger(__name__)


def grosz_to_pln(grosz):
    """
    Konwertuje grosze na zlotowki.

    Args:
        grosz: Kwota w groszach (int lub None)

    Returns:
        float: Kwota w PLN
    """
    if grosz is None:
        return 0.0
    return grosz / 100.0


def pln_to_grosz(pln):
    """
    Konwertuje zlotowki na grosze.

    Args:
        pln: Kwota w PLN (float)

    Returns:
        int: Kwota w groszach
    """
    if pln is None:
        return 0
    return int(pln * 100)


def calculate_left_to_pay(gross_price, paid_price):
    """
    Oblicza pozostala kwote do zaplaty.

    Args:
        gross_price: Cena brutto w groszach (int lub None)
        paid_price: Zaplacona kwota w groszach (int lub None)

    Returns:
        int: Pozostala kwota w groszach
    """
    gross = gross_price if gross_price is not None else 0
    paid = paid_price if paid_price is not None else 0
    return gross - paid


def calculate_total_debt_grosz(left_to_pay_values):
    """
    Sumuje liste kwot pozostalych do zaplaty.

    Args:
        left_to_pay_values: Lista kwot w groszach

    Returns:
        int: Suma w groszach
    """
    return sum(val for val in left_to_pay_values if val is not None)


def format_currency_pln(amount_pln):
    """
    Formatuje kwote jako string PLN.

    Args:
        amount_pln: Kwota w PLN (float)

    Returns:
        str: Sformatowana kwota (np. "1 234.56 zl")
    """
    if amount_pln is None:
        return "0.00 zl"
    # Formatowanie z separatorem tysiecy
    formatted = f"{amount_pln:,.2f}".replace(",", " ")
    return f"{formatted} zl"
