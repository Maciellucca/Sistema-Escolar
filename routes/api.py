"""
API JSON interna, consumida pelo próprio front-end via JavaScript
(fetch). Não é uma API pública — exige a mesma sessão de login da equipe
escolar que as telas HTML usam.
"""
from flask import Blueprint, jsonify, request, session, abort

import config
from models import get_db
from auth import login_required, roles_required

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/alunos")
@login_required
def alunos_busca():
    """Busca ao vivo de alunos em qualquer turma (usada em várias telas
    pra vincular um registro a um aluno, e na busca do painel principal).
    Exige pelo menos 2 caracteres — nunca devolve a lista inteira de uma
    vez. Busca por nome de registro OU nome social; o campo "nome" da
    resposta já vem como o nome de EXIBIÇÃO (nome social, se tiver)."""
    termo = request.args.get("q", "").strip()
    if len(termo) < 2:
        return jsonify([])
    with get_db() as db:
        linhas = db.execute(
            """SELECT id, nome, nome_social, turma FROM students
               WHERE nome LIKE ? OR nome_social LIKE ? ORDER BY nome LIMIT 20""",
            (f"%{termo}%", f"%{termo}%"),
        ).fetchall()
    return jsonify([
        {"id": a["id"], "nome": a["nome_social"] or a["nome"], "turma": a["turma"]} for a in linhas
    ])


@api_bp.route("/responsaveis")
@login_required
def responsaveis_busca():
    """Busca ao vivo pelo nome do responsável (filiação do cadastro,
    responsável legal dos telefones e responsável da SPTrans), para achar o
    aluno a partir de quem está no balcão ou ao telefone. Mínimo de 2
    caracteres; alunos ativos primeiro."""
    termo = request.args.get("q", "").strip()
    if len(termo) < 2:
        return jsonify([])
    like = f"%{termo}%"
    with get_db() as db:
        linhas = db.execute(
            """SELECT s.id, s.nome, s.nome_social, s.turma, s.situacao,
                      s.filiacao1, c.responsavel_legal, sp.nome_responsavel
               FROM students s
               LEFT JOIN contatos_responsaveis c ON c.student_id = s.id
               LEFT JOIN sptrans_dados_aluno sp ON sp.student_id = s.id
               WHERE s.filiacao1 LIKE ? OR c.responsavel_legal LIKE ? OR sp.nome_responsavel LIKE ?
               ORDER BY CASE WHEN s.situacao = 'ATIVO' THEN 0 ELSE 1 END, s.nome
               LIMIT 20""",
            (like, like, like),
        ).fetchall()
    termo_min = termo.lower()
    saida = []
    for r in linhas:
        # mostra o nome que bateu com a busca (pode ser mais de um)
        achados = []
        for rotulo, nome in (("Filiação", r["filiacao1"]), ("Responsável legal", r["responsavel_legal"]),
                             ("Responsável (SPTrans)", r["nome_responsavel"])):
            if nome and termo_min in nome.lower() and nome.strip().upper() not in {a[1].upper() for a in achados}:
                achados.append((rotulo, nome.strip()))
        if not achados:  # LIKE do banco ignora maiúsculas/acentos de outro jeito: mostra a filiação
            achados = [("Filiação", r["filiacao1"] or r["responsavel_legal"] or r["nome_responsavel"] or "")]
        saida.append({
            "id": r["id"], "aluno": r["nome_social"] or r["nome"], "turma": r["turma"],
            "ativo": (r["situacao"] or "").upper() == "ATIVO", "situacao": r["situacao"],
            "responsavel": achados[0][1], "tipo": achados[0][0],
        })
    return jsonify(saida)


# fonte -> (SELECT que devolve uma coluna "valor", colunas onde procurar).
# Whitelist fixa: o front só escolhe a fonte pelo nome, nunca monta SQL.
FONTES_SUGESTAO = {
    "alunos": (
        "SELECT COALESCE(nome_social, nome) AS valor FROM students WHERE situacao = 'ATIVO'",
        ("nome", "nome_social"),
    ),
    "bolsa_familia": (
        "SELECT COALESCE(nome_social, nome) AS valor FROM students "
        "WHERE situacao = 'ATIVO' AND bolsa_familia = 1",
        ("nome", "nome_social"),
    ),
    "teg_alunos": (
        "SELECT COALESCE(s.nome_social, s.nome) AS valor FROM teg_alunos t "
        "JOIN students s ON s.id = t.student_id WHERE s.situacao = 'ATIVO'",
        ("s.nome", "s.nome_social"),
    ),
    "teg_condutores": (
        "SELECT DISTINCT nome_condutor AS valor FROM teg_alunos WHERE nome_condutor IS NOT NULL",
        ("nome_condutor",),
    ),
    "arquivo_morto": (
        "SELECT DISTINCT nome AS valor FROM arquivo_morto WHERE 1 = 1",
        ("nome",),
    ),
}


@api_bp.route("/sugestoes/<fonte>")
@roles_required("admin", "secretaria")
def sugestoes(fonte):
    """Sugestões pros campos de busca (autocompletar enquanto digita):
    devolve até 12 nomes compatíveis com ?q=, os que COMEÇAM com o termo
    primeiro. Só nomes — quem escolhe um deles envia o formulário de busca
    normal da tela."""
    if fonte not in FONTES_SUGESTAO:
        abort(404)
    termo = request.args.get("q", "").strip()
    if not termo:
        return jsonify([])
    base, colunas = FONTES_SUGESTAO[fonte]
    filtro = " OR ".join(f"{c} LIKE ?" for c in colunas)
    with get_db() as db:
        linhas = db.execute(
            f"{base} AND ({filtro}) ORDER BY valor LIMIT 200",
            tuple(f"%{termo}%" for _ in colunas),
        ).fetchall()
    termo_min = termo.lower()
    vistos, valores = set(), []
    for r in linhas:
        v = r["valor"]
        if v and v not in vistos:
            vistos.add(v)
            valores.append(v)
    valores.sort(key=lambda v: (not v.lower().startswith(termo_min), v.lower()))
    return jsonify(valores[:12])


@api_bp.route("/turma/<turma>/alunos")
@login_required
def alunos_turma(turma):
    """Busca ao vivo de alunos dentro de uma turma (usada pelo campo de
    busca da tela de turma). ?q=<termo> filtra por nome (de registro ou
    social). O campo "nome" da resposta já vem como o nome de EXIBIÇÃO
    (nome social, se tiver; senão o de registro) — quem consome esse
    JSON não precisa saber da distinção."""
    termo = request.args.get("q", "").strip()
    with get_db() as db:
        if termo:
            linhas = db.execute(
                """SELECT id, nome, nome_social, foto_path, aee, situacao FROM students
                   WHERE turma = ? AND (nome LIKE ? OR nome_social LIKE ?) ORDER BY nome""",
                (turma, f"%{termo}%", f"%{termo}%"),
            ).fetchall()
        else:
            linhas = db.execute(
                "SELECT id, nome, nome_social, foto_path, aee, situacao FROM students WHERE turma = ? ORDER BY nome",
                (turma,),
            ).fetchall()
    return jsonify([
        {
            "id": a["id"],
            "nome": a["nome_social"] or a["nome"],
            "foto_url": f"/fotos/{a['foto_path']}" if a["foto_path"] else None,
            "aee": bool(a["aee"]),
            "situacao": a["situacao"],
        }
        for a in linhas
    ])


@api_bp.route("/turma/<turma>/estatisticas")
@login_required
def estatisticas_turma(turma):
    """Estatísticas agregadas da turma a partir das notas já importadas:
    frequência média por bimestre e distribuição de conceitos/notas.
    Usado pelo painel de análise de dados da tela de turma."""
    with get_db() as db:
        existe = db.execute("SELECT 1 FROM students WHERE turma = ? LIMIT 1", (turma,)).fetchone()
        if not existe:
            abort(404)

        freq_por_bimestre = db.execute(
            """SELECT g.ano, g.bimestre, ROUND(AVG(g.frequencia), 1) AS media
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE s.turma = ? AND s.situacao = 'ATIVO' AND g.frequencia IS NOT NULL
               GROUP BY g.ano, g.bimestre ORDER BY g.ano, g.bimestre""",
            (turma,),
        ).fetchall()

        distrib_conceito = db.execute(
            """SELECT g.conceito, COUNT(*) AS total
               FROM grades g JOIN students s ON s.id = g.student_id
               WHERE s.turma = ? AND s.situacao = 'ATIVO' AND g.conceito IS NOT NULL AND g.conceito != ''
               GROUP BY g.conceito ORDER BY total DESC""",
            (turma,),
        ).fetchall()

        total_alunos = db.execute(
            "SELECT COUNT(*) c FROM students WHERE turma = ? AND situacao = 'ATIVO'", (turma,)
        ).fetchone()["c"]
        total_aee = db.execute(
            "SELECT COUNT(*) c FROM students WHERE turma = ? AND situacao = 'ATIVO' AND aee = 1", (turma,)
        ).fetchone()["c"]

    return jsonify({
        "turma": turma,
        "total_alunos": total_alunos,
        "total_aee": total_aee,
        "frequencia_por_bimestre": [
            {"ano": r["ano"], "bimestre": r["bimestre"], "media": r["media"]} for r in freq_por_bimestre
        ],
        "distribuicao_conceito": [
            {"conceito": r["conceito"], "total": r["total"]} for r in distrib_conceito
        ],
    })
