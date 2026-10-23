"""
Testa a edição do nome do aluno (correção do nome de registro) e o
nome social — usado no dia a dia do sistema no lugar do nome de
registro, mas nunca em documentos oficiais.
"""
import io


def _aluno(db, codigo, nome, turma="6A", serie="6º Ano", nome_social=None):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, nome_social, turma, serie, situacao) VALUES (?,?,?,?,?, 'ATIVO')",
        (codigo, nome, nome_social, turma, serie),
    ).lastrowid


def test_link_editar_nome_aparece_na_pagina_do_aluno(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "N1", "ALUNO TESTE")

    resp = client.get(f"/aluno/{aluno_id}")
    assert "Editar nome" in resp.get_data(as_text=True)


def test_corrigir_acento_no_nome_de_registro(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "N2", "JOAO SILVA")

    tok = pegar_csrf(f"/aluno/{aluno_id}/nome")
    resp = client.post(
        f"/aluno/{aluno_id}/nome",
        data={"csrf_token": tok, "nome": "JOÃO SILVA", "nome_social": ""},
        follow_redirects=True,
    )
    assert "atualizado" in resp.get_data(as_text=True).lower()

    with get_db() as db:
        aluno = db.execute("SELECT nome, nome_social FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["nome"] == "JOÃO SILVA"
    assert aluno["nome_social"] is None


def test_nome_vazio_mostra_erro(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "N3", "ALUNO TESTE 3")

    tok = pegar_csrf(f"/aluno/{aluno_id}/nome")
    resp = client.post(
        f"/aluno/{aluno_id}/nome",
        data={"csrf_token": tok, "nome": "", "nome_social": ""},
        follow_redirects=True,
    )
    assert "não pode ficar em branco" in resp.get_data(as_text=True)

    with get_db() as db:
        aluno = db.execute("SELECT nome FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["nome"] == "ALUNO TESTE 3"


def test_nome_social_aparece_no_cabecalho_e_nome_de_registro_fica_secundario(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "N4", "PEDRO SANTOS REGISTRO")

    tok = pegar_csrf(f"/aluno/{aluno_id}/nome")
    client.post(
        f"/aluno/{aluno_id}/nome",
        data={"csrf_token": tok, "nome": "PEDRO SANTOS REGISTRO", "nome_social": "ANA SANTOS"},
    )

    resp = client.get(f"/aluno/{aluno_id}")
    html = resp.get_data(as_text=True)
    assert "ANA SANTOS" in html
    assert "Nome de registro: PEDRO SANTOS REGISTRO" in html


def test_sem_nome_social_nao_mostra_linha_de_registro(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "N5", "ALUNO SEM NOME SOCIAL")

    resp = client.get(f"/aluno/{aluno_id}")
    assert "Nome de registro:" not in resp.get_data(as_text=True)


def test_turma_lista_com_nome_social(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "N6", "CARLOS REGISTRO", turma="7A", nome_social="BEATRIZ")
        _aluno(db, "N7", "OUTRO ALUNO", turma="7A")

    resp = client.get("/turma/7A")
    html = resp.get_data(as_text=True)
    assert "BEATRIZ" in html
    assert "CARLOS REGISTRO" not in html
    assert "OUTRO ALUNO" in html


def test_busca_global_encontra_por_nome_social_ou_registro_e_exibe_o_social(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "N8", "FELIPE REGISTRO SILVA", nome_social="LUIZA SILVA")

    r1 = client.get("/api/alunos?q=LUIZA")
    dados1 = r1.get_json()
    assert len(dados1) == 1
    assert dados1[0]["nome"] == "LUIZA SILVA"

    r2 = client.get("/api/alunos?q=FELIPE REGISTRO")
    dados2 = r2.get_json()
    assert len(dados2) == 1
    assert dados2[0]["nome"] == "LUIZA SILVA"


def test_busca_por_turma_encontra_por_nome_social(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "N9", "RAFAEL REGISTRO", turma="8A", nome_social="SOFIA")

    resp = client.get("/api/turma/8A/alunos?q=SOFIA")
    dados = resp.get_json()
    assert len(dados) == 1
    assert dados[0]["nome"] == "SOFIA"


def test_area_do_aluno_cumprimenta_com_nome_social(client, pegar_csrf, criar_admin):
    import re
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "N10", "GABRIEL REGISTRO", nome_social="LARISSA")

    html = client.get(f"/aluno/{aluno_id}").get_data(as_text=True)
    token = re.search(r'data-copiar="(\d{6})"', html).group(1)  # código fixo de 6 números na ficha

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    tok2 = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": tok2}, follow_redirects=True)
    assert "LARISSA" in r2.get_data(as_text=True)






def test_professor_nao_edita_nome(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        aluno_id = _aluno(db, "N13", "ALUNO TESTE 13")
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("prof10", hash_password("senha-professor-666"), "Professor Dez", "Sala", "professor"),
        )
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "prof10", "senha": "senha-professor-666", "csrf_token": tok})

    resp = client.get(f"/aluno/{aluno_id}/nome")
    assert resp.status_code == 403
