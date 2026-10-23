"""
Turma de projeto importada do relatório "Alunos da Turma" do SGP (.xls que
é HTML por dentro): turma = Turma + Descrição, turno sem a duração, alunos
ligados pelo código EOL sem mudar a turma regular.
"""
import io

CABECALHO = (
    "<table width=100% border=1>"
    "<tr><td><b>Unidade</b></td><td colspan=7>000000 - EMEF - ESCOLA TESTE</td></tr>"
    "<tr><td><b>Turma</b></td><td>3167035 - LE</td><td><b>Situação</b></td><td>Organizada</td>"
    "<td><b>Ano Letivo</b></td><td>2026</td><td><b>Turno/Duração</b></td><td>Manhã 01:30h</td></tr>"
    "<tr><td><b>Descrição</b></td><td colspan=7>APRENDER E ENSINAR / PAP / PAP COLABORATIVO 3 4 E 5 ANO</td></tr>"
    "<tr><td colspan=8></td></tr>"
    "<tr><td>Código</td><td>RA Prodesp</td><td>Código INEP</td><td>Nº</td><td>Nome do Aluno</td>"
    "<td>Filiação 1</td><td>Data Nascimento</td><td>Data Inclusão Aluno Turma</td><td>Data Matrícula</td>"
    "<td>P.C.</td><td>Situação Aluno</td><td>Origem Matrícula</td><td>Série</td><td>Utiliz. T.E.G.</td></tr>"
)


def _linha(codigo, numero, nome, situacao):
    return (f"<tr><td>{codigo}</td><td>RA</td><td>INEP</td><td>{numero}</td><td>{nome}</td><td>MAE</td>"
            f"<td>01/01/2016</td><td>02/04/2026</td><td>02/04/2026</td><td></td><td>{situacao}</td>"
            f"<td>INICIAL</td><td></td><td></td></tr>")


def _arquivo(linhas):
    html = CABECALHO + "".join(linhas) + "</table>"
    return io.BytesIO(html.encode("cp1252"))


def _alunos(db):
    ana = db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('900001','ANA TESTE','3A','3º Ano','ATIVO')"
    ).lastrowid
    bia = db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('900002','BIA TESTE','4B','4º Ano','ATIVO')"
    ).lastrowid
    return ana, bia


def _enviar(client, pegar_csrf, arquivo, nome="AlunosDaTurma_1.xls"):
    tok = pegar_csrf("/importar/alunos")
    return client.post(
        "/importar/alunos/upload-projeto", data={"csrf_token": tok, "planilha": (arquivo, nome)},
        content_type="multipart/form-data", follow_redirects=True,
    )


def test_importa_turma_de_projeto_do_sgp(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        ana, bia = _alunos(db)

    resp = _enviar(client, pegar_csrf, _arquivo([
        _linha("900001", "001", "ANA TESTE", "ATIVO"),
        _linha("900002", "002", "BIA TESTE", "VÍNCULO INDEVIDO"),
        _linha("900003", "003", "CAIO FORA DO SISTEMA", "ATIVO"),
    ]))
    html = resp.get_data(as_text=True)
    nome = "3167035 - LE - APRENDER E ENSINAR / PAP / PAP COLABORATIVO 3 4 E 5 ANO"
    assert resp.status_code == 200
    assert nome in html and "Turma de projeto criada" in html
    assert "Turno: <strong>Manhã</strong>" in html  # sem a duração
    assert "2 ativo(s)" in html and "2 ligado(s) ao cadastro" in html
    assert "sem cadastro" in html and "CAIO FORA DO SISTEMA" in html
    assert "Outras situações" in html and "VÍNCULO INDEVIDO" in html

    with get_db() as db:
        p = db.execute("SELECT * FROM turmas_projeto").fetchone()
        assert (p["codigo"], p["nome"], p["turno"], p["ano"]) == ("3167035", nome, "Manhã", 2026)
        # a turma regular não muda
        assert db.execute("SELECT turma FROM students WHERE id = ?", (ana,)).fetchone()["turma"] == "3A"
        assert db.execute("SELECT turma FROM students WHERE id = ?", (bia,)).fetchone()["turma"] == "4B"

    inicio = client.get("/").get_data(as_text=True)
    assert "Projetos" in inicio and f"/projeto/{p['id']}" in inicio and "3167035 - LE" in inicio


def test_reimportar_atualiza_a_lista(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _alunos(db)
    _enviar(client, pegar_csrf, _arquivo([_linha("900001", "001", "ANA TESTE", "ATIVO"),
                                          _linha("900002", "002", "BIA TESTE", "ATIVO")]))
    resp = _enviar(client, pegar_csrf, _arquivo([_linha("900002", "001", "BIA TESTE", "ATIVO")]))
    assert "Turma de projeto atualizada" in resp.get_data(as_text=True)
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM turmas_projeto").fetchone()["n"] == 1
        codigos = [r["codigo_eol"] for r in db.execute("SELECT codigo_eol FROM turma_projeto_alunos").fetchall()]
    assert codigos == ["900002"]


def test_aceita_xlsx_e_recusa_arquivo_errado(client, pegar_csrf, criar_admin):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Unidade", "000000 - EMEF"])
    ws.append(["Turma", "4000001 - AB", "Situação", "Organizada", "Ano Letivo", 2026, "Turno/Duração", "Tarde 02:00h"])
    ws.append(["Descrição", "PROJETO DE LEITURA"])
    ws.append([])
    ws.append(["Código", "RA Prodesp", "Código INEP", "Nº", "Nome do Aluno", "Situação Aluno"])
    ws.append([900009, "RA", "INEP", "001", "DUDA XLSX", "ATIVO"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    html = _enviar(client, pegar_csrf, buf, "turma.xlsx").get_data(as_text=True)
    assert "4000001 - AB - PROJETO DE LEITURA" in html and "Turno: <strong>Tarde</strong>" in html

    html = _enviar(client, pegar_csrf, io.BytesIO(b"<table><tr><td>qualquer</td></tr></table>")).get_data(as_text=True)
    assert "Não encontrei a turma" in html


def test_excluir_turma_de_projeto(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _alunos(db)
    _enviar(client, pegar_csrf, _arquivo([_linha("900001", "001", "ANA TESTE", "ATIVO")]))
    with get_db() as db:
        pid = db.execute("SELECT id FROM turmas_projeto").fetchone()["id"]
    tok = pegar_csrf(f"/projeto/{pid}")
    html = client.post(f"/projeto/{pid}/excluir", data={"csrf_token": tok}, follow_redirects=True).get_data(as_text=True)
    assert "excluída" in html
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM turma_projeto_alunos").fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"] == 2


def test_turno_sem_duracao():
    from scripts.import_turma_projeto import turno_sem_duracao

    assert turno_sem_duracao("Manhã 01:30h") == "Manhã"
    assert turno_sem_duracao("Tarde 2:00") == "Tarde"
    assert turno_sem_duracao("Integral") == "Integral"
