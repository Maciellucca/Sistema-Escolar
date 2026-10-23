"""
Envio de e-mail pelo SMTP configurado nas variáveis de ambiente (SMTP_*
em config.py). Usado pelo "Esqueci minha senha". Só biblioteca padrão
(smtplib) — nenhum serviço externo além do servidor SMTP escolhido.
"""
import smtplib
import ssl
from email.message import EmailMessage

import config


def email_configurado():
    return bool(config.SMTP_HOST and config.SMTP_FROM)


def enviar_email(para, assunto, texto):
    """Envia um e-mail de texto simples. Levanta exceção se falhar —
    quem chama decide o que mostrar pro usuário."""
    if not email_configurado():
        raise RuntimeError("Envio de e-mail não configurado (SMTP_HOST/SMTP_FROM).")
    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(texto)

    contexto = ssl.create_default_context()
    if config.SMTP_SSL:
        servidor = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=contexto, timeout=20)
    else:
        servidor = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
    with servidor:
        if not config.SMTP_SSL:
            servidor.ehlo()
            if servidor.has_extn("starttls"):
                servidor.starttls(context=contexto)
                servidor.ehlo()
        if config.SMTP_USER:
            servidor.login(config.SMTP_USER, config.SMTP_PASSWORD)
        servidor.send_message(msg)
