"""
Perfis Direção (acesso completo, igual ao administrador) e POT (consulta
de alunos e turmas, sem acesso administrativo).
"""
from bs4 import BeautifulSoup


def _entrar_como(client, pegar_csrf, papel, username=None):
    from auth import hash_password
    from models import get_db
    username = username or f"user_{papel}"
    with get_db() as db:
        db.execute("INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
                   (username, hash_password("senha-perfil-123"), f"Pessoa {papel}", None, papel))
        sid = db.execute("INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('P1','ALUNO PERFIL','3A','3º Ano','ATIVO')").lastrowid
    client.get("/logout")
    client.post("/login", data={"username": username, "senha": "senha-perfil-123", "csrf_token": pegar_csrf("/login")})
    return sid


def _menu(client):
    soup = BeautifulSoup(client.get("/").get_data(as_text=True), "html.parser")
    return {a["href"] for a in soup.select("aside.sidebar a[href]")}


def test_direcao_tem_acesso_completo(client, pegar_csrf, criar_admin):
    sid = _entrar_como(client, pegar_csrf, "direcao")
    for url in ("/configuracoes/usuarios", "/arquivo-morto/", "/importar/notas", "/importar/alunos",
                f"/aluno/{sid}", "/turma/3A"):
        assert client.get(url).status_code == 200, url
    html = client.get("/configuracoes/usuarios").get_data(as_text=True)
    assert "Direção" in html and "POT" in html


def test_pot_consulta_alunos_e_turmas_sem_acesso_administrativo(client, pegar_csrf, criar_admin):
    sid = _entrar_como(client, pegar_csrf, "pot")
    for url in ("/", "/turma/3A", f"/aluno/{sid}"):
        assert client.get(url).status_code == 200, url
    for url in ("/configuracoes/usuarios", "/arquivo-morto/", "/importar/notas", "/importar/alunos"):
        assert client.get(url).status_code == 403, url
    menu = _menu(client)
    assert "/arquivo-morto/" not in menu


def test_admin_escolhe_os_novos_perfis(client, pegar_csrf, criar_admin):
    from models import get_db
    tok = pegar_csrf("/configuracoes/usuarios")
    for papel, login in (("direcao", "diretora"), ("pot", "pot.maria")):
        client.post("/configuracoes/usuarios/novo", data={
            "csrf_token": tok, "nome": login, "username": login, "papel": papel, "setor": "", "email": ""})
    with get_db() as db:
        papeis = {r["username"]: r["papel"] for r in db.execute("SELECT username, papel FROM users")}
    assert papeis["diretora"] == "direcao" and papeis["pot.maria"] == "pot"


def test_direcao_conta_como_administrador_ativo(client, pegar_csrf, criar_admin):
    """Com uma Direção ativa, o admin pode ser rebaixado por ela; e a última
    pessoa com acesso completo não perde o perfil."""
    from models import get_db
    _entrar_como(client, pegar_csrf, "direcao", "diretora")
    tok = pegar_csrf("/configuracoes/usuarios")
    with get_db() as db:
        admin_id = db.execute("SELECT id FROM users WHERE username = 'admin_teste'").fetchone()["id"]
    client.post(f"/configuracoes/usuarios/{admin_id}/editar", data={"csrf_token": tok, "papel": "secretaria", "setor": ""})
    with get_db() as db:
        assert db.execute("SELECT papel FROM users WHERE id = ?", (admin_id,)).fetchone()["papel"] == "secretaria"
        # única com acesso completo agora é a diretora: não pode ser desativada nem rebaixada por outro admin
        assert db.execute("SELECT COUNT(*) c FROM users WHERE papel IN ('admin','direcao') AND ativo = 1").fetchone()["c"] == 1


def test_migracao_do_check_de_papel_em_banco_antigo(tmp_path, monkeypatch):
    import os
    import sqlite3
    import pytest
    if os.environ.get("TESTE_MYSQL_HOST"):
        pytest.skip("migração do CHECK específica do SQLite")
    import config
    import models
    banco = tmp_path / "antigo.db"
    c = sqlite3.connect(banco)
    c.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, nome TEXT NOT NULL, setor TEXT,
            papel TEXT NOT NULL CHECK (papel IN ('admin','professor','aee','secretaria')),
            ativo INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO users (username, password_hash, nome, papel) VALUES ('velho', 'x', 'Velho', 'admin');
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(config, "DB_PATH", str(banco))
    models.init_db()
    with models.get_db() as db:
        db.execute("UPDATE users SET papel = 'pot' WHERE username = 'velho'")
        assert db.execute("SELECT papel FROM users").fetchone()["papel"] == "pot"
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
