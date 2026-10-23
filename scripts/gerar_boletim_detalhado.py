"""
Boletim escolar no formato do "Boletim Escolar Detalhado" do SGP: uma
folha por aluno com o ano letivo inteiro (1º a 4º bimestre + Final), em
vez de uma tabela por bimestre.

Layout (igual ao modelo do SGP):
  - cabeçalho: brasão à esquerda; à direita "BOLETIM ESCOLAR - <ano>",
    Secretaria, DRE e escola;
  - quadro do estudante: nº e nome, ciclo, código EOL, turma e
    frequência global (média das frequências lançadas no ano);
  - grade de componentes × bimestres (Conc. e %), em três blocos: base
    comum, Laboratório de Educação Digital / Sala de leitura, e demais
    componentes (ex: "I - EDUCOMUNICAÇÃO..."). Na regência (Ciências,
    Geografia, História, Língua Portuguesa e Matemática) a % igual em
    linhas seguidas aparece uma vez só, com a célula mesclada;
  - legenda, "Recomendações ao estudante" (as do conselho de classe e as
    gerais do aluno; sem nenhuma, o texto padrão do SGP) e
    "Recomendações à família" (texto padrão).

Uso:
  - gerar_pdf_turma_bytes(itens, ano, turma, sem_lancamento=()): tela da
    turma, com itens = [(numero, aluno, notas_do_ano, recomendacoes)];
  - gerar_pdf_aluno_bytes(aluno, notas, recomendacoes, numero, para_responsavel):
    ficha do aluno e área do responsável, com uma folha por ano letivo
    com nota (o mais recente primeiro).

Na versão do responsável o código EOL não aparece: a área do responsável
não mostra documentos do aluno.
"""
import sys
from datetime import date
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Flowable, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)
from xml.sax.saxutils import escape

import config
from routes.cursos import ciclo_da_serie

LARGURA, ALTURA = A4
MARGEM_ESQ = MARGEM_DIR = 60
BRASAO = config.TEMPLATES_DIR / "BRASAO_PREFEITURA_SP.png"
FONTE, FONTE_NEGRITO = "Courier", "Courier-Bold"
TAM = 7.2
LARGURA_UTIL = LARGURA - MARGEM_ESQ - MARGEM_DIR

# ordem e blocos dos componentes, como no boletim do SGP
BASE_COMUM = ["Arte", "Ed. Física", "Inglês", "Ciências", "Geografia", "História", "Língua Portuguesa", "Matemática"]
REGENCIA = {"Ciências", "Geografia", "História", "Língua Portuguesa", "Matemática"}
COMPLEMENTARES = ["Laboratório de Educação Digital", "Sala de leitura"]

LEGENDA = ("Legenda: F:Frequente - NF:Não Frequente - P:Plenamente Satisfatório - S:Satisfatório - "
           "NS:Não Satisfatório")

RECOMENDACOES_ESTUDANTE = (
    "- Busque ir além dos conhecimentos trabalhados em sala de aula. Seja curioso. - Cuide de seu material "
    "escolar. Ele é de sua responsabilidade. - Cuide de suas relações pessoais. Busque ajuda e orientação de "
    "professores, funcionários e gestores sempre que necessário. - Desenvolva uma rotina de estudo e organização "
    "para o cumprimento das tarefas e prazos escolares. - Esclareça suas dúvidas com os professores sempre que "
    "necessário. - Frequente às aulas diariamente. Em caso de ausência, justifique-a. - Frequente bibliotecas e "
    "sites confiáveis para pesquisa. - Leia, releia, converse com seus colegas e outros adultos sobre temas "
    "estudados, buscando ampliar seu entendimento sobre eles. - Participe das aulas com atenção, pergunte quando "
    "tiver dúvidas e faça registro das ideias centrais da aula. - Peça permissão para falar e saiba ouvir seus "
    "colegas. - Pesquise. Reflita. Questione. Discuta. Escreva. - Procure desenvolver seus próprios métodos de "
    "estudo. Use agenda e anote seus compromissos. - Valorize, respeite e coopere com o trabalho de todos no "
    "ambiente escolar."
)
RECOMENDACOES_FAMILIA = (
    "- Acompanhe a frequência de seus filhos às aulas e às atividades escolares. - Acompanhe seu filho na "
    "realização das lições de casa. - Ajude a construir uma escola democrática. Participe do Conselho de Escola. "
    "- Compareça às reuniões da escola. Dê sua opinião. Ela é muito importante. - Confira o boletim escolar de "
    "seu filho, caso tenha alguma dúvida procure o professor/coordenador. - Incentive seu filho a cumprir "
    "prazos, tarefas e regras da Unidade Escolar. - Leia bilhetes e avisos que a escola mandar e responda quando "
    "necessário. - Oriente seu filho a cuidar de seu material escolar. - Peça orientação aos professores e "
    "coordenadores caso perceba alguma dificuldade no desempenho do seu filho. - Procure visitar a escola de seus "
    "filhos sempre que precisar. - Verifique diariamente os cadernos e livros de seus filhos."
)

TEXTO = ParagraphStyle("texto", fontName=FONTE, fontSize=TAM, leading=TAM * 1.45)
CAB_DIREITA = ParagraphStyle("cab", fontName=FONTE, fontSize=9, leading=12, alignment=TA_RIGHT)
CAB_TITULO = ParagraphStyle("cabt", parent=CAB_DIREITA, fontName=FONTE_NEGRITO, fontSize=7.2, leading=11)
TITULO_CAIXA = ParagraphStyle("tcx", parent=TEXTO, alignment=TA_CENTER)
CELULA = ParagraphStyle("cel", parent=TEXTO, leading=TAM * 1.2)
LINHA = colors.HexColor("#333333")


def _pct(valor):
    return "-" if valor is None else f"{float(valor):.2f}%"


def _tem_conceito(nota):
    c = (nota["conceito"] or "").strip()
    return bool(c) and c != "-"


def _conc(nota, componente_com_conceito):
    """Conceito como no SGP: em componente que só tem frequência (ex:
    Laboratório, Sala de leitura) a coluna fica vazia; nos demais, "-"
    quando o bimestre não tem conceito."""
    if nota is not None and _tem_conceito(nota):
        return nota["conceito"].strip().upper()
    return "-" if componente_com_conceito else ""


def _ordenar_componentes(disciplinas):
    base = [d for d in BASE_COMUM if d in disciplinas]
    compl = [d for d in COMPLEMENTARES if d in disciplinas]
    outros = sorted(d for d in disciplinas if d not in BASE_COMUM and d not in COMPLEMENTARES)
    return [b for b in (base, compl, outros) if b]


def _cabecalho(ano):
    linhas = [
        Paragraph(f"BOLETIM ESCOLAR - {ano}", CAB_TITULO),
        Paragraph("SECRETARIA MUNICIPAL DE EDUCAÇÃO", CAB_DIREITA),
        Paragraph(escape(getattr(config, "ESCOLA_DRE", "DIRETORIA REGIONAL DE EDUCAÇÃO CAPELA DO SOCORRO")), CAB_DIREITA),
        Paragraph(escape(config.ESCOLA_NOME.upper()), CAB_DIREITA),
    ]
    logo = Image(str(BRASAO), width=30, height=39) if BRASAO.exists() else ""
    t = Table([[logo, linhas]], colWidths=[60, LARGURA_UTIL - 60])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _caixa(linhas, larguras):
    t = Table([[Paragraph(escape(txt), TEXTO) for txt in linhas]], colWidths=larguras)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, LINHA), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _dados_estudante(numero, aluno, freq_global, turma=None, para_responsavel=False):
    """turma: a do ano do boletim (a atual; em ano anterior o sistema não
    guarda a turma, então vai "-")."""
    nome = aluno["nome_social"] or aluno["nome"] or ""
    ciclo = ciclo_da_serie(aluno["serie"]) or "-"
    estudante = f"Estudante: {numero} - {nome}" if numero else f"Estudante: {nome}"
    turma_txt = f"Turma: EF - {turma}" if turma else "Turma: -"
    freq_txt = f"Frequência Global: {_pct(freq_global) if freq_global is not None else '-'}"
    segunda = (_caixa([turma_txt, freq_txt], [241, LARGURA_UTIL - 241]) if para_responsavel else
               _caixa([f"Código EOL: {aluno['codigo_interno'] or '-'}", turma_txt, freq_txt],
                      [156, 114, LARGURA_UTIL - 270]))
    return [_caixa([estudante, f"Ciclo: {ciclo}"], [241, LARGURA_UTIL - 241]), segunda]


COL_COMP = LARGURA_UTIL - 5 * (24 + 35)
LARGURAS_GRADE = [COL_COMP] + [24, 35] * 5


def _grade(blocos, por_comp):
    """Uma tabela por bloco de componentes; a primeira leva o cabeçalho."""
    tabelas = []
    for b, componentes in enumerate(blocos):
        dados, estilo = [], [
            ("GRID", (0, 0), (-1, -1), 0.6, LINHA),
            ("FONT", (0, 0), (-1, -1), FONTE, TAM),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (0, -1), 4), ("LEFTPADDING", (1, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ]
        topo = 0
        if b == 0:
            dados.append(["Componentes curriculares"] + sum([[f"{n}° Bim.", ""] for n in range(1, 5)], []) + ["Final", ""])
            dados.append([""] + ["Conc.", "%"] * 5)
            estilo += [("SPAN", (0, 0), (0, 1))] + [("SPAN", (1 + 2 * i, 0), (2 + 2 * i, 0)) for i in range(5)]
            topo = 2
        for comp in componentes:
            notas = por_comp.get(comp, {})
            com_conceito = any(_tem_conceito(n) for n in notas.values())
            linha = [Paragraph(escape(comp if len(comp) <= 34 else comp[:31] + "..."), CELULA)]
            for bim in range(1, 5):
                n = notas.get(bim)
                linha += [_conc(n, com_conceito), _pct(n["frequencia"]) if n else "-"]
            linha += ["-", ""]  # Final: ainda não há resultado final no sistema
            dados.append(linha)
        # regência: % igual em linhas seguidas fica numa célula só
        for col in [2, 4, 6, 8, 10]:
            inicio = None
            for i in range(topo, len(dados) + 1):
                comp = componentes[i - topo] if i < len(dados) else None
                valor = dados[i][col] if i < len(dados) else None
                if inicio is not None and (comp not in REGENCIA or valor != dados[inicio][col]):
                    if i - inicio > 1:
                        estilo.append(("SPAN", (col, inicio), (col, i - 1)))
                    inicio = None
                if inicio is None and comp in REGENCIA:
                    inicio = i
        t = Table(dados, colWidths=LARGURAS_GRADE)
        t.setStyle(TableStyle(estilo))
        tabelas += [t, Spacer(1, 5)]
    return tabelas[:-1]


def _caixa_texto(titulo, texto):
    corpo = escape(texto).replace("\n", "<br/>")
    t = Table([[Paragraph(titulo, TITULO_CAIXA)], [Paragraph(corpo, TEXTO)]], colWidths=[LARGURA_UTIL])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINHA), ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINHA),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _texto_recomendacoes(ano, aluno, recomendacoes):
    partes = [f"{bim}º bimestre: {rec['texto'].strip()}"
              for (a, bim), rec in sorted(recomendacoes.items()) if a == ano and (rec["texto"] or "").strip()]
    geral = (aluno["recomendacoes"] or "").strip() if "recomendacoes" in aluno.keys() else ""
    if geral:
        partes.append(geral)
    return "\n".join(partes) or RECOMENDACOES_ESTUDANTE


class _Rodape(Flowable):
    def __init__(self, texto):
        super().__init__()
        self.texto = texto
        self.width = self.height = 0

    def draw(self):
        self.canv._rodape = self.texto


class _Canvas(rl_canvas.Canvas):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._paginas, self._rodape = [], ""

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont(FONTE, 9)
            self.drawString(MARGEM_ESQ - 30, 22, self._rodape)
            self.drawRightString(LARGURA - MARGEM_DIR + 30, 22, f"{self._pageNumber} / {total}")
            super().showPage()
        super().save()


def boletim_do_aluno(numero, aluno, notas, recomendacoes, ano, turma=None, para_responsavel=False):
    """Flowables da folha de um aluno num ano letivo."""
    turma = turma if turma is not None else aluno["turma"]
    por_comp = {}
    for n in notas:
        por_comp.setdefault(n["disciplina"], {})[n["bimestre"]] = n
    freqs = [n["frequencia"] for n in notas if n["frequencia"] is not None]
    freq_global = sum(freqs) / len(freqs) if freqs else None
    historia = [_cabecalho(ano), Spacer(1, 12), *_dados_estudante(numero, aluno, freq_global, turma, para_responsavel),
                Spacer(1, 5)]
    historia += _grade(_ordenar_componentes(set(por_comp)), por_comp)
    historia += [
        Paragraph(escape(LEGENDA), TEXTO), Spacer(1, 10),
        KeepTogether(_caixa_texto("Recomendações ao estudante", _texto_recomendacoes(ano, aluno, recomendacoes))),
        Spacer(1, 10),
        KeepTogether(_caixa_texto("Recomendações à família", RECOMENDACOES_FAMILIA)),
    ]
    return historia


def gerar_pdf_turma_bytes(itens, ano, turma="", sem_lancamento=(), emitido_em=None):
    emitido = (emitido_em or date.today()).strftime("%d/%m/%Y")
    historia = []
    for i, (numero, aluno, notas, recomendacoes) in enumerate(itens):
        if i:
            historia.append(PageBreak())
        historia.append(_Rodape(f"{config.ESCOLA_NOME} | Turma {turma} | {emitido}"))
        historia += boletim_do_aluno(numero, aluno, notas, recomendacoes, ano)
    if sem_lancamento:
        if historia:
            historia.append(PageBreak())
        historia += [
            _Rodape(f"{config.ESCOLA_NOME} | Turma {turma} | {emitido}"), _cabecalho(ano), Spacer(1, 14),
            Paragraph(escape(f"Turma {turma}: alunos sem nota lançada em {ano} (sem boletim neste arquivo):"), TEXTO),
            Spacer(1, 4),
        ]
        historia += [Paragraph(escape(f"{numero} - {a['nome_social'] or a['nome']}"), TEXTO) for numero, a in sem_lancamento]
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGEM_ESQ, rightMargin=MARGEM_DIR, topMargin=18,
                            bottomMargin=40, title=f"Boletins - Turma {turma} - {ano}", author=config.ESCOLA_NOME)
    doc.build(historia, canvasmaker=_Canvas)
    return buffer.getvalue()


def gerar_pdf_aluno_bytes(aluno, notas, recomendacoes=None, numero=None, para_responsavel=False,
                          ano_atual=None, emitido_em=None):
    """notas: todas as linhas de grades do aluno. Uma folha por ano letivo
    com nota, do mais recente para o mais antigo."""
    recomendacoes = recomendacoes or {}
    ano_atual = ano_atual or config.ANO_LETIVO
    emitido = (emitido_em or date.today()).strftime("%d/%m/%Y")
    nome = aluno["nome_social"] or aluno["nome"] or ""
    por_ano = {}
    for n in notas:
        por_ano.setdefault(n["ano"], []).append(n)
    anos = sorted(por_ano, reverse=True) or [ano_atual]
    historia = [_Rodape(f"{config.ESCOLA_NOME} | {nome} | {emitido}")]
    for i, ano in enumerate(anos):
        if i:
            historia.append(PageBreak())
        historia += boletim_do_aluno(
            numero if ano == ano_atual else None, aluno, por_ano.get(ano, []), recomendacoes, ano,
            turma=aluno["turma"] if ano == ano_atual else "", para_responsavel=para_responsavel,
        )
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=MARGEM_ESQ, rightMargin=MARGEM_DIR, topMargin=18,
                            bottomMargin=40, title=f"Boletim Escolar - {nome}", author=config.ESCOLA_NOME)
    doc.build(historia, canvasmaker=_Canvas)
    return buffer.getvalue()


def numero_na_turma(db, aluno):
    """Posição do aluno na lista da turma (ativos em ordem alfabética), a
    mesma usada nos boletins da turma. None se ele não estiver ativo."""
    if (aluno["situacao"] or "").upper() != "ATIVO":
        return None
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM students WHERE turma = ? AND situacao = 'ATIVO' ORDER BY nome", (aluno["turma"],)
    ).fetchall()]
    return ids.index(aluno["id"]) + 1 if aluno["id"] in ids else None
