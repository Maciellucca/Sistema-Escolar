"""
Proteção CSRF simples e sem dependência extra (usa apenas a sessão do
Flask, que já é assinada com SECRET_KEY). Suficiente para os formulários
deste sistema — se o projeto crescer muito, considere trocar por
Flask-WTF.
"""
import secrets

from flask import session, request, abort


def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _validar_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        enviado = request.form.get("csrf_token", "")
        esperado = session.get("_csrf_token", "")
        if not esperado or not secrets.compare_digest(enviado, esperado):
            abort(400, description="Sessão expirada ou formulário inválido. Recarregue a página e tente novamente.")


def init_csrf(app):
    app.jinja_env.globals["csrf_token"] = get_csrf_token
    app.before_request(_validar_csrf)
