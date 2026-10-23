"""
scripts/migrar_sqlite_para_mysql.py: copia um banco SQLite (com fotos) para
o MySQL. Só roda com um MySQL de teste (TESTE_MYSQL_HOST).
"""
import importlib
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("TESTE_MYSQL_HOST"), reason="precisa de um MySQL de teste")


def test_copia_tabelas_e_fotos(tmp_path, monkeypatch):
    from conftest import _preparar_mysql_de_teste
    import config

    # origem: SQLite com um aluno, um usuário e uma foto na pasta
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("ESCOLA_DATA_DIR", str(tmp_path / "origem"))
    monkeypatch.delenv("ESCOLA_DB_PATH", raising=False)
    importlib.reload(config)
    import models
    models.init_db()
    with models.get_db() as db:
        sid = db.execute("INSERT INTO students (codigo_interno, nome, turma, situacao, data_nascimento, foto_path) "
                         "VALUES ('M1','ALUNA MIGRADA','4A','ATIVO','', 'aluno_1.jpg')").lastrowid
        db.execute("INSERT INTO users (username, password_hash, nome, papel) VALUES ('diretora','x','Diretora','direcao')")
        db.execute("INSERT INTO afastamentos_saude (student_id, data_inicio, data_fim) VALUES (?, '2026-03-01', '')", (sid,))
    (config.PHOTOS_DIR).mkdir(parents=True, exist_ok=True)
    (config.PHOTOS_DIR / f"aluno_{sid}.jpg").write_bytes(b"JPEGFAKE")
    origem = config.DB_PATH

    # destino: MySQL vazio
    _preparar_mysql_de_teste(monkeypatch)
    monkeypatch.setenv("ESCOLA_DATA_DIR", str(tmp_path / "destino"))
    importlib.reload(config)
    from scripts.migrar_sqlite_para_mysql import migrar
    resumo = migrar(origem, saida=lambda *_: None)
    assert resumo["students"] == 1 and resumo["(arquivos de fotos)"] == 1
    with models.get_db() as db:
        a = db.execute("SELECT id, nome, data_nascimento FROM students").fetchone()
        assert (a["id"], a["nome"]) == (sid, "ALUNA MIGRADA")
        assert db.execute("SELECT papel FROM users WHERE username = 'diretora'").fetchone()["papel"] == "direcao"
        assert db.execute("SELECT data_fim FROM afastamentos_saude").fetchone()["data_fim"] is None
        assert db.execute("SELECT COUNT(*) n FROM whatsapp_modelos").fetchone()["n"] == 4
    import arquivos
    assert arquivos.ler(arquivos.FOTOS, f"aluno_{sid}.jpg") == b"JPEGFAKE"
    # segunda vez sem --substituir: recusa
    with pytest.raises(SystemExit):
        migrar(origem, saida=lambda *_: None)
    assert migrar(origem, substituir=True, saida=lambda *_: None)["students"] == 1
