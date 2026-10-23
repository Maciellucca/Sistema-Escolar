"""
Aplica de uma vez o mapeamento de turno (Manhã/Integral/Tarde) por turma,
conforme informado pela escola. Rode de novo quando as turmas mudarem —
ele só ATUALIZA/insere, nunca apaga turma que não estiver nas listas
abaixo (essas continuam com o turno que já tinham, ou sem turno definido).

Se sua rede tiver um mapeamento diferente, edite as três listas abaixo
antes de rodar — ou, mais simples, use a tela "Configurar turnos" no
sistema (menu do painel principal), que faz a mesma coisa pelo navegador.

Uso:
    python scripts/seed_turnos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import get_db, init_db, salvar_turma_turno

MANHA = ["4A", "4B", "4C", "5A", "5B", "6A", "6B", "6C", "6D", "6E", "8A", "8B", "8C", "9A", "9B", "9C"]
INTEGRAL = ["1A", "1B", "1C", "1D", "2A", "2B", "2C", "2D", "3A", "3B", "3C", "3D"]
TARDE = ["7A", "7B", "7C", "7D"]


def seed():
    init_db()
    with get_db() as db:
        for turma in MANHA:
            salvar_turma_turno(db, turma, "Manhã")
        for turma in INTEGRAL:
            salvar_turma_turno(db, turma, "Integral")
        for turma in TARDE:
            salvar_turma_turno(db, turma, "Tarde")
    total = len(MANHA) + len(INTEGRAL) + len(TARDE)
    print(f"Turnos aplicados: {len(MANHA)} turma(s) na Manhã, {len(INTEGRAL)} no Integral, "
          f"{len(TARDE)} na Tarde ({total} no total).")


if __name__ == "__main__":
    seed()
