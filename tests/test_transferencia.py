"""
Testa marcar um aluno como transferido durante o ano letivo — e
reverter, caso tenha sido engano.
"""


def _aluno(db, codigo, nome, turma="5A", serie="5º Ano"):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?,?, 'ATIVO')",
        (codigo, nome, turma, serie),
    ).lastrowid


def test_botao_aparece_para_aluno_ativo(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR1", "ALUNO ATIVO")

    resp = client.get(f"/aluno/{aluno_id}")
    html = resp.get_data(as_text=True)
    assert "Marcar como transferido" in html
    assert "Reativar matrícula" not in html


def test_tela_de_transferencia_carrega(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR2", "ALUNO TESTE")

    resp = client.get(f"/aluno/{aluno_id}/transferir")
    assert resp.status_code == 200
    assert "Marcar como transferido" in resp.get_data(as_text=True)
    assert "Escola de destino" not in resp.get_data(as_text=True)


def test_transferir_sem_data_mostra_erro(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR3", "ALUNO TESTE 3")

    tok = pegar_csrf(f"/aluno/{aluno_id}/transferir")
    resp = client.post(
        f"/aluno/{aluno_id}/transferir",
        data={"csrf_token": tok, "data_transferencia": ""},
        follow_redirects=True,
    )
    assert "Informe a data" in resp.get_data(as_text=True)

    with get_db() as db:
        aluno = db.execute("SELECT situacao FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["situacao"] == "ATIVO"


def test_transferir_atualiza_situacao_e_data(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR4", "ALUNO TESTE 4")

    tok = pegar_csrf(f"/aluno/{aluno_id}/transferir")
    resp = client.post(
        f"/aluno/{aluno_id}/transferir",
        data={"csrf_token": tok, "data_transferencia": "2026-09-20"},
        follow_redirects=True,
    )
    assert "transferido" in resp.get_data(as_text=True).lower()

    with get_db() as db:
        aluno = db.execute(
            "SELECT situacao, data_transferencia FROM students WHERE id=?", (aluno_id,)
        ).fetchone()
    assert aluno["situacao"] == "TRANSFERIDO"
    assert aluno["data_transferencia"] == "2026-09-20"


def test_aluno_transferido_some_da_turma_mas_continua_na_busca(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR6", "ALUNO SUMIDO DA TURMA", turma="6B")
        _aluno(db, "TR7", "COLEGA DE TURMA", turma="6B")

    tok = pegar_csrf(f"/aluno/{aluno_id}/transferir")
    client.post(
        f"/aluno/{aluno_id}/transferir",
        data={"csrf_token": tok, "data_transferencia": "2026-09-20"},
        follow_redirects=True,  # consome a flash message aqui, não na consulta da turma
    )

    resp = client.get("/turma/6B")
    html = resp.get_data(as_text=True)
    assert "ALUNO SUMIDO DA TURMA" not in html
    assert "COLEGA DE TURMA" in html

    resp2 = client.get("/api/alunos?q=SUMIDO")
    dados = resp2.get_json()
    assert len(dados) == 1
    assert dados[0]["nome"] == "ALUNO SUMIDO DA TURMA"


def test_reativar_volta_a_ficar_ativo(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR8", "ALUNO PARA REATIVAR", turma="7A")

    tok = pegar_csrf(f"/aluno/{aluno_id}/transferir")
    client.post(
        f"/aluno/{aluno_id}/transferir",
        data={"csrf_token": tok, "data_transferencia": "2026-09-20"},
    )

    tok2 = pegar_csrf(f"/aluno/{aluno_id}")
    resp = client.post(f"/aluno/{aluno_id}/reativar", data={"csrf_token": tok2}, follow_redirects=True)
    assert "ativo" in resp.get_data(as_text=True).lower()

    with get_db() as db:
        aluno = db.execute(
            "SELECT situacao, data_transferencia FROM students WHERE id=?", (aluno_id,)
        ).fetchone()
    assert aluno["situacao"] == "ATIVO"
    assert aluno["data_transferencia"] is None

    resp2 = client.get("/turma/7A")
    assert "ALUNO PARA REATIVAR" in resp2.get_data(as_text=True)


def test_professor_nao_transfere_aluno(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        aluno_id = _aluno(db, "TR9", "ALUNO TESTE 9")
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("prof7", hash_password("senha-professor-222"), "Professor Sete", "Sala", "professor"),
        )
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "prof7", "senha": "senha-professor-222", "csrf_token": tok})

    resp = client.get(f"/aluno/{aluno_id}/transferir")
    assert resp.status_code == 403


def test_pagina_do_aluno_nao_fica_com_html_quebrado(client, pegar_csrf, criar_admin):
    """Regressão: uma </div> sobrando no cabeçalho fechava o <main> mais
    cedo, jogando o resto da página (foto, histórico, SPTrans etc.) pra
    fora da área de conteúdo — mesmo com o texto continuando presente no
    HTML, o que fazia os testes baseados só em 'texto está no HTML'
    passarem apesar do bug visual. Aqui conferimos a estrutura, não só o
    texto: cada seção precisa estar DENTRO do <main class="container">."""
    from bs4 import BeautifulSoup
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "TR10", "ALUNO TESTE ESTRUTURA")

    for situacao in ("ATIVO", "TRANSFERIDO"):
        with get_db() as db:
            db.execute(
                "UPDATE students SET situacao=?, data_transferencia=? WHERE id=?",
                (situacao, "2026-09-20" if situacao == "TRANSFERIDO" else None, aluno_id),
            )
        resp = client.get(f"/aluno/{aluno_id}")
        soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
        main = soup.find("main", class_="container")
        assert main is not None, f"main.container não encontrado (situação={situacao})"
        for titulo in ("Foto do aluno", "Acesso do responsável", "Situação da matrícula"):
            achado = main.find(lambda tag: tag.name == "h2" and tag.get_text(strip=True) == titulo)
            assert achado is not None, f"'{titulo}' não está dentro do container (situação={situacao})"
