"""
Testa a busca de aluno e o agrupamento de turmas em gavetas
(turno -> série) no painel principal.
"""
from bs4 import BeautifulSoup


def _aluno(db, codigo, nome, turma, serie):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?,?, 'ATIVO')",
        (codigo, nome, turma, serie),
    ).lastrowid


def test_campo_de_busca_presente(client, pegar_csrf, criar_admin):
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert 'id="busca-aluno-dashboard"' in html


def test_turmas_aparecem_em_gaveta_details(client, pegar_csrf, criar_admin):
    from models import get_db, salvar_turma_turno

    with get_db() as db:
        _aluno(db, "D1", "ALUNO QUARTO ANO", "4A", "4º Ano")
        salvar_turma_turno(db, "4A", "Manhã")

    resp = client.get("/")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    gavetas = soup.find_all("details", class_="turno-gaveta")
    assert len(gavetas) >= 1
    nomes = [g.find("span", class_="turno-gaveta-nome").get_text(strip=True) for g in gavetas]
    assert "Manhã" in nomes


def test_gaveta_fechada_mostra_resumo_sem_listar_turmas_no_texto_visivel(client, pegar_csrf, criar_admin):
    """A gaveta em si é sempre renderizada no HTML (details/summary não
    removem o conteúdo do DOM), mas o resumo (contagem) tem que aparecer
    no <summary>, fora do <div> que só é revelado ao abrir."""
    from models import get_db, salvar_turma_turno

    with get_db() as db:
        _aluno(db, "D2", "ALUNO QUINTO ANO", "5A", "5º Ano")
        _aluno(db, "D3", "ALUNO QUINTO ANO B", "5A", "5º Ano")
        salvar_turma_turno(db, "5A", "Manhã")

    resp = client.get("/")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    gaveta = soup.find("details", class_="turno-gaveta")
    resumo = gaveta.find("summary").get_text()
    assert "2 turma(s)" not in resumo  # só 1 turma (5A) nesse turno
    assert "1 turma(s)" in resumo
    assert "2 aluno(s)" in resumo


def test_turmas_separadas_por_serie_dentro_do_turno(client, pegar_csrf, criar_admin):
    from models import get_db, salvar_turma_turno

    with get_db() as db:
        _aluno(db, "D4", "ALUNO A", "4A", "4º Ano")
        _aluno(db, "D5", "ALUNO B", "5A", "5º Ano")
        salvar_turma_turno(db, "4A", "Manhã")
        salvar_turma_turno(db, "5A", "Manhã")

    resp = client.get("/")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    gaveta = soup.find("details", class_="turno-gaveta")
    rotulos = [s.get_text(strip=True) for s in gaveta.find_all("span", class_="serie-rotulo")]
    assert "4º Ano" in rotulos
    assert "5º Ano" in rotulos
    assert rotulos.index("4º Ano") < rotulos.index("5º Ano")


def test_turma_sem_turno_fica_em_gaveta_separada(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "D6", "ALUNO SEM TURNO", "9Z", "9º Ano")

    resp = client.get("/")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    gavetas = soup.find_all("details", class_="turno-gaveta")
    nomes = [g.find("span", class_="turno-gaveta-nome").get_text(strip=True) for g in gavetas]
    assert "Turno não definido" in nomes


def test_busca_via_api_usada_pelo_dashboard(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "D7", "ALUNO PROCURADO SILVA", "6A", "6º Ano")

    resp = client.get("/api/alunos?q=PROCURADO")
    dados = resp.get_json()
    assert len(dados) == 1
    assert dados[0]["nome"] == "ALUNO PROCURADO SILVA"
    assert dados[0]["turma"] == "6A"


def test_inicio_nao_mostra_progresso_de_notas(client, pegar_csrf, criar_admin):
    html = client.get("/").get_data(as_text=True)
    assert "Notas lançadas" not in html
    assert "barra-progresso" not in html
