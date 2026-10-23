"""
Fixtures compartilhadas dos testes. Cada teste roda com um banco de dados
e uma pasta de dados totalmente isolados (tmp_path do pytest) — nada aqui
toca no banco/arquivos reais do projeto.
"""
import importlib
import os
import secrets
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


BANCO_MYSQL_TESTE = "escola_teste_pytest"


def _preparar_mysql_de_teste(monkeypatch):
    import pymysql
    host = os.environ["TESTE_MYSQL_HOST"]
    porta = int(os.environ.get("TESTE_MYSQL_PORT", "3306"))
    usuario = os.environ.get("TESTE_MYSQL_USER", "root")
    senha = os.environ.get("TESTE_MYSQL_PASSWORD", "")
    conn = pymysql.connect(host=host, port=porta, user=usuario, password=senha)
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {BANCO_MYSQL_TESTE}")
        cur.execute(f"CREATE DATABASE {BANCO_MYSQL_TESTE} CHARACTER SET utf8mb4")
    conn.close()
    for chave, valor in (("DB_BACKEND", "mysql"), ("MYSQL_HOST", host), ("MYSQL_PORT", str(porta)),
                         ("MYSQL_USER", usuario), ("MYSQL_PASSWORD", senha), ("MYSQL_DATABASE", BANCO_MYSQL_TESTE)):
        monkeypatch.setenv(chave, valor)
    monkeypatch.delenv("MYSQL_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ESCOLA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("ADMIN_SETUP_KEY", "chave-de-teste-12345")
    monkeypatch.setenv("ESCOLA_DEBUG", "0")
    monkeypatch.setenv("ESCOLA_FORCE_HTTPS", "0")
    monkeypatch.delenv("ESCOLA_DB_PATH", raising=False)
    # Os testes rodam contra SQLite, mesmo que o ambiente de quem está
    # rodando tenha DB_BACKEND=mysql configurado globalmente. Para rodar a
    # mesma suíte num MySQL de teste (banco apagado e recriado a cada
    # teste), defina TESTE_MYSQL_HOST (e TESTE_MYSQL_PORT/USER/PASSWORD).
    if os.environ.get("TESTE_MYSQL_HOST"):
        _preparar_mysql_de_teste(monkeypatch)
    else:
        monkeypatch.setenv("DB_BACKEND", "sqlite")

    import config
    importlib.reload(config)  # re-executa config.py lendo as env vars acima

    import app as app_module
    flask_app = app_module.create_app()
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def pegar_csrf(client):
    """Uso: token = pegar_csrf('/login')"""
    def _pegar(path):
        resp = client.get(path)
        soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
        campo = soup.find("input", {"name": "csrf_token"})
        assert campo is not None, f"formulário em {path} não tem campo csrf_token"
        return campo["value"]
    return _pegar


@pytest.fixture()
def criar_admin(app, client, pegar_csrf):
    """Cria (via rota web, chave de setup de teste) e loga um admin.
    Retorna (username, senha)."""
    import config
    username, senha = "admin_teste", "senha-de-teste-123"
    tok = pegar_csrf("/login/criar-admin")
    client.post(
        "/login/criar-admin",
        data={
            "username": username, "nome": "Admin de Teste", "setor": "Direção",
            "senha": senha, "senha2": senha, "chave": config.ADMIN_SETUP_KEY,
            "csrf_token": tok,
        },
    )
    tok2 = pegar_csrf("/login")
    client.post("/login", data={"username": username, "senha": senha, "csrf_token": tok2})
    return username, senha


@pytest.fixture()
def aluno_exemplo(app, criar_admin):
    """Insere um aluno de teste direto no banco e devolve seu id."""
    from models import get_db
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO students (codigo_interno, nome, turma, serie, situacao, aee)
               VALUES ('COD1', 'ALUNO DE TESTE', '1A', '1º Ano', 'ATIVO', 0)"""
        )
        return cur.lastrowid
