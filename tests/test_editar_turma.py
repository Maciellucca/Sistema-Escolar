"""
Testa a edição de turma do aluno (usada sobretudo pra corrigir a turma
provisória 'TEG-PROV'), incluindo a correção em lote na tela da turma e
o desaparecimento automático da TEG-PROV do painel principal assim que
ninguém mais estiver nela.
"""


def _aluno(db, codigo, nome, turma="6A", serie="6º Ano"):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?,?, 'ATIVO')",
        (codigo, nome, turma, serie),
    ).lastrowid


def test_link_editar_turma_aparece_na_pagina_do_aluno(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "ET1", "ALUNO TESTE TURMA")

    resp = client.get(f"/aluno/{aluno_id}")
    assert "Editar turma" in resp.get_data(as_text=True)


def test_corrigir_turma_de_aluno_provisorio(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "ET2", "ALUNO PROVISORIO TESTE", turma="TEG-PROV", serie="7º Ano")

    tok = pegar_csrf(f"/aluno/{aluno_id}/turma")
    resp = client.post(
        f"/aluno/{aluno_id}/turma",
        data={"csrf_token": tok, "turma": "7a", "serie": "7º Ano"},
        follow_redirects=True,
    )
    assert "atualizada" in resp.get_data(as_text=True).lower()

    with get_db() as db:
        aluno = db.execute("SELECT turma FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["turma"] == "7A"  # maiuscula


def test_turma_vazia_mostra_erro(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "ET3", "ALUNO TESTE 3", turma="TEG-PROV")

    tok = pegar_csrf(f"/aluno/{aluno_id}/turma")
    resp = client.post(
        f"/aluno/{aluno_id}/turma",
        data={"csrf_token": tok, "turma": "", "serie": ""},
        follow_redirects=True,
    )
    assert "não pode ficar em branco" in resp.get_data(as_text=True)

    with get_db() as db:
        aluno = db.execute("SELECT turma FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["turma"] == "TEG-PROV"








def test_professor_nao_edita_turma(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        aluno_id = _aluno(db, "ET9", "ALUNO TESTE 9")
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("prof13", hash_password("senha-professor-999"), "Professor Treze", "Sala", "professor"),
        )
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "prof13", "senha": "senha-professor-999", "csrf_token": tok})

    resp = client.get(f"/aluno/{aluno_id}/turma")
    assert resp.status_code == 403
