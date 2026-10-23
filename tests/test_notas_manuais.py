"""Lançamento manual de notas na ficha do aluno e troca de turma pela
coluna lateral da ficha."""
from bs4 import BeautifulSoup


def _aluno(db, nome, turma):
    return db.execute("INSERT INTO students (nome, turma, situacao) VALUES (?, ?, 'ATIVO')", (nome, turma)).lastrowid


def test_lanca_corrige_e_apaga_notas(client, pegar_csrf, criar_admin):
    from models import get_db, salvar_nota
    with get_db() as db:
        sid = _aluno(db, "AGATHA FICTICIA", "2A")
        colega = _aluno(db, "BRUNO FICTICIO", "2A")
        # a turma já tem notas importadas: os componentes vêm delas
        for d in ("Arte", "Matemática"):
            salvar_nota(db, colega, 2026, 2, d, 1, 0, 98.0, "P", "REGISTRADO", "importado_pdf")
    url = f"/aluno/{sid}/notas?ano=2026&bimestre=2"
    html = client.get(url).get_data(as_text=True)
    assert "Arte" in html and "Matemática" in html and "Geografia" not in html
    tok = pegar_csrf(url)
    resp = client.post(f"/aluno/{sid}/notas", data={
        "csrf_token": tok, "ano": "2026", "bimestre": "2",
        "faltas::0": "3", "comp::0": "1", "freq::0": "95,5", "conc::0": "s",
        "faltas::1": "", "comp::1": "", "freq::1": "", "conc::1": "",
        "nova_disciplina": "Sala de leitura", "faltas::nova": "0", "conc::nova": "P"})
    assert resp.status_code == 302
    with get_db() as db:
        notas = {r["disciplina"]: r for r in db.execute(
            "SELECT * FROM grades WHERE student_id = ? AND ano = 2026 AND bimestre = 2", (sid,)).fetchall()}
    assert set(notas) == {"Arte", "Sala de leitura"}
    a = notas["Arte"]
    assert (a["faltas"], a["compensacoes"], a["frequencia"], a["conceito"], a["origem"]) == (3, 1, 95.5, "S", "manual")
    ficha = client.get(f"/aluno/{sid}").get_data(as_text=True)
    assert "Lançar notas manualmente" in ficha and "Sala de leitura" in ficha
    # deixar a linha em branco apaga o componente
    tok = pegar_csrf(url)
    client.post(f"/aluno/{sid}/notas", data={"csrf_token": tok, "ano": "2026", "bimestre": "2",
                                              "conc::0": "", "conc::2": "P", "faltas::2": "0"})
    with get_db() as db:
        restantes = [r["disciplina"] for r in db.execute(
            "SELECT disciplina FROM grades WHERE student_id = ?", (sid,)).fetchall()]
    assert restantes == ["Sala de leitura"]


def test_sem_notas_na_turma_usa_lista_padrao_e_valida(client, criar_admin):
    from models import get_db
    with get_db() as db:
        sid = _aluno(db, "ALUNO SOZINHO", "9Z")
    html = client.get(f"/aluno/{sid}/notas").get_data(as_text=True)
    for d in ("Língua Portuguesa", "Matemática", "Sala de leitura"):
        assert d in html
    assert client.get(f"/aluno/{sid}/notas?bimestre=7").status_code == 400
    assert client.get("/aluno/999999/notas").status_code == 404


def test_professor_nao_lanca_notas(client, pegar_csrf, criar_admin):
    from auth import hash_password
    from models import get_db
    with get_db() as db:
        sid = _aluno(db, "ALUNO X", "1A")
        db.execute("INSERT INTO users (username, password_hash, nome, papel) VALUES ('prof', ?, 'Prof', 'professor')",
                   (hash_password("senha-prof-123"),))
    client.get("/logout")
    client.post("/login", data={"username": "prof", "senha": "senha-prof-123", "csrf_token": pegar_csrf("/login")})
    assert client.get(f"/aluno/{sid}/notas").status_code == 403
    assert "Lançar notas manualmente" not in client.get(f"/aluno/{sid}").get_data(as_text=True)


def test_trocar_de_turma_pela_ficha(client, criar_admin):
    from models import get_db
    with get_db() as db:
        sid = _aluno(db, "CARLA FICTICIA", "2A")
        _aluno(db, "ZECA FICTICIO", "3B")
        primeiro_3b = _aluno(db, "ANA FICTICIA", "3B")
    soup = BeautifulSoup(client.get(f"/aluno/{sid}").get_data(as_text=True), "html.parser")
    select = soup.find("select", {"data-trocar-turma": True})
    assert [o["value"] for o in select.find_all("option")] == ["2A", "3B"]
    assert select.find("option", selected=True)["value"] == "2A"
    resp = client.get("/turma/ir?turma=3B")
    assert resp.status_code == 302 and resp.headers["Location"].endswith(f"/aluno/{primeiro_3b}")
    assert client.get("/turma/ir?turma=XX").status_code == 302  # volta com aviso
