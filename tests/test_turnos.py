"""
Testa o agrupamento de turmas por turno (Manhã/Integral/Tarde) no painel
principal, e a tela de configuração que define o turno de cada turma.
"""


def _aluno(db, codigo, nome, turma):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?, '1º Ano', 'ATIVO')",
        (codigo, nome, turma),
    ).lastrowid


def test_turma_sem_turno_aparece_em_nao_definido(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "TU1", "ALUNO SEM TURNO", "5A")

    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "Turno não definido" in html
    assert "5A" in html


def test_turma_com_turno_aparece_na_secao_certa(client, pegar_csrf, criar_admin):
    from bs4 import BeautifulSoup
    from models import get_db, salvar_turma_turno

    with get_db() as db:
        _aluno(db, "TU2", "ALUNO MANHA", "6A")
        salvar_turma_turno(db, "6A", "Manhã")

    resp = client.get("/")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    # painel: uma "gaveta" (<details class="turno-gaveta">) por turno, com as
    # turmas em pílulas agrupadas por série dentro dela
    gaveta = soup.find("details", class_="turno-gaveta")
    assert gaveta is not None
    assert gaveta.find(class_="turno-gaveta-nome").get_text(strip=True) == "Manhã"
    assert "6A" in gaveta.find("div", class_="turno-gaveta-conteudo").get_text()


def test_tela_de_configuracao_carrega_com_turno_atual_selecionado(client, pegar_csrf, criar_admin):
    from models import get_db, salvar_turma_turno

    with get_db() as db:
        _aluno(db, "TU3", "ALUNO INTEGRAL", "2A")
        salvar_turma_turno(db, "2A", "Integral")

    resp = client.get("/turmas/turnos")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<option value="Integral" selected>' in html


def test_salvar_turno_via_formulario(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "TU4", "ALUNO TESTE", "7A")

    tok = pegar_csrf("/turmas/turnos")
    resp = client.post(
        "/turmas/turnos",
        data={"csrf_token": tok, "turma": ["7A"], "turno::7A": "Tarde"},
        follow_redirects=True,
    )
    assert "atualizados" in resp.get_data(as_text=True).lower()

    with get_db() as db:
        t = db.execute("SELECT turno FROM turma_turno WHERE turma='7A'").fetchone()
    assert t["turno"] == "Tarde"


def test_limpar_turno_remove_a_configuracao(client, pegar_csrf, criar_admin):
    from models import get_db, salvar_turma_turno

    with get_db() as db:
        _aluno(db, "TU5", "ALUNO TESTE 2", "3A")
        salvar_turma_turno(db, "3A", "Integral")

    tok = pegar_csrf("/turmas/turnos")
    client.post("/turmas/turnos", data={"csrf_token": tok, "turma": ["3A"], "turno::3A": ""})

    with get_db() as db:
        t = db.execute("SELECT turno FROM turma_turno WHERE turma='3A'").fetchone()
    assert t is None

    resp = client.get("/")
    assert "Turno não definido" in resp.get_data(as_text=True)


def test_todas_as_turmas_do_exemplo_real_ficam_nos_turnos_certos(client, pegar_csrf, criar_admin):
    """Reproduz o mapeamento real informado pela escola, garantindo que
    nenhuma turma some e todas ficam agrupadas certo."""
    from bs4 import BeautifulSoup
    from models import get_db, salvar_turma_turno

    manha = ["4A", "4B", "4C", "5A", "5B", "6A", "6B", "6C", "6D", "6E", "8A", "8B", "8C", "9A", "9B", "9C"]
    integral = ["1A", "1B", "1C", "1D", "2A", "2B", "2C", "2D", "3A", "3B", "3C", "3D"]
    tarde = ["7A", "7B", "7C", "7D"]

    with get_db() as db:
        for i, turma in enumerate(manha + integral + tarde):
            _aluno(db, f"R{i}", f"ALUNO {turma}", turma)
        for t in manha:
            salvar_turma_turno(db, t, "Manhã")
        for t in integral:
            salvar_turma_turno(db, t, "Integral")
        for t in tarde:
            salvar_turma_turno(db, t, "Tarde")

    resp = client.get("/")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    assert "Turno não definido" not in soup.get_text()

    turma_por_secao = {}
    for gaveta in soup.find_all("details", class_="turno-gaveta"):
        nome_secao = gaveta.find(class_="turno-gaveta-nome").get_text(strip=True)
        for link in gaveta.find_all("a", class_="pilula"):
            turma_nome = link.get_text(strip=True).split("(")[0].strip()
            turma_por_secao[turma_nome] = nome_secao

    for t in manha:
        assert turma_por_secao.get(t) == "Manhã", f"{t} não está na seção Manhã"
    for t in integral:
        assert turma_por_secao.get(t) == "Integral", f"{t} não está na seção Integral"
    for t in tarde:
        assert turma_por_secao.get(t) == "Tarde", f"{t} não está na seção Tarde"
