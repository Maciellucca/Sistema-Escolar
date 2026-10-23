"""
Importa a base de alunos a partir da planilha "PILOTO" exportada do sistema
de matrícula (SGP), gerando/atualizando a tabela `students`.

Uso:
    1. Se o arquivo original for .xls (formato antigo), abra-o no Excel/LibreOffice
       e "Salvar como" .xlsx primeiro (ou rode:
       `soffice --headless --convert-to xlsx --outdir data/raw data/raw/PILOTO.xls`).
    2. Coloque o .xlsx resultante em data/raw/
    3. python scripts/import_students.py data/raw/PILOTO_01_07_2026.xlsx

Por padrão importa TODAS as séries (1º ao 9º ano). Use --serie para importar
uma série específica se preferir (ex: --serie "1º Ano").
Este script NUNCA deve rodar automaticamente em um pipeline público — ele
lida com dados pessoais reais de crianças. Rode manualmente, localmente.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook

from models import get_db, init_db, agora, propagar_dados_aluno

COLS = [
    "codigo", "ra_prodesp", "inep", "nome_turma_num", "nome", "filiacao1",
    "data_nascimento", "data_inclusao", "data_matricula", "pc",
    "situacao", "origem", "serie", "teg", "sed",
]


def _to_iso(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


def carregar_planilha(path, aba=None):
    """Le a planilha PILOTO. Por padrao usa a primeira aba que comece com
    'AlunosDaTurma' (o arquivo do SGP costuma trazer abas extras de
    'Conferência de Documentos' com um cabeçalho parecido mas mais estreito
    — ler a aba errada quebra o mapeamento de colunas)."""
    wb = load_workbook(path, data_only=True)
    if aba:
        nomes_aba = [aba]
    else:
        nomes_aba = [s for s in wb.sheetnames if s.startswith("AlunosDaTurma")] or [wb.sheetnames[0]]

    linhas = []
    for sheet_name in nomes_aba:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        header_idx = next(
            (i for i, r in enumerate(rows) if r and r[0] == "Código" and len(r) >= len(COLS)),
            None,
        )
        if header_idx is None:
            continue
        for r in rows[header_idx + 1 :]:
            if not r or not r[0]:
                continue
            linhas.append(dict(zip(COLS, r)))
    return linhas


def importar(path, serie_filtro, dry_run=False, aba=None):
    linhas = carregar_planilha(path, aba)
    alvo = [l for l in linhas if not serie_filtro or (l["serie"] or "").strip() == serie_filtro]

    print(f"Linhas na planilha: {len(linhas)} · após filtro de série '{serie_filtro}': {len(alvo)}")

    if dry_run:
        for l in alvo[:5]:
            print(" ", l["nome"], l["nome_turma_num"], l["situacao"])
        return {"total": len(alvo), "novos": 0, "atualizados": 0, "dry_run": True}

    init_db()
    novos, atualizados = 0, 0
    with get_db() as db:
        for l in alvo:
            codigo = str(l["codigo"])
            turma = str(l["nome_turma_num"]).strip()
            existente = db.execute(
                "SELECT id, nome, nome_social, turma FROM students WHERE codigo_interno = ?", (codigo,)
            ).fetchone()
            valores = (
                l["ra_prodesp"],
                str(l["inep"]) if l["inep"] else None,
                l["nome"].strip(),
                l["filiacao1"],
                _to_iso(l["data_nascimento"]),
                turma,
                l["serie"],
                l["situacao"],
            )
            if existente:
                db.execute(
                    """UPDATE students SET ra_prodesp=?, inep=?, nome=?, filiacao1=?,
                       data_nascimento=?, turma=?, serie=?, situacao=?, updated_at=?
                       WHERE codigo_interno=?""",
                    valores + (agora(), codigo),
                )
                propagar_dados_aluno(db, existente["id"], antes=existente)
                atualizados += 1
            else:
                db.execute(
                    """INSERT INTO students
                       (codigo_interno, ra_prodesp, inep, nome, filiacao1,
                        data_nascimento, turma, serie, situacao)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (codigo,) + valores,
                )
                novos += 1
    resultado = {"total": len(alvo), "novos": novos, "atualizados": atualizados, "dry_run": False}
    print(f"Importação concluída: {novos} aluno(s) novo(s), {atualizados} atualizado(s).")
    return resultado


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("planilha", help="Caminho do .xlsx exportado (PILOTO)")
    parser.add_argument("--serie", default="", help="Filtra por série (ex: '1º Ano'). Padrão: '' = importa todas as séries.")
    parser.add_argument("--dry-run", action="store_true", help="Só mostra o que seria importado, sem gravar no banco.")
    parser.add_argument("--aba", default=None, help="Nome exato da aba, se quiser forçar (padrão: detecta 'AlunosDaTurma...')")
    args = parser.parse_args()
    importar(args.planilha, args.serie, args.dry_run, args.aba)
