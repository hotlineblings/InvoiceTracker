"""
Blueprint autoryzacji.
Logowanie, wylogowanie, wybór profilu.
"""
import os
from flask import Blueprint, render_template, redirect, url_for, request, flash, session

from ..models import Account

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Logowanie administratora."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin')
        if username == admin_user and password == admin_pass:
            session['logged_in'] = True
            flash("Zalogowano.", "success")
            return redirect(url_for('auth.select_account'))
        else:
            flash("Złe dane.", "danger")
    return render_template('login.html')


@auth_bp.route('/select_account')
def select_account():
    """Wybór profilu po zalogowaniu."""
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()

    # Jeśli tylko jedno konto - automatycznie wybierz
    if len(accounts) == 1:
        session['current_account_id'] = accounts[0].id
        session['current_account_name'] = accounts[0].name
        flash(f'Automatycznie wybrano profil: {accounts[0].name}', 'info')
        return redirect(url_for('cases.active_cases'))

    return render_template('select_account.html', accounts=accounts)


@auth_bp.route('/switch_account/<int:account_id>')
def switch_account(account_id):
    """Przełączanie między profilami."""
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    account = Account.query.filter_by(id=account_id, is_active=True).first()
    if not account:
        flash("Nieprawidłowe konto.", "danger")
        return redirect(url_for('auth.select_account'))

    session['current_account_id'] = account.id
    session['current_account_name'] = account.name
    flash(f'Przełączono na profil: {account.name}', 'success')
    return redirect(url_for('cases.active_cases'))


@auth_bp.route('/logout')
def logout():
    """Wylogowanie."""
    session.pop('logged_in', None)
    session.pop('current_account_id', None)
    session.pop('current_account_name', None)
    flash("Wylogowano.", "success")
    return redirect(url_for('auth.login'))
