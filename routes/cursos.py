"""
Utilitários de série e ciclo de ensino, usados pelo portal do responsável.
Neste recorte do sistema não há tela de cursos recomendados: só as funções
abaixo, que convertem a série do aluno no ciclo do Ensino Fundamental.
"""
import re

CICLOS = ["Alfabetização", "Interdisciplinar", "Autoral"]


def ciclo_da_serie(serie):
    """Converte a série do aluno (ex: '5º Ano') no ciclo correspondente
    (Alfabetização 1º-3º, Interdisciplinar 4º-6º, Autoral 7º-9º). Devolve
    None se não reconhecer o número da série."""
    if not serie:
        return None
    m = re.match(r"\s*(\d+)", serie)
    if not m:
        return None
    numero = int(m.group(1))
    if 1 <= numero <= 3:
        return "Alfabetização"
    if 4 <= numero <= 6:
        return "Interdisciplinar"
    if 7 <= numero <= 9:
        return "Autoral"
    return None


def serie_com_turma(serie, turma):
    """Junta a série com a letra da turma (ex: '3º Ano' + '3B' -> '3º Ano B')."""
    if not serie:
        return turma or "—"
    m = re.match(r"^\d+", turma or "")
    if not m:
        return f"{serie} ({turma})" if turma else serie
    letra = (turma or "")[m.end():].strip()
    return f"{serie} {letra}".strip() if letra else serie
