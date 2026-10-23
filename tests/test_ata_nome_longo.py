"""Ata Bimestral: aluno com nome longo (quebrado em 2 linhas na célula do
PDF, com Nº/situação/notas no meio da célula) era descartado na leitura."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

NOME_LONGO = "AGATHA MANUELA FICTICIA DO NASCIMENTO OLIVEIRA"


def test_nome_em_duas_linhas_e_lido_inteiro(tmp_path):
    from gerar_ata_ficticia import ALUNOS, _quebrar_nome, gerar_pdf
    from _ata_parser_lib import parse_pdf
    assert len(_quebrar_nome(NOME_LONGO)) == 2  # o PDF de teste quebra mesmo o nome
    alunos = [NOME_LONGO] + ALUNOS[:4] + [NOME_LONGO.replace("AGATHA", "BEATRIZ")]
    caminho = tmp_path / "ata.pdf"
    gerar_pdf(str(caminho), turma="2A", alunos=alunos)
    lidos = parse_pdf(str(caminho))["2A"]
    assert list(lidos) == alunos  # todos, na ordem, com o nome completo
    for nome in alunos:
        assert lidos[nome]["situacao_conselho"] == "REGISTRADO"
        assert len(lidos[nome]["disciplinas"]) >= 8
    # as notas do aluno de nome longo não se misturam com as do vizinho
    assert lidos[NOME_LONGO]["disciplinas"] != lidos[ALUNOS[0]]["disciplinas"]


def test_casa_nome_sem_acento_ou_cortado(app):
    from models import get_db
    from routes.importacao import _match_student
    with get_db() as db:
        a = db.execute("INSERT INTO students (nome, turma, situacao) VALUES (?, '2A', 'ATIVO')",
                       ("ÁGATHA MANUELA FICTÍCIA DO NASCIMENTO",)).lastrowid
        db.execute("INSERT INTO students (nome, turma, situacao) VALUES ('ANA LIMA', '2A', 'ATIVO')")
        assert _match_student(db, "2A", "AGATHA  MANUELA FICTICIA DO NASCIMENTO") == a
        assert _match_student(db, "2A", "AGATHA MANUELA FICTICIA") == a  # nome cortado no PDF
        assert _match_student(db, "2A", "ANA") is None  # curto demais para adivinhar
        assert _match_student(db, "2A", "OUTRO ALUNO QUALQUER") is None
