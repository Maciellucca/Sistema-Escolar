"""
Coluna lateral da ficha do aluno com os alunos ativos da turma (como um
diário de classe), com nº de chamada, destaque no aluno aberto e botões
Anterior/Próximo.
"""
from bs4 import BeautifulSoup


def _aluno(db, codigo, nome, turma="4A", situacao="ATIVO", aee=0):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao, aee) VALUES (?,?,?, '4º Ano', ?, ?)",
        (codigo, nome, turma, situacao, aee),
    ).lastrowid


def test_coluna_lista_a_turma_com_numero_e_destaque(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        c = _aluno(db, "F3", "CARLOS LIMA")
        a = _aluno(db, "F1", "ANA SOUZA", aee=1)
        b = _aluno(db, "F2", "BRUNO ALVES")
        _aluno(db, "F4", "DANI TRANSFERIDA", situacao="TRANSFERIDO")
        _aluno(db, "F5", "OUTRA TURMA", turma="5B")

    soup = BeautifulSoup(client.get(f"/aluno/{b}").get_data(as_text=True), "html.parser")
    coluna = soup.find("aside", id="ficha-turma")
    assert "Turma 4A" in coluna.get_text() and "3 aluno(s)" in coluna.get_text()
    itens = coluna.select(".ficha-turma-lista a")
    nomes = [i.select_one(".ficha-turma-nome").get_text(strip=True) for i in itens]
    assert nomes == ["ANA SOUZA", "BRUNO ALVES", "CARLOS LIMA"]  # ordem de chamada
    assert [i.select_one(".ficha-turma-num").get_text() for i in itens] == ["1", "2", "3"]
    assert itens[1].get("aria-current") == "page" and "atual" in itens[1]["class"]
    assert itens[0].select_one(".ficha-turma-aee")
    assert itens[2]["href"].endswith(f"/aluno/{c}")
    vizinhos = soup.select(".ficha-vizinhos a")
    assert [v.get_text(strip=True) for v in vizinhos] == ["‹ Anterior", "Próximo ›"]
    assert vizinhos[0]["href"].endswith(f"/aluno/{a}") and vizinhos[1]["href"].endswith(f"/aluno/{c}")
    assert "js/ficha_turma.js" in str(soup)


def test_primeiro_sem_anterior_e_inativo_aparece_no_fim(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        a = _aluno(db, "G1", "ANA SOUZA")
        _aluno(db, "G2", "BRUNO ALVES")
        t = _aluno(db, "G3", "DANI TRANSFERIDA", situacao="TRANSFERIDO")

    soup = BeautifulSoup(client.get(f"/aluno/{a}").get_data(as_text=True), "html.parser")
    assert [v.get_text(strip=True) for v in soup.select(".ficha-vizinhos a")] == ["Próximo ›"]

    soup = BeautifulSoup(client.get(f"/aluno/{t}").get_data(as_text=True), "html.parser")
    itens = soup.select("#ficha-turma .ficha-turma-lista a")
    assert len(itens) == 3 and itens[-1].select_one(".ficha-turma-num").get_text() == "—"
    assert "atual" in itens[-1]["class"]
    assert not soup.select(".ficha-vizinhos")
