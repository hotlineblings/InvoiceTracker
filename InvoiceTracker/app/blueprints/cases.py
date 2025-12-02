"""
Blueprint spraw windykacyjnych.
Aktywne sprawy, zakonczone, szczegoly, klienci.
"""
import logging

from flask import Blueprint, render_template, redirect, url_for, request, flash, session

from ..services import case_service, notification_service, payment_service
from ..forms import MarkPaidForm, SendManualForm, ReopenCaseForm, ManualSyncForm

log = logging.getLogger(__name__)

cases_bp = Blueprint('cases', __name__)


@cases_bp.route('/')
def active_cases():
    """Lista aktywnych spraw windykacyjnych."""
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    sync_form = ManualSyncForm()

    try:
        result = case_service.get_active_cases_for_account(
            account_id=account_id,
            search_query=request.args.get('search', '').strip().lower(),
            sort_by=request.args.get('sort_by', 'case_number'),
            sort_order=request.args.get('sort_order', 'asc'),
            page=request.args.get('page', 1, type=int),
            per_page=100
        )
        return render_template('cases.html', sync_form=sync_form, **result)
    except Exception as e:
        log.error(f"General error in active_cases: {e}", exc_info=True)
        flash("Wystapil blad podczas ladowania spraw aktywnych.", "danger")
        return render_template(
            'cases.html',
            sync_form=sync_form,
            cases=[],
            search_query="",
            sort_by="case_number",
            sort_order="asc",
            total_debt_all=0,
            active_count=0,
            page=1,
            per_page=100,
            total_pages=0,
            total_count=0
        )


@cases_bp.route('/completed')
def completed_cases():
    """Lista zakonczonych spraw windykacyjnych."""
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    try:
        result = case_service.get_completed_cases_for_account(
            account_id=account_id,
            search_query=request.args.get('search', '').strip().lower(),
            sort_by=request.args.get('sort_by', 'case_number'),
            sort_order=request.args.get('sort_order', 'asc'),
            page=request.args.get('page', 1, type=int),
            per_page=100,
            show_unpaid=request.args.get('show_unpaid', '') == '1'
        )
        return render_template('completed.html', **result)
    except Exception as e:
        log.error(f"General error in completed_cases: {e}", exc_info=True)
        flash("Blad ladowania spraw zakonczonych.", "danger")
        return render_template(
            'completed.html',
            cases=[],
            stage_counts={i: 0 for i in range(1, 6)},
            completed_count=0,
            search_query="",
            sort_by="case_number",
            sort_order="asc",
            page=1,
            per_page=100,
            total_pages=0,
            total_count=0
        )


@cases_bp.route('/case/<path:case_number>')
def case_detail(case_number):
    """Szczegoly sprawy windykacyjnej."""
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    try:
        result = case_service.get_case_detail(account_id, case_number)
        # Dodaj formularze akcji do kontekstu szablonu
        result['mark_paid_form'] = MarkPaidForm()
        result['send_manual_form'] = SendManualForm()
        result['reopen_form'] = ReopenCaseForm()
        return render_template('case_detail.html', **result)
    except Exception as e:
        log.error(f"Blad w case_detail dla {case_number}: {e}", exc_info=True)
        flash(f"Blad ladowania sprawy {case_number}.", "danger")
        return redirect(url_for('cases.active_cases'))


@cases_bp.route('/client/<client_id>')
def client_cases(client_id):
    """Lista spraw dla konkretnego klienta."""
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    sync_form = ManualSyncForm()

    try:
        result = case_service.get_client_cases(account_id, client_id)
        return render_template('client_cases.html', sync_form=sync_form, **result)
    except Exception as e:
        log.error(f"Blad w client_cases dla {client_id}: {e}", exc_info=True)
        flash(f"Blad ladowania spraw klienta {client_id}.", "danger")
        return redirect(url_for('cases.active_cases'))


@cases_bp.route('/mark_paid/<int:invoice_id>', methods=['POST'])
def mark_invoice_paid(invoice_id):
    """Oznacza fakture jako oplacona (POST z CSRF)."""
    form = MarkPaidForm()
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    if form.validate_on_submit():
        result = payment_service.mark_invoice_as_paid(account_id, invoice_id)
        flash(result['message'], result['message_type'])

    return redirect(url_for('cases.active_cases'))


@cases_bp.route('/send_manual', methods=['POST'])
def send_manual():
    """Reczna wysylka powiadomienia (POST z CSRF)."""
    form = SendManualForm()
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    if form.validate_on_submit():
        case_number = form.case_number.data
        stage = form.stage.data
        result = notification_service.send_manual_notification(account_id, case_number, stage)
        flash(result['message'], result['message_type'])
        return redirect(url_for('cases.case_detail', case_number=case_number))

    return redirect(url_for('cases.active_cases'))


@cases_bp.route('/reopen_case', methods=['POST'])
def reopen_case():
    """Przywraca zamknieta sprawe do statusu aktywnego (POST z CSRF)."""
    form = ReopenCaseForm()
    if not session.get('logged_in'):
        flash("Zaloguj sie.", "danger")
        return redirect(url_for('auth.login'))

    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('auth.select_account'))

    if form.validate_on_submit():
        case_number = form.case_number.data
        result = payment_service.reopen_case(account_id, case_number)
        flash(result['message'], result['message_type'])
        return redirect(url_for('cases.case_detail', case_number=case_number))

    return redirect(url_for('cases.active_cases'))
