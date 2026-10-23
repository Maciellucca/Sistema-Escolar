def test_salvar_nota_insere_e_depois_atualiza_sem_duplicar(app):
    from models import get_db, salvar_nota

    with get_db() as db:
        aluno_id = db.execute(
            """INSERT INTO students (codigo_interno, nome, turma, serie, situacao)
               VALUES ('C1', 'ALUNO TESTE', '1A', '1º Ano', 'ATIVO')"""
        ).lastrowid

        salvar_nota(db, aluno_id, 2026, 1, "Matemática", 2, 0, 90.0, "S", "REGISTRADO", "teste")
        salvar_nota(db, aluno_id, 2026, 1, "Matemática", 3, 1, 85.0, "P", "REGISTRADO", "teste")

        total = db.execute("SELECT COUNT(*) c FROM grades WHERE student_id=?", (aluno_id,)).fetchone()
        assert total["c"] == 1

        nota = db.execute("SELECT faltas, conceito FROM grades WHERE student_id=?", (aluno_id,)).fetchone()
        assert nota["faltas"] == 3
        assert nota["conceito"] == "P"


def test_salvar_aee_info_insere_e_depois_atualiza_sem_duplicar(app):
    from models import get_db, salvar_aee_info

    with get_db() as db:
        aluno_id = db.execute(
            """INSERT INTO students (codigo_interno, nome, turma, serie, situacao, aee)
               VALUES ('C2', 'ALUNO AEE', '1A', '1º Ano', 'ATIVO', 1)"""
        ).lastrowid

        salvar_aee_info(db, aluno_id, "E1", "laudo v1", "obs v1", "TEA", "INTEGRAL")
        salvar_aee_info(db, aluno_id, "E1", "laudo v2", "obs v2", "TEA", "INTEGRAL")

        total = db.execute("SELECT COUNT(*) c FROM aee_info").fetchone()
        assert total["c"] == 1

        info = db.execute("SELECT laudo FROM aee_info WHERE student_id=?", (aluno_id,)).fetchone()
        assert info["laudo"] == "laudo v2"


def test_agora_retorna_formato_compativel_com_os_dois_bancos():
    from models import agora
    valor = agora()
    # formato "YYYY-MM-DD HH:MM:SS" — comparável como string em SQLite e MySQL
    assert len(valor) == 19
    assert valor[4] == "-" and valor[7] == "-" and valor[10] == " "
