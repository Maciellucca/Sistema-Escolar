"""
Importa notas/faltas de um PDF de Ata Bimestral (SGP) para a tabela `grades`.

A leitura é feita pela posição (x, y) de cada palavra no PDF — não por um
layout fixo de colunas — então tende a resistir a pequenas mudanças no
relatório. Mesmo assim, revise os dados no sistema antes de divulgá-los aos
responsáveis: PDFs às vezes trazem células quebradas em várias linhas e o
mapeamento pode falhar em casos incomuns.

Uso:
    python scripts/import_atas.py data/raw/AtaBimestral_1º_Bimestre.pdf \\
        --ano 2026 --bimestre 1 --turmas 1A 1B 1C

Isto pode levar alguns minutos em arquivos grandes (o script varre
todas as páginas do PDF, não só as turmas escolhidas).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _ata_parser_lib import parse_pdf
from models import get_db, init_db, salvar_nota
from routes.importacao import _match_student


def importar(path, ano, bimestre, turmas, dry_run=False):
    print(f"Lendo {path} (isso pode levar alguns minutos)...")
    resultado = parse_pdf(path, turmas_alvo=set(turmas) if turmas else None)

    total_gravado, nao_encontrados = 0, []
    init_db()
    with get_db() as db:
        for turma, alunos in resultado.items():
            print(f"Turma {turma}: {len(alunos)} aluno(s) lidos no PDF")
            for nome, dados in alunos.items():
                # mesma regra da importação pela tela (turma + nome, depois só o
                # nome, depois sem diferença de acento/espaço)
                student_id = _match_student(db, turma, nome)
                if not student_id:
                    nao_encontrados.append((turma, nome))
                    continue
                if dry_run:
                    continue
                for disciplina, valores in dados["disciplinas"].items():
                    salvar_nota(
                        db, student_id, ano, bimestre, disciplina,
                        valores.get("faltas"), valores.get("compensacoes"),
                        valores.get("frequencia"), valores.get("conceito"),
                        dados.get("situacao_conselho"), "importado_pdf",
                    )
                    total_gravado += 1

    print(f"Registros de nota gravados: {total_gravado}")
    if nao_encontrados:
        print(f"Alunos do PDF não localizados no cadastro ({len(nao_encontrados)}):")
        for turma, nome in nao_encontrados[:30]:
            print(f"   - [{turma}] {nome}")
        print("Confira acentos/grafia, ou se o aluno já foi importado via import_students.py.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Caminho do PDF da Ata Bimestral")
    parser.add_argument("--ano", type=int, required=True)
    parser.add_argument("--bimestre", type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument("--turmas", nargs="*", default=None, help="Ex: 1A 1B 1C (padrão: todas as turmas do PDF)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    importar(args.pdf, args.ano, args.bimestre, args.turmas, args.dry_run)
