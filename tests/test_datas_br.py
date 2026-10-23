"""Datas aparecem no formato da escola (dd/mm/aaaa) em todas as telas; no
banco continuam em aaaa-mm-dd."""
import re

import pytest
from bs4 import BeautifulSoup

ISO = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")


def test_filtros():
    from datetime import date, datetime
    from datas import data_br, data_hora_br
    assert data_br("2018-06-26") == "26/06/2018"
    assert data_br("2018-06-26 10:00:00") == "26/06/2018"
    assert data_br(date(2018, 6, 26)) == "26/06/2018" and data_br(datetime(2018, 6, 26, 9)) == "26/06/2018"
    assert data_br("26/06/2018") == "26/06/2018"  # já no formato: fica igual
    assert data_br(None) == "" and data_br("", "—") == "—"
    assert data_hora_br("2026-10-06 14:30:00") == "06/10/2026 14:30"
    assert data_hora_br("2026-10-06T08:05") == "06/10/2026 08:05"
    assert data_hora_br("2026-10-06") == "06/10/2026"


def _texto_visivel(html):
    """Texto que a pessoa lê na tela (sem valores de campos, links, scripts)."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "input", "select", "textarea", "template"]):
        tag.decompose()
    return soup.get_text(" ")


@pytest.fixture()
def dados(client, criar_admin):
    from models import get_db, agora
    with get_db() as db:
        sid = db.execute(
            """INSERT INTO students (nome, turma, serie, situacao, data_nascimento, rg, rg_data_expedicao,
                                     codigo_interno, filiacao1) VALUES ('ALUNA FICTICIA','2A','2º Ano','ATIVO',
                                     '2018-06-26','12.345.678','2020-03-15','990001','MAE FICTICIA')""").lastrowid
        tid = db.execute(
            """INSERT INTO students (nome, turma, situacao, data_nascimento, data_transferencia)
               VALUES ('ALUNO TRANSFERIDO','2A','TRANSFERIDO','2017-01-05','2026-08-10')""").lastrowid
    return {"sid": sid, "tid": tid}


def test_telas_sem_data_aaaa_mm_dd(client, dados):
    paginas = [
        f"/aluno/{dados['sid']}", f"/aluno/{dados['tid']}", "/turma/2A",
        "/arquivo-morto/", "/importar/alunos", "/importar/notas", "/",
    ]
    vistas = 0
    for url in paginas:
        resp = client.get(url, follow_redirects=True)
        if resp.status_code != 200:
            continue
        vistas += 1
        texto = _texto_visivel(resp.get_data(as_text=True))
        achadas = ISO.findall(texto)
        assert not achadas, f"{url}: {[m.group(0) for m in ISO.finditer(texto)]}"
    assert vistas >= 6
    ficha = _texto_visivel(client.get(f"/aluno/{dados['sid']}").get_data(as_text=True))
    assert "26/06/2018" in ficha and "15/03/2020" in ficha
    assert "10/08/2026" in _texto_visivel(client.get(f"/aluno/{dados['tid']}").get_data(as_text=True))
