"""
Biblioteca de leitura das Atas Bimestrais (SGP) em PDF.
Extrai, por página, a turma, o tipo de tabela (Base Nacional Comum /
Diversificada / Integral) e as notas/faltas de cada aluno por componente
curricular, usando as coordenadas (x, y) das palavras no PDF — não depende
de um layout fixo de colunas, então continua funcionando se a SME mudar
levemente o relatório.
"""
import re
import pdfplumber

ROW_NUM_RE = re.compile(r"^\d{1,3}$")


def _cluster_header_slots(words, tol=1.5):
    """Encontra a linha de cabeçalho com os rotulos F / CA / % / N/C e
    agrupa em blocos de 4 (um bloco = uma disciplina)."""
    labels = {"F", "CA", "%", "N/C"}
    cand = [w for w in words if w["text"] in labels]
    if not cand:
        return None, []
    from collections import Counter
    tops = Counter(round(w["top"], 0) for w in cand)
    header_top = max(tops, key=lambda t: tops[t])
    row = sorted(
        [w for w in cand if abs(w["top"] - header_top) <= tol],
        key=lambda w: w["x0"],
    )
    slots = []
    for i in range(0, len(row) - 3, 4):
        chunk = row[i : i + 4]
        if [w["text"] for w in chunk] != ["F", "CA", "%", "N/C"]:
            continue
        slots.append(
            {
                "x_start": chunk[0]["x0"] - 4,
                "x_end": None,
                "sub_x": [w["x0"] for w in chunk],
            }
        )
    for i, s in enumerate(slots):
        s["x_end"] = slots[i + 1]["x_start"] if i + 1 < len(slots) else 10_000
    return header_top, slots


def _subject_names(words, header_top, slots):
    """Junta as palavras do titulo de cada disciplina (podem estar em
    varias linhas) usando a posicao x para saber a qual coluna pertencem.
    A primeira linha acima do cabecalho costuma ser um rotulo de categoria
    ("Base Nacional Comum" / "Diversificada" / "Integral") que abrange
    varias colunas — essa linha e descartada e tratada a parte."""
    cand = [
        w
        for w in words
        if header_top - 40 < w["top"] < header_top - 3 and w["x0"] >= slots[0]["x_start"]
    ]
    if not cand:
        return [f"Disciplina {i+1}" for i in range(len(slots))]
    rows = {}
    for w in cand:
        rows.setdefault(round(w["top"]), []).append(w)
    tops_sorted = sorted(rows.keys())
    # a linha de categoria fica logo acima e tem poucas palavras espalhadas;
    # ignoramos a primeira linha (menor "top") do bloco de titulo.
    category_top = tops_sorted[0] if len(tops_sorted) > 1 else None
    title_words = [w for t in tops_sorted if t != category_top for w in rows[t]]
    title_words.sort(key=lambda w: (round(w["top"]), w["x0"]))

    names = ["" for _ in slots]
    for w in title_words:
        best, best_d = None, 1e9
        for i, s in enumerate(slots):
            if s["x_start"] - 15 <= w["x0"] < s["x_end"] - 5:
                d = 0
            else:
                d = min(abs(w["x0"] - s["x_start"]), abs(w["x0"] - s["x_end"]))
            if d < best_d:
                best_d, best = d, i
        if best is not None:
            names[best] = (names[best] + " " + w["text"]).strip()
    return [n if n else f"Disciplina {i+1}" for i, n in enumerate(names)]


def _assign_value(word, slots):
    best, best_d = None, 1e9
    for si, s in enumerate(slots):
        for ci, sx in enumerate(s["sub_x"]):
            d = abs(word["x0"] - sx)
            if d < best_d:
                best_d, best = d, (si, ci)
    return best


def parse_page(page):
    """Retorna dict {turma, tipo_tabela, disciplinas:[...], alunos:{nome:{...}}}
    ou None se a pagina nao for uma tabela de notas reconhecivel."""
    words = page.extract_words(keep_blank_chars=False)
    if not words:
        return None

    turma = None
    for i, w in enumerate(words):
        if w["text"] == "EF" and i + 2 < len(words) and words[i + 1]["text"] == "-":
            turma = words[i + 2]["text"]
            break
    if turma is None:
        return None

    header_top, slots = _cluster_header_slots(words)
    if not slots:
        return None

    # linha "Nº NOME ... CONSELHO DE CLASSE" fica acima dos titulos de disciplina
    nome_tops = [w["top"] for w in words if w["text"] == "NOME"]
    top_floor = max(nome_tops) if nome_tops else 0

    tipo = "Integral" if any(w["text"] == "Integral" for w in words) else "Base Nacional Comum"

    subjects = _subject_names(words, header_top, slots)

    STATUS_WORDS = {"REGISTRADO", "PENDENTE", "AGUARDANDO", "NAO", "CONSELHO"}

    # linhas de alunos: cada aluno comeca com o numero (Nº) na margem
    # esquerda. Nomes longos quebram em 2 ou 3 linhas dentro da celula — e o
    # numero, a situacao e as notas ficam centralizados na altura da celula,
    # entre as linhas do nome. Por isso cada palavra vai para o aluno cujo
    # numero esta mais perto na vertical (faixa ate o meio do caminho para o
    # vizinho), e nao so as palavras na mesma altura do numero.
    abaixo = [w for w in words if w["top"] > header_top + 3]
    numeros = sorted((w for w in abaixo if ROW_NUM_RE.match(w["text"]) and w["x0"] <= 40),
                     key=lambda w: w["top"])
    # descarta numeros na mesma altura (ex: dois "1" na mesma linha)
    ancoras = []
    for w in numeros:
        if not ancoras or w["top"] - ancoras[-1]["top"] > 2.5:
            ancoras.append(w)
    if not ancoras:
        return {"turma": turma, "tipo_tabela": tipo, "disciplinas": subjects, "alunos": {}}
    passos = sorted(b["top"] - a["top"] for a, b in zip(ancoras, ancoras[1:]))
    passo = passos[len(passos) // 2] if passos else 16.8
    faixas = []
    for i, a in enumerate(ancoras):
        de = (ancoras[i - 1]["top"] + a["top"]) / 2 if i else a["top"] - passo / 2
        ate = (a["top"] + ancoras[i + 1]["top"]) / 2 if i + 1 < len(ancoras) else a["top"] + passo / 2
        faixas.append((max(de, header_top + 3), ate))

    groups = []
    for (de, ate), a in zip(faixas, ancoras):
        ws = [w for w in abaixo if de <= w["top"] < ate and w is not a and w["x0"] > a["x0"]]
        groups.append((a, ws))

    alunos = {}
    for numero, ws in groups:
        status_words = [w for w in ws if w["text"] in STATUS_WORDS and w["x0"] < slots[0]["x_start"]]
        if not status_words:
            continue
        status_x = min(w["x0"] for w in status_words)
        # situacao: a primeira palavra da coluna (ex: "NAO REGISTRADO" -> NAO)
        situacao = min(status_words, key=lambda w: (round(w["top"]), w["x0"]))["text"]
        name_words = [w for w in ws if w["x0"] < status_x - 1 and w["text"] not in STATUS_WORDS]
        name_words.sort(key=lambda w: (round(w["top"]), w["x0"]))
        nome = " ".join(" ".join(w["text"] for w in name_words).split())
        if not nome:
            continue
        value_words = [w for w in ws if w["x0"] >= slots[0]["x_start"] - 6]
        disc = {}
        for w in value_words:
            slot = _assign_value(w, slots)
            if slot is None:
                continue
            si, ci = slot
            key = subjects[si]
            disc.setdefault(key, {"faltas": None, "compensacoes": None, "frequencia": None, "conceito": None})
            field = ["faltas", "compensacoes", "frequencia", "conceito"][ci]
            val = w["text"]
            if field in ("faltas", "compensacoes"):
                try:
                    val = int(val)
                except ValueError:
                    val = None
            elif field == "frequencia":
                try:
                    val = float(val)
                except ValueError:
                    val = None
            disc[key][field] = val
        alunos[nome] = {"situacao_conselho": situacao, "disciplinas": disc}

    return {"turma": turma, "tipo_tabela": tipo, "disciplinas": subjects, "alunos": alunos}


_CANONICAL_HINTS = [
    ("CLUBE DA LEITURA", "I - Educomunicação e Novas Linguagens (Clube da Leitura)"),
    ("EDUCOMUNICACAO", "I - Educomunicação e Novas Linguagens"),
    ("ARTES VISUAIS", "II - Culturas, Arte e Memória"),
    ("CONHECIMENTOS MATEMATICOS", "III - Orientação de Estudos e Invenção Criativa (Matemática/Científico)"),
    ("PEDAGOGICA_SPI", "III - Orientação de Estudos e Invenção Criativa (Fortalecimento das Aprendizagens)"),
    ("FORTALECIMENTO", "III - Orientação de Estudos e Invenção Criativa (Fortalecimento das Aprendizagens)"),
    ("ATIVIDADES FISICAS", "VI - Cultura Corporal e Promoção da Saúde (Atividades Físicas e Recreativas)"),
    ("GREMIO ESTUDANTIL", "VI - Cultura Corporal e Promoção da Saúde (Grêmio Estudantil)"),
    ("SUSTENTABILIDADE", "IV - Consciência e Sustentabilidade Socioambiental"),
]


def _normalize_subject(name):
    up = name.upper()
    for hint, canonical in _CANONICAL_HINTS:
        if hint in up:
            return canonical
    return name


def parse_pdf(path, turmas_alvo=None):
    """Le o PDF inteiro e devolve {turma: {aluno: {disciplina: {...}}}}"""
    resultado = {}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            info = parse_page(page)
            if not info:
                continue
            if turmas_alvo and info["turma"] not in turmas_alvo:
                continue
            turma_dict = resultado.setdefault(info["turma"], {})
            for nome, dados in info["alunos"].items():
                aluno = turma_dict.setdefault(nome, {"situacao_conselho": None, "disciplinas": {}})
                if dados["situacao_conselho"]:
                    aluno["situacao_conselho"] = dados["situacao_conselho"]
                for disc, valores in dados["disciplinas"].items():
                    aluno["disciplinas"][_normalize_subject(disc)] = valores
    return resultado
