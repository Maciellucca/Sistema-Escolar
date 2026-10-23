"""
Testa a exibição de cursos recomendados no portal do responsável,
filtrados pelo ciclo do aluno (calculado a partir da série).
"""
import re


def _aluno(db, codigo, nome, turma, serie):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?,?, 'ATIVO')",
        (codigo, nome, turma, serie),
    ).lastrowid


def _token_responsavel(client, pegar_csrf, student_id):
    html = client.get(f"/aluno/{student_id}").get_data(as_text=True)
    return re.search(r'data-copiar="(\d{6})"', html).group(1)  # código fixo de 6 números na ficha


def test_ciclo_da_serie_mapeia_corretamente():
    from routes.cursos import ciclo_da_serie

    assert ciclo_da_serie("1º Ano") == "Alfabetização"
    assert ciclo_da_serie("3º Ano") == "Alfabetização"
    assert ciclo_da_serie("4º Ano") == "Interdisciplinar"
    assert ciclo_da_serie("6º Ano") == "Interdisciplinar"
    assert ciclo_da_serie("7º Ano") == "Autoral"
    assert ciclo_da_serie("9º Ano") == "Autoral"
    assert ciclo_da_serie(None) is None
    assert ciclo_da_serie("") is None
    assert ciclo_da_serie("Ensino Médio") is None


def test_responsavel_ve_cursos_do_ciclo_do_filho(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "C1", "ALUNO OITAVO ANO", "8A", "8º Ano")
        db.execute("INSERT INTO cursos_recomendados (titulo, ciclo, ativo) VALUES ('Curso Autoral', 'Autoral', 1)")

    token = _token_responsavel(client, pegar_csrf, aluno_id)

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    soup_tok = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": soup_tok}, follow_redirects=True)
    html = r2.get_data(as_text=True)

    assert "Cursos gratuitos recomendados" in html
    assert "Curso Autoral" in html
    assert "Autoral" in html


def test_responsavel_nao_ve_curso_de_outro_ciclo(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "C2", "ALUNO PRIMEIRO ANO", "1A", "1º Ano")
        db.execute("INSERT INTO cursos_recomendados (titulo, ciclo, ativo) VALUES ('Curso Autoral', 'Autoral', 1)")
        db.execute(
            "INSERT INTO cursos_recomendados (titulo, ciclo, ativo) VALUES ('Curso Alfabetização', 'Alfabetização', 1)"
        )

    token = _token_responsavel(client, pegar_csrf, aluno_id)

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    soup_tok = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": soup_tok}, follow_redirects=True)
    html = r2.get_data(as_text=True)

    assert "Curso Alfabetização" in html
    assert "Curso Autoral" not in html


def test_responsavel_nao_ve_curso_inativo(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "C3", "ALUNO SEXTO ANO", "6A", "6º Ano")
        db.execute(
            "INSERT INTO cursos_recomendados (titulo, ciclo, ativo) VALUES ('Curso Inativo', 'Interdisciplinar', 0)"
        )

    token = _token_responsavel(client, pegar_csrf, aluno_id)

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    soup_tok = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": soup_tok}, follow_redirects=True)
    html = r2.get_data(as_text=True)

    assert "Curso Inativo" not in html


def test_sem_curso_no_ciclo_nao_mostra_secao(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "C4", "ALUNO SEM CURSO", "5A", "5º Ano")

    token = _token_responsavel(client, pegar_csrf, aluno_id)

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    soup_tok = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": soup_tok}, follow_redirects=True)
    html = r2.get_data(as_text=True)

    assert "Cursos gratuitos recomendados" not in html
