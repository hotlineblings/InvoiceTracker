# send_email.py
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import logging
from contextlib import contextmanager

load_dotenv()

# SMTP Configuration (legacy global)
SMTP_SERVER = os.getenv('SMTP_SERVER', 'sgz.nazwa.pl')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', 'rozliczenia@aquatest.pl')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'

# Global SMTP connection
_smtp_connection = None


@contextmanager
def get_smtp_connection():
    """
    Context manager for SMTP connection that handles connection, authentication,
    and cleanup. Reuses existing connection if available.
    """
    global _smtp_connection

    try:
        if _smtp_connection is None:
            _smtp_connection = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            if SMTP_USE_TLS:
                _smtp_connection.starttls()
            _smtp_connection.login(SMTP_USERNAME, SMTP_PASSWORD)

        yield _smtp_connection
    except Exception as e:
        # If connection is broken, try to reconnect
        if _smtp_connection:
            try:
                _smtp_connection.quit()
            except:
                pass
            _smtp_connection = None
        raise e


def send_email(to_email, subject, body, html=False):
    """
    Send an email using a persistent SMTP connection.
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_USERNAME
        msg['To'] = to_email

        if html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))

        with get_smtp_connection() as smtp:
            smtp.send_message(msg)
            print(f"Email sent successfully to {to_email}")
            return True

    except Exception as e:
        print(f"Error sending email to {to_email}: {str(e)}")
        return False


def close_smtp_connection():
    """
    Explicitly close the SMTP connection.
    Should be called when shutting down the application.
    """
    global _smtp_connection
    if _smtp_connection:
        try:
            _smtp_connection.quit()
        except:
            pass
        _smtp_connection = None


def send_email_for_account(account, to_email, subject, body, html=False):
    """
    Wysyla email uzywajac konfiguracji SMTP konkretnego konta (dla multi-tenancy).

    Args:
        account: Obiekt Account z models.py z wlasnymi ustawieniami SMTP
        to_email (str): Adres odbiorcy
        subject (str): Temat wiadomosci
        body (str): Tresc wiadomosci
        html (bool): Czy tresc jest w formacie HTML

    Returns:
        bool: True jesli wyslano pomyslnie, False w przeciwnym razie
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = account.email_from
        msg['To'] = to_email

        if html:
            msg.attach(MIMEText(body, 'html'))
        else:
            msg.attach(MIMEText(body, 'plain'))

        # Utworz dedykowane polaczenie SMTP dla tego konta (nie uzywamy globalnego)
        with smtplib.SMTP(account.smtp_server, account.smtp_port) as smtp:
            if os.getenv('SMTP_USE_TLS', 'True').lower() == 'true':
                smtp.starttls()
            smtp.login(account.smtp_username, account.smtp_password)
            smtp.send_message(msg)
            print(f"Email sent successfully to {to_email} via account: {account.name}")
            return True

    except Exception as e:
        print(f"Error sending email to {to_email} for account {account.name}: {str(e)}")
        return False
