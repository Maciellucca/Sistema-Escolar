"""
Copia todos os dados de um banco SQLite do sistema (o arquivo
sistema_escolar.db) para o MySQL configurado no ambiente, junto com as fotos
que estiverem nas pastas locais.

Uso (no computador, com o arquivo .db salvo e a URL do MySQL da nuvem):

    set MYSQL_URL=mysql://usuario:senha@host:porta/banco?ssl-mode=REQUIRED      (Windows)
    export MYSQL_URL='mysql://usuario:senha@host:porta/banco?ssl-mode=REQUIRED' (Linux/Mac)
    python scripts/migrar_sqlite_para_mysql.py caminho/sistema_escolar.db

Opções:
    --fotos PASTA       pasta das fotos dos alunos (padrão: "photos" ao lado do .db)
    --relatorios PASTA  pasta das fotos dos relatórios (padrão: "relatorios_fotos" ao lado do .db)
    --substituir        apaga o que já existir no MySQL antes de copiar (sem
                        isso, o script para se o MySQL já tiver alunos)

O MySQL de destino recebe a estrutura completa (init_db) e, em seguida, os
dados de cada tabela; os ids são mantidos, então as ligações entre as
tabelas continuam certas.
"""
import argparse
import mimetypes
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

LOTE = 500
TIPOS_DATA = {"date", "datetime", "timestamp", "time", "int", "tinyint", "smallint", "bigint", "decimal", "float", "double"}


def _colunas_mysql(db, tabela):
    return {r["COLUMN_NAME"]: r["DATA_TYPE"] for r in db.execute(
        "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
        (tabela,),
    ).fetchall()}


def _arquivos_da_pasta(pasta, categoria):
    pasta = Path(pasta)
    if not pasta.is_dir():
        return []
    return [(categoria, p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            for p in sorted(pasta.iterdir()) if p.is_file()]


def migrar(caminho_sqlite, pasta_fotos=None, pasta_relatorios=None, substituir=False, saida=print):
    if config.DB_BACKEND != "mysql":
        raise SystemExit("Configure o MySQL de destino (MYSQL_URL ou DB_BACKEND=mysql + MYSQL_*) antes de rodar.")
    origem_path = Path(caminho_sqlite)
    if not origem_path.is_file():
        raise SystemExit(f"Arquivo não encontrado: {origem_path}")

    from models import agora, get_db, init_db

    init_db()  # estrutura completa no MySQL
    origem = sqlite3.connect(str(origem_path))
    origem.row_factory = sqlite3.Row
    tabelas = [r["name"] for r in origem.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    resumo = {}
    with get_db() as db:
        if not substituir and db.execute("SELECT COUNT(*) AS n FROM students").fetchone()["n"]:
            raise SystemExit("O MySQL de destino já tem alunos. Rode com --substituir para apagar e copiar de novo.")
        db.execute("SET FOREIGN_KEY_CHECKS = 0")
        for tabela in tabelas:
            destino = _colunas_mysql(db, tabela)
            if not destino:
                saida(f"  (ignorada: tabela {tabela} não existe no MySQL)")
                continue
            cols_origem = [r["name"] for r in origem.execute(f"PRAGMA table_info({tabela})")]
            cols = [c for c in cols_origem if c in destino]
            db.execute(f"DELETE FROM `{tabela}`")  # tira os registros-padrão criados pelo init_db
            linhas = origem.execute(f"SELECT {', '.join(cols)} FROM {tabela}").fetchall()
            sql = f"INSERT INTO `{tabela}` ({', '.join('`' + c + '`' for c in cols)}) VALUES ({', '.join('?' for _ in cols)})"
            for i in range(0, len(linhas), LOTE):
                for linha in linhas[i:i + LOTE]:
                    valores = []
                    for c in cols:
                        v = linha[c]
                        if v == "" and destino[c] in TIPOS_DATA:
                            v = None  # SQLite aceita texto vazio em coluna de data/número; MySQL não
                        valores.append(v)
                    db.execute(sql, valores)
            resumo[tabela] = len(linhas)
            saida(f"  {tabela}: {len(linhas)} registro(s)")

        pasta_base = origem_path.parent
        arquivos = (_arquivos_da_pasta(pasta_fotos or pasta_base / "photos", "fotos")
                    + _arquivos_da_pasta(pasta_relatorios or pasta_base / "relatorios_fotos", "relatorios"))
        for categoria, nome, conteudo, tipo in arquivos:
            db.execute("DELETE FROM arquivos WHERE categoria = ? AND nome = ?", (categoria, nome))
            db.execute("INSERT INTO arquivos (categoria, nome, conteudo, tipo, tamanho, updated_at) VALUES (?,?,?,?,?,?)",
                       (categoria, nome, conteudo, tipo, len(conteudo), agora()))
        resumo["(arquivos de fotos)"] = len(arquivos)
        saida(f"  fotos copiadas para o banco: {len(arquivos)}")
        db.execute("SET FOREIGN_KEY_CHECKS = 1")
    origem.close()
    init_db()  # migrações e registros-padrão que faltarem (ex: modelos de WhatsApp novos)
    return resumo


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sqlite", help="arquivo sistema_escolar.db")
    p.add_argument("--fotos")
    p.add_argument("--relatorios")
    p.add_argument("--substituir", action="store_true")
    a = p.parse_args()
    print(f"Copiando {a.sqlite} para o MySQL {config.MYSQL_HOST}:{config.MYSQL_PORT}/{config.MYSQL_DATABASE}...")
    resumo = migrar(a.sqlite, a.fotos, a.relatorios, a.substituir)
    print(f"Pronto: {sum(resumo.values())} registro(s) copiados.")


if __name__ == "__main__":
    main()
