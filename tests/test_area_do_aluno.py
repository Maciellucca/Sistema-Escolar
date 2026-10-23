"""
Testa a renomeação de "Boletim" para "Área do aluno" e os novos campos
de recomendações e pendências cadastrais.
"""
import re


def _aluno(db, codigo, nome, turma="1A"):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?, '1º Ano', 'ATIVO')",
        (codigo, nome, turma),
    ).lastrowid


def _token_responsavel(client, pegar_csrf, student_id):
    html = client.get(f"/aluno/{student_id}").get_data(as_text=True)
    return re.search(r'data-copiar="(\d{6})"', html).group(1)  # código fixo de 6 números na ficha


def test_login_do_responsavel_mostra_area_do_aluno(client, pegar_csrf, criar_admin):
    resp = client.get("/responsavel/")
    html = resp.get_data(as_text=True)
    assert "Área do aluno" in html
    assert "Boletim escolar" not in html


def test_tela_de_edicao_carrega(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "A1", "ALUNO TESTE")

    resp = client.get(f"/aluno/{aluno_id}/area-do-aluno")
    assert resp.status_code == 200
    assert "<h1>Pendências cadastrais</h1>" in resp.get_data(as_text=True)  # recomendações saíram desta tela


def test_salvar_recomendacoes_e_pendencias(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "A2", "ALUNO TESTE 2")

    tok = pegar_csrf(f"/aluno/{aluno_id}/area-do-aluno")
    resp = client.post(
        f"/aluno/{aluno_id}/area-do-aluno",
        data={"csrf_token": tok, "alteracoes_pendentes": "Atualizar telefone de contato."},
        follow_redirects=True,
    )
    assert "Pendências cadastrais atualizadas" in resp.get_data(as_text=True)
    # recomendação geral agora é salva na aba Boletim & Frequência
    resp = client.post(f"/aluno/{aluno_id}/recomendacao",
                       data={"csrf_token": tok, "texto": "Incentivar leitura em casa."}, follow_redirects=True)
    assert "Recomendação (geral) salva" in resp.get_data(as_text=True)

    with get_db() as db:
        aluno = db.execute("SELECT recomendacoes, alteracoes_pendentes FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["recomendacoes"] == "Incentivar leitura em casa."
    assert aluno["alteracoes_pendentes"] == "Atualizar telefone de contato."


def test_responsavel_ve_recomendacoes_e_pendencias(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "A3", "ALUNO TESTE 3")

    tok = pegar_csrf(f"/aluno/{aluno_id}/area-do-aluno")
    client.post(f"/aluno/{aluno_id}/area-do-aluno", data={"csrf_token": tok, "alteracoes_pendentes": "Pendência de teste"})
    client.post(f"/aluno/{aluno_id}/recomendacao", data={"csrf_token": tok, "texto": "Recomendação de teste"})

    token = _token_responsavel(client, pegar_csrf, aluno_id)

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    tok2 = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": tok2}, follow_redirects=True)
    html = r2.get_data(as_text=True)

    assert "Recomendação de teste" in html
    assert "Pendência de teste" in html
    assert "Pendências cadastrais" in html
    assert "Área do aluno" in html


def test_sem_recomendacao_ou_pendencia_nao_mostra_secao(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "A4", "ALUNO SEM NADA")

    token = _token_responsavel(client, pegar_csrf, aluno_id)

    from app import app
    c2 = app.test_client()
    r = c2.get("/responsavel/")
    tok = re.search(r'name="csrf_token" value="([^"]+)"', r.get_data(as_text=True)).group(1)
    r2 = c2.post("/responsavel/", data={"token": token, "csrf_token": tok}, follow_redirects=True)
    html = r2.get_data(as_text=True)

    assert "Pendências cadastrais" not in html
    assert "Recomendações gerais da escola" not in html
    assert "conselho de classe" not in html


def test_professor_pode_editar_area_do_aluno(client, pegar_csrf, criar_admin):
    """Diferente de SPTrans/telefones (admin+secretaria só), professor
    também deve poder registrar recomendações."""
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        aluno_id = _aluno(db, "A5", "ALUNO TESTE 5")
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("prof6", hash_password("senha-professor-111"), "Professor Seis", "Sala", "professor"),
        )
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "prof6", "senha": "senha-professor-111", "csrf_token": tok})

    resp = client.get(f"/aluno/{aluno_id}/area-do-aluno")
    assert resp.status_code == 200


def test_boletim_do_responsavel_resumo_cores_e_ultimo_bimestre(client, pegar_csrf, criar_admin):
    """Área do responsável: abre no bimestre mais recente, mostra o resumo
    (frequência média, faltas, componentes com P), destaca frequência
    abaixo de 75%, recolhe componentes sem lançamento e traz o contato."""
    from bs4 import BeautifulSoup
    from models import get_db
    with get_db() as db:
        aluno_id = db.execute(
            "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('RB1','ALUNO RESUMO','1A','1º Ano','ATIVO')"
        ).lastrowid
        linhas = [
            (1, "Arte", "S", 1, 0, 95.0), (2, "Arte", "S", 2, 0, 90.0),
            (2, "Matemática", "NS", 12, 0, 70.0), (2, "Inglês", "P", 4, 2, 90.0),
            (2, "Sala de leitura", None, None, None, None),
        ]
        for bim, disc, conceito, faltas, comp, freq in linhas:
            db.execute("""INSERT INTO grades (student_id, ano, bimestre, disciplina, conceito, faltas, compensacoes, frequencia)
                          VALUES (?, 2026, ?, ?, ?, ?, ?, ?)""", (aluno_id, bim, disc, conceito, faltas, comp, freq))
    token = _token_responsavel(client, pegar_csrf, aluno_id)
    responsavel = client.application.test_client()
    soup = BeautifulSoup(responsavel.get("/responsavel/").get_data(as_text=True), "html.parser")
    tok = soup.find("input", {"name": "csrf_token"})["value"]
    html = responsavel.post("/responsavel/", data={"token": token, "csrf_token": tok}, follow_redirects=True).get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")

    assert soup.select_one(".pilula.ativa").get_text(strip=True) == "2º Bimestre"  # mais recente aberto
    painel = soup.select_one('[data-tab-panel="2026-2"]')
    assert not painel.has_attr("hidden")
    valores = [v.get_text(strip=True) for v in painel.select(".resumo-valor")]
    assert valores == ["83.3%", "18", "1"]  # média (90+70+90)/3, faltas 2+12+4, 1 componente com NS
    assert painel.select_one(".freq-baixa").get_text(strip=True) == "70.0%"
    assert painel.select_one(".conceito-ns").get_text(strip=True) == "NS"
    assert painel.select_one(".conceito-ns")["title"] == "Não satisfatório"
    assert painel.select_one(".conceito-p")["title"] == "Plenamente satisfatório"
    assert "Plenamente satisfatório" in painel.parent.select_one(".boletim-legenda").get_text()
    assert "Parcialmente" not in html
    assert "Sala de leitura" not in painel.select_one("tbody").get_text()  # vazio fica recolhido
    assert "Sala de leitura" in painel.select_one(".boletim-vazios").get_text()
    assert "Fale com a escola" in html and "0000-0000" in html
    assert "Imprimir boletim" in html


def test_recomendacao_do_conselho_por_bimestre(client, pegar_csrf, criar_admin):
    """Recomendação do conselho de classe fica em cada bimestre da aba
    Boletim & Frequência (editável por admin/secretaria/professor) e aparece
    para o responsável no mesmo bimestre."""
    from bs4 import BeautifulSoup
    from models import get_db
    from auth import hash_password
    with get_db() as db:
        aluno_id = _aluno(db, "CC1", "ALUNO CONSELHO")
        for bim in (1, 2):
            db.execute("INSERT INTO grades (student_id, ano, bimestre, disciplina, conceito, faltas, frequencia) VALUES (?, 2026, ?, 'Arte', 'S', 1, 95.0)",
                       (aluno_id, bim))
        db.execute("INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
                   ("coord", hash_password("senha-coord-1234"), "Coordenadora Ana", "Coordenação", "professor"))

    # coordenação (perfil professor) salva a recomendação do 2º bimestre, via tela (fetch)
    client.get("/logout")
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "coord", "senha": "senha-coord-1234", "csrf_token": tok})
    soup = BeautifulSoup(client.get(f"/aluno/{aluno_id}").get_data(as_text=True), "html.parser")
    painel2 = soup.select_one('[data-tab-panel="2026-2"]')
    form = painel2.select_one("form.recomendacao-bimestre")
    assert form is not None and form.select_one('input[name="bimestre"]')["value"] == "2"
    dados = client.post(f"/aluno/{aluno_id}/recomendacao", headers={"X-Requested-With": "fetch"}, data={
        "csrf_token": form.select_one('input[name="csrf_token"]')["value"], "ano": "2026", "bimestre": "2",
        "texto": "Avançou na leitura; reforçar tabuada em casa.",
    }).get_json()
    assert dados["ok"] and dados["autor"] == "Coordenadora Ana"

    soup = BeautifulSoup(client.get(f"/aluno/{aluno_id}").get_data(as_text=True), "html.parser")
    assert "reforçar tabuada" in soup.select_one('[data-tab-panel="2026-2"] textarea').get_text()
    assert soup.select_one('[data-tab-panel="2026-1"] textarea').get_text().strip() == ""

    # responsável vê no 2º bimestre
    with get_db() as db:
        from auth import codigo_responsavel
        token = codigo_responsavel(db, aluno_id)
    from app import app
    c2 = app.test_client()
    tok2 = re.search(r'name="csrf_token" value="([^"]+)"', c2.get("/responsavel/").get_data(as_text=True)).group(1)
    html = c2.post("/responsavel/", data={"token": token, "csrf_token": tok2}, follow_redirects=True).get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")
    assert "reforçar tabuada" in soup.select_one('[data-tab-panel="2026-2"]').get_text()
    assert "conselho de classe" not in soup.select_one('[data-tab-panel="2026-1"]').get_text()
    assert soup.select_one("form.recomendacao-bimestre") is None  # responsável só lê

    # texto vazio apaga
    client.post(f"/aluno/{aluno_id}/recomendacao", data={
        "csrf_token": pegar_csrf(f"/aluno/{aluno_id}"), "ano": "2026", "bimestre": "2", "texto": ""})
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) FROM recomendacoes_bimestre").fetchone()[0] == 0


def test_aee_nao_edita_recomendacao(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password
    with get_db() as db:
        aluno_id = _aluno(db, "CC2", "ALUNO AEE")
        db.execute("INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
                   ("aee1", hash_password("senha-aee-12345"), "AEE", "AEE", "aee"))
    client.get("/logout")
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "aee1", "senha": "senha-aee-12345", "csrf_token": tok})
    tok = pegar_csrf(f"/aluno/{aluno_id}")
    assert "recomendacao-bimestre" not in client.get(f"/aluno/{aluno_id}").get_data(as_text=True)
    assert client.post(f"/aluno/{aluno_id}/recomendacao", data={"csrf_token": tok, "texto": "x"}).status_code == 403
