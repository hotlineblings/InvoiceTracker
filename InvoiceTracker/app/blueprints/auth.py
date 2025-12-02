"""
Blueprint autoryzacji.
Logowanie, wylogowanie, wybór profilu.
"""
import os
from flask import Blueprint, render_template, redirect, url_for, flash, session

from ..models import Account
from ..forms import LoginForm, SwitchAccountForm

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Logowanie administratora."""
    form = LoginForm()
    if form.validate_on_submit():
        admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin')
        if form.username.data == admin_user and form.password.data == admin_pass:
            session['logged_in'] = True
            flash("Zalogowano.", "success")
            return redirect(url_for('auth.select_account'))
        else:
            flash("Złe dane.", "danger")
    return render_template('login.html', form=form)


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

    switch_form = SwitchAccountForm()
    return render_template('select_account.html', accounts=accounts, switch_form=switch_form)


@auth_bp.route('/switch_account', methods=['POST'])
def switch_account():
    """Przełączanie między profilami (POST z CSRF)."""
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))

    form = SwitchAccountForm()
    if form.validate_on_submit():
        account_id = int(form.account_id.data)
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
