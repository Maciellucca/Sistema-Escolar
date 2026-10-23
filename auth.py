import hashlib
import secrets
from functools import wraps

from flask import session, redirect, url_for, request, abort
from werkzeug.security import generate_password_hash, check_password_hash

import config

from models import get_db


# ---------------------------------------------------------------- staff ----
def hash_password(raw):
    return generate_password_hash(raw)


def verify_password(raw, hashed):
    return check_password_hash(hashed, raw)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("staff.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*papeis):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("staff.login", next=request.path))
            if session.get("papel") not in papeis:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def papel_efetivo(papel):
    """Perfil usado nas permissões: Direção vale como administrador."""
    return config.PAPEL_EFETIVO.get(papel, papel)


def current_user():
    """Usuário logado, com "papel" já efetivo (Direção -> admin) e o perfil
    cadastrado em "papel_cadastro"."""
    if not session.get("user_id"):
        return None
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if row is None:
        return None
    user = dict(row)
    user["papel_cadastro"] = user["papel"]
    user["papel"] = papel_efetivo(user["papel"])
    return user


# ------------------------------------------------------------- guardian ----
def new_guardian_token():
    """Gera um token para o responsavel (mostrado 1 vez ao staff) e o hash
    que fica salvo no banco. Nunca guardamos o token em texto puro."""
    token = secrets.token_urlsafe(24)
    return token, hash_token(token)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def codigo_responsavel(db, student_id, trocar=False):
    """Código fixo de 6 números do responsável: criado na primeira vez e
    mantido (a secretaria consulta e copia quando quiser). trocar=True gera
    outro — o anterior (e o token antigo, se houver) deixam de valer."""
    aluno = db.execute(
        "SELECT guardian_codigo FROM students WHERE id = ?", (student_id,)
    ).fetchone()
    if not aluno:
        return None
    if aluno["guardian_codigo"] and not trocar:
        return aluno["guardian_codigo"]
    while True:
        codigo = f"{secrets.randbelow(10**6):06d}"
        if not db.execute("SELECT 1 FROM students WHERE guardian_codigo = ?", (codigo,)).fetchone():
            break
    if trocar:
        db.execute(
            "UPDATE students SET guardian_codigo = ?, guardian_token_hash = NULL WHERE id = ?",
            (codigo, student_id),
        )
    else:
        db.execute("UPDATE students SET guardian_codigo = ? WHERE id = ?", (codigo, student_id))
    return codigo


def guardian_student_from_token(token):
    """Aceita o código de 6 números (atual) e, por compatibilidade, o
    token longo antigo de quem já tinha recebido um."""
    token = (token or "").strip()
    if not token:
        return None
    digitos = "".join(c for c in token if not c.isspace() and c not in ".-")
    with get_db() as db:
        if len(digitos) == 6 and digitos.isdigit():
            return db.execute("SELECT * FROM students WHERE guardian_codigo = ?", (digitos,)).fetchone()
        return db.execute(
            "SELECT * FROM students WHERE guardian_token_hash = ?", (hash_token(token),)
        ).fetchone()
