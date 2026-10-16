"""Shared email transport. Settings responses never include SMTP credentials."""
import os
import smtplib
import socket
import ssl
from email.message import EmailMessage
from cryptography.fernet import InvalidToken
from .core import cipher


def smtp_configuration(settings, secret=None):
    source=settings.get('smtp_source','environment')
    if source=='panel':
        encrypted=settings.get('smtp_password_encrypted','')
        result={'source':source,'host':settings.get('smtp_host',''),'port':settings.get('smtp_port',587),
            'security':settings.get('smtp_security','starttls'),'user':settings.get('smtp_user',''),
            'password_saved':bool(encrypted)}
        if secret is not None:
            result['password']=cipher(secret).decrypt(encrypted.encode()).decode() if encrypted else ''
    else:
        try: port=int(os.getenv('SMTP_PORT','587'))
        except ValueError: port=0
        result={'source':'environment','host':os.getenv('SMTP_HOST',''),'port':port,
            'security':os.getenv('SMTP_SECURITY','starttls'),'user':os.getenv('SMTP_USER',''),
            'password_saved':bool(os.getenv('SMTP_PASSWORD'))}
        if secret is not None: result['password']=os.getenv('SMTP_PASSWORD','')
    return result


def smtp_ready(settings):
    s=smtp_configuration(settings)
    return bool(s['host'] and settings.get('sender') and type(s['port']) is int and 1<=s['port']<=65535
        and s['security'] in ('ssl','starttls') and (not s['user'] or s['password_saved']))


def send_email(settings, secret, to, subject, body, message_id, html_body=None):
    if not smtp_ready(settings):
        raise ValueError('Complete the SMTP host, port, security, sender and any required login details first.')
    s=smtp_configuration(settings,secret)
    message=EmailMessage();message['From']=settings['sender'];message['To']=to;message['Subject']=subject
    message['Message-ID']='<'+message_id+'@planner.ivorydigital.uk>'
    if settings.get('reply_to'): message['Reply-To']=settings['reply_to']
    message.set_content(body)
    if html_body: message.add_alternative(html_body,subtype='html')
    smtp=None
    try:
        if s['security']=='ssl':
            smtp=smtplib.SMTP_SSL(s['host'],s['port'],timeout=10,context=ssl.create_default_context())
        else:
            smtp=smtplib.SMTP(s['host'],s['port'],timeout=10)
            smtp.ehlo();smtp.starttls(context=ssl.create_default_context());smtp.ehlo()
        if s['user']: smtp.login(s['user'],s['password'])
        smtp.send_message(message)
    finally:
        if smtp is not None:
            # A lost QUIT acknowledgement after acceptance must not trigger a resend.
            try: smtp.quit()
            except Exception:
                try: smtp.close()
                except Exception: pass


def delivery_error(exc):
    # Provider exception text can contain credentials or addresses. Use fixed hints only.
    if isinstance(exc,smtplib.SMTPAuthenticationError): return 'Login rejected. Check the SMTP username and password or app password.'
    if isinstance(exc,smtplib.SMTPSenderRefused): return 'Sender rejected. Use an authorised sending address for this mailbox.'
    if isinstance(exc,smtplib.SMTPRecipientsRefused): return 'Recipient rejected by the email server. Check the destination address.'
    if isinstance(exc,smtplib.SMTPDataError): return 'The email server rejected the message. Check the mailbox sending permissions or provider limits.'
    if isinstance(exc,ssl.SSLError): return 'Secure connection failed. Check the SMTP hostname, port and SSL/TLS setting.'
    if isinstance(exc,socket.gaierror): return 'SMTP server not found. Check its hostname and the server DNS connection.'
    if isinstance(exc,smtplib.SMTPNotSupportedError): return 'The server does not support the selected secure connection or login method.'
    if isinstance(exc,(TimeoutError,ConnectionError,OSError)): return 'Cannot reach the email server. Check the host, port and network connection.'
    if isinstance(exc,InvalidToken): return 'The saved password cannot be unlocked. Re-enter it and save the email settings.'
    if isinstance(exc,ValueError): return 'Email settings are incomplete. Check the SMTP connection and sender details.'
    return 'Email delivery failed. Check the SMTP details and your provider’s sending permissions.'

