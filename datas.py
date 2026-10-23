"""
Datas na tela e nos documentos sempre no formato da escola: dd/mm/aaaa.

No banco elas continuam em aaaa-mm-dd (padrão ISO): é o que deixa ordenar,
comparar e calcular idade, e o que o campo <input type="date"> do navegador
usa (o navegador mostra o campo em dd/mm/aaaa sozinho). A conversão é feita
só na hora de mostrar, pelos filtros do Jinja registrados em app.py:

    {{ aluno['data_nascimento']|data_br }}         -> 26/06/2018
    {{ atendimento['data_hora']|data_hora_br }}    -> 26/06/2018 14:30
    {{ registro['updated_at']|hora_brasilia }}     -> horário de Brasília
"""
import re
from datetime import date, datetime

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?")


def data_br(valor, vazio=""):
    """'2018-06-26' (ou date/datetime) -> '26/06/2018'. Texto que não é data
    ISO (ex: já em dd/mm/aaaa) volta como está; vazio -> `vazio`."""
    if valor is None or valor == "":
        return vazio
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    m = _ISO.match(str(valor).strip())
    if not m:
        return str(valor)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"


def data_hora_br(valor, vazio=""):
    """'2026-10-06 14:30[:00]' -> '06/10/2026 14:30' (sem mudar o fuso: para
    horários digitados pela equipe, como os da agenda)."""
    if valor is None or valor == "":
        return vazio
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    m = _ISO.match(str(valor).strip())
    if not m:
        return str(valor)
    texto = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return f"{texto} {m.group(4)}:{m.group(5)}" if m.group(4) else texto
