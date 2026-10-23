"""
Lê uma Ata Bimestral em PDF LOCALMENTE (na sua máquina) e exporta o
resultado já processado para um arquivo .json — para depois subir esse
.json pela tela "Importar notas" do sistema (opção "Já tenho o arquivo
processado"), sem precisar que o servidor faça a leitura pesada do PDF.

Isso existe porque hospedagens com pouca CPU (ex: plano Free do Render)
podem não sustentar a leitura em segundo plano de um PDF grande — rodando
a leitura aqui, no seu computador, e subindo só o resultado (um JSON
pequeno e rápido de processar), o servidor nunca precisa fazer o trabalho
pesado. O JSON gerado NÃO deve ser commitado no Git se a Ata for real
(tem dado de aluno de verdade) — envie só pela tela do sistema.

Uso:
    python scripts/exportar_notas_json.py caminho/da/ata.pdf --ano 2026 --bimestre 1
    python scripts/exportar_notas_json.py ata.pdf --ano 2026 --bimestre 1 --turmas 1A 1B -o saida.json
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from _ata_parser_lib import parse_pdf


def exportar(caminho_pdf, ano, bimestre, turmas=None, saida=None):
    print(f"Lendo {caminho_pdf} (pode levar de alguns segundos a alguns minutos)...")
    resultado = parse_pdf(caminho_pdf, turmas_alvo=set(turmas) if turmas else None)
    if not resultado:
        raise SystemExit(
            "Nenhuma turma reconhecida nesse PDF (confira o filtro --turmas e se é "
            "mesmo um relatório de Ata Bimestral do SGP)."
        )

    pacote = {
        "arquivo_origem": Path(caminho_pdf).name,
        "ano": ano,
        "bimestre": bimestre,
        "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "turmas": resultado,
    }

    saida = Path(saida) if saida else Path(caminho_pdf).with_suffix(".json")
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(pacote, f, ensure_ascii=False, indent=2)

    total_alunos = sum(len(alunos) for alunos in resultado.values())
    print(
        f"Exportado: {saida} — {len(resultado)} turma(s), {total_alunos} aluno(s). "
        f"Envie esse arquivo pela tela \"Importar notas\" (opção \"Já tenho o "
        f"arquivo processado\")."
    )
    return saida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", help="Caminho do PDF da Ata Bimestral")
    parser.add_argument("--ano", type=int, required=True)
    parser.add_argument("--bimestre", type=int, required=True)
    parser.add_argument("--turmas", nargs="*", help="Filtra turmas (ex: 1A 1B). Sem isso, lê todas do PDF.")
    parser.add_argument("-o", "--saida", help="Caminho do .json de saída (padrão: mesmo nome do PDF, com .json)")
    args = parser.parse_args()
    exportar(args.pdf, args.ano, args.bimestre, args.turmas, args.saida)
