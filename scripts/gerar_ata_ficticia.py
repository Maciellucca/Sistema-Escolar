"""
Gera uma Ata Bimestral FICTÍCIA em PDF, no mesmo layout visual/estrutural
do relatório real do SGP, usando os alunos fictícios do projeto integrador.
Nenhum dado real é usado — nomes, escola, DRE, usuário, notas: tudo fictício.

Requer reportlab (pip install -r requirements-dev.txt).

Uso:
    python scripts/gerar_ata_ficticia.py data/exemplo/AtaBimestral_ficticia_3bim.pdf --turma 1A --bimestre 3 --ano 2026
"""
import random
from datetime import date
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape, A4

ALUNOS = [
    "ALICE COSTA SILVA", "ARTHUR PEREIRA LIMA", "BERNARDO ALVES GOMES",
    "BIANCA RIBEIRO SOUZA", "CAIO MENDES ROCHA", "CLARA MARTINS DIAS",
    "DAVI LUCCA FERNANDES", "ENZO GABRIEL CASTRO", "GABRIEL ARAUJO MELO",
    "GIOVANNA NUNES BARROS", "GUILHERME FARIAS MORAIS", "HELENA CARDOSO RAMOS",
    "HEITOR VIANA TEIXEIRA", "ISABELLA CUNHA MACIEL", "JOAO MIGUEL LOPES",
    "JULIA MOURA PIRES", "LAURA FONTES CORREIA", "LORENZO MACHADO REIS",
    "LUCAS PEIXOTO FONSECA", "LUIZA CAMPOS VIEIRA", "MANUELA BORGES MONTEIRO",
    "MARIA EDUARDA BATISTA", "MATEUS DUARTE GOMES", "MIGUEL BARBOSA SILVA",
    "NICOLAS FREITAS LIMA", "PEDRO HENRIQUE DIAS", "RAFAEL MENEZES CRUZ",
    "SOPHIA NOGUEIRA PAZ", "THEO ANDRADE VALE", "VALENTINA MOREIRA LUZ",
]

# (nome da disciplina, x do F, x do CA, x do %, x do N/C) -- mesmas posicoes
# de coluna do relatorio real do SGP, para o parser conseguir ler igual.
SUBJECTS = [
    ("Arte",                200.0, 182.6, 194.0, 212.6, 227.3),
    ("Ciências",             258.0, 246.2, 257.6, 274.7, 288.2),
    ("Ed. Física",           320.0, 307.7, 319.7, 338.6, 353.6),
    ("Geografia",            383.0, 373.1, 385.1, 402.5, 416.0),
    ("História",             448.0, 435.5, 447.5, 464.9, 478.4),
    ("Inglês",                514.0, 497.9, 509.9, 528.8, 543.8),
    ("Língua Portuguesa",    563.0, 563.4, 575.4, 592.8, 606.6),
    ("Matemática",           634.0, 626.4, 638.4, 655.8, 669.3),
    ("Laboratório de Educação Digital", 686.0, 690.0, 704.7, 727.2, 746.1),
    ("Sala de leitura",      772.0, 767.4, 779.4, 795.6, 808.5),
]

PAGE_W, PAGE_H = landscape(A4)  # 842 x 595


def y(top):
    return PAGE_H - top


def cabecalho(c, turma, bimestre, ano, pagina, total_paginas, data_impressao):
    c.setFont("Helvetica", 8)
    c.drawString(685.2, y(17.1), "SGP - Sistema de Gestão Pedagógica (fictício)")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(665.4, y(32.9), f"ATA BIMESTRAL - {bimestre}° BIMESTRE - {ano}")
    c.drawString(794.4, y(49.7), f"EF - {turma}")

    c.setFont("Helvetica", 8)
    c.drawString(20.3, y(83.1), "DRE: DRE FICTÍCIA")
    c.drawString(134.9, y(83.1), "UE: 999999 - EMEF ESCOLA MODELO (PROJETO INTEGRADOR)")
    c.drawString(348.5, y(83.1), "USUÁRIO: PROJETO INTEGRADOR")
    c.drawString(562.2, y(83.1), "RF: 0000000")
    c.drawString(676.8, y(83.1), f"DATA DE IMPRESSÃO: {data_impressao}")

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(20.3, y(96), "Documento fictício gerado para fins acadêmicos — nenhum aluno ou escola real.")

    # categorias
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(440, y(112.5), "Base Nacional Comum")
    c.drawCentredString(780, y(112.5), "Diversificada")

    # cabecalhos de disciplina (uma ou duas linhas) — alinhados à esquerda
    # na coluna (não centralizados), para não "vazar" visualmente para a
    # coluna vizinha e confundir a leitura por posição.
    c.setFont("Helvetica-Bold", 6.3)
    for nome, cx, fx, _, _, _ in SUBJECTS:
        palavras = nome.split(" ")
        if len(" ".join(palavras)) <= 12:
            c.drawString(fx, y(130.5), nome)
        else:
            meio = len(palavras) // 2 + (1 if len(palavras) % 2 else 0)
            linha1 = " ".join(palavras[:meio])
            linha2 = " ".join(palavras[meio:])
            c.drawString(fx, y(126.3), linha1)
            c.drawString(fx, y(134.7), linha2)

    c.setFont("Helvetica-Bold", 7)
    c.drawString(22.7, y(130.5), "Nº")
    c.drawString(34.1, y(130.5), "NOME")
    c.drawString(135.8, y(126.3), "CONSELHO DE")
    c.drawString(144.8, y(134.7), "CLASSE")

    c.setFont("Helvetica-Bold", 6.5)
    for _, _, fx, cax, px, ncx in SUBJECTS:
        c.drawString(fx, y(147.9), "F")
        c.drawString(cax, y(147.9), "CA")
        c.drawString(px, y(147.9), "%")
        c.drawString(ncx, y(147.9), "N/C")

    c.line(15, y(152), 828, y(152))

    c.setFont("Helvetica", 6.5)
    c.drawString(15, y(586), f"Página {pagina}/{total_paginas}")


def rodape(c):
    c.setFont("Helvetica", 6.5)
    c.drawString(
        15, y(592),
        "Legenda: F:Total de faltas · CA:Compensação de ausências · %:Frequência · N/C:Conceito (P=Plenamente satisfatório, S=Satisfatório, NS=Não satisfatório)",
    )


LARGURA_NOME = 104  # coluna NOME vai de x=34 até a coluna CONSELHO DE CLASSE


def _quebrar_nome(nome, fonte="Helvetica", tamanho=6.6):
    """Nome longo quebra em duas linhas dentro da célula, como no SGP."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if stringWidth(nome, fonte, tamanho) <= LARGURA_NOME:
        return [nome]
    palavras, linha1 = nome.split(), ""
    while palavras and stringWidth((linha1 + " " + palavras[0]).strip(), fonte, tamanho) <= LARGURA_NOME:
        linha1 = (linha1 + " " + palavras.pop(0)).strip()
    return [linha1, " ".join(palavras)]


def gerar_notas(seed_nome):
    rnd = random.Random(seed_nome)
    linha = []
    for i, _ in enumerate(SUBJECTS):
        if i >= 8 and rnd.random() < 0.3:  # Lab Digital / Sala leitura, parte fica em branco
            linha.append((None, None, None, None))
            continue
        faltas = rnd.randint(0, 9)
        comp = faltas if rnd.random() < 0.15 else (rnd.randint(0, faltas) if rnd.random() < 0.2 else 0)
        freq = round(100 * (1 - max(0, faltas - comp) / 59), 2)
        freq = max(0.0, min(100.0, freq))
        conceito = "P" if freq >= 95 else ("S" if freq >= 85 else "NS")
        linha.append((faltas, comp, freq, conceito))
    return linha


def gerar_pdf(caminho, turma="1A", bimestre=1, ano=2026, alunos=None, alunos_por_pagina=20):
    alunos = alunos or ALUNOS
    data_impressao = date.today().strftime("%d/%m/%Y")
    total_paginas = (len(alunos) + alunos_por_pagina - 1) // alunos_por_pagina

    c = canvas.Canvas(caminho, pagesize=(PAGE_W, PAGE_H))
    for pagina in range(total_paginas):
        bloco = alunos[pagina * alunos_por_pagina : (pagina + 1) * alunos_por_pagina]
        cabecalho(c, turma, bimestre, ano, pagina + 1, total_paginas, data_impressao)

        c.setFont("Helvetica", 6.6)
        top = 165.4
        for idx, nome in enumerate(bloco, start=pagina * alunos_por_pagina + 1):
            c.drawString(22.7, y(top), str(idx))
            linhas = _quebrar_nome(nome)
            if len(linhas) == 1:
                c.drawString(34.1, y(top), nome)
            else:  # como no SGP: nome em 2 linhas, Nº/situação/notas no meio da célula
                c.drawString(34.1, y(top - 3.8), linhas[0])
                c.drawString(34.1, y(top + 3.8), linhas[1])
            c.setFont("Helvetica", 5.4)
            c.drawString(141.2, y(top), "REGISTRADO")
            c.setFont("Helvetica", 6.6)
            notas = gerar_notas(f"{turma}-{bimestre}-{nome}")
            for (falt, comp, freq, conc), (_, _, fx, cax, px, ncx) in zip(notas, SUBJECTS):
                if falt is None:
                    c.drawString(ncx, y(top), "-")
                else:
                    c.drawString(fx, y(top), str(falt))
                    c.drawString(cax, y(top), str(comp))
                    c.drawRightString(ncx - 6, y(top), f"{freq:.0f}")
                    c.drawString(ncx, y(top), conc)
            top += 16.8

        rodape(c)
        c.showPage()
    c.save()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("saida")
    parser.add_argument("--turma", default="1A")
    parser.add_argument("--bimestre", type=int, default=1)
    parser.add_argument("--ano", type=int, default=2026)
    args = parser.parse_args()
    gerar_pdf(args.saida, turma=args.turma, bimestre=args.bimestre, ano=args.ano)
    print(f"Gerado: {args.saida}")
