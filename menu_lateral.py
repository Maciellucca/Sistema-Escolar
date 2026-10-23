"""
Menu lateral: itens, categorias e a ordem configurada pelo admin.

Cada item tem rótulo, rota, quem pode ver (None = toda a equipe), como
saber se é a tela atual e o ícone. Os itens ficam agrupados em
categorias (config.GRUPOS_SIDEBAR); o admin muda a ordem das categorias e
dos itens dentro de cada uma em "Ordem do menu lateral" — fica salvo na
tabela configuracoes (chaves 'ordem_sidebar_grupos' e 'ordem_sidebar').

As importações (notas e alunos) não ficam na barra: aparecem no menu da
conta, no topo da tela (ITENS_MENU_CONTA).
"""
from flask import request, url_for

import config

ADM_SEC = ("admin", "secretaria")


def _prefixo(*prefixos, extras=()):
    def ativo(endpoint):
        return endpoint.startswith(prefixos) or endpoint in extras
    return ativo


ITENS = {
    "inicio": {
        "endpoint": "staff.dashboard", "papeis": None,
        "ativo": lambda e: e == "staff.dashboard",
        "icone": '<path d="M4 11.5 12 4l8 7.5"/><path d="M6 10v9a1 1 0 0 0 1 1h4v-6h2v6h4a1 1 0 0 0 1-1v-9"/>',
    },
    "importar_notas": {
        "endpoint": "importacao.notas_index", "papeis": ADM_SEC,
        "ativo": lambda e: e in ("importacao.notas_index", "importacao.notas_upload", "importacao.revisar",
                                 "importacao.confirmar", "importacao.descartar"),
        "icone": '<path d="M12 4v11m0-11 4 4m-4-4-4 4"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    },
    "importar_alunos": {
        "endpoint": "importacao.alunos_index", "papeis": ADM_SEC,
        "ativo": lambda e: e.startswith("importacao.") and "alunos" in e,
        "icone": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>',
    },
    "arquivo_morto": {
        "endpoint": "arquivo_morto.index", "papeis": ADM_SEC, "ativo": _prefixo("arquivo_morto."),
        "icone": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/>',
    },
}

# itens que ficam no menu da conta (topo), fora da barra lateral
ITENS_MENU_CONTA = ("importar_notas", "importar_alunos")


def _validar(salva, padrao):
    """Ordem salva, só com ids que ainda existem; itens novos (de algo
    adicionado depois de o admin configurar a ordem) entram no fim."""
    ordem = [i for i in (salva or "").split(",") if i in padrao]
    return ordem + [i for i in padrao if i not in ordem]


def itens_do_grupo_padrao():
    return [i for g in config.GRUPOS_SIDEBAR for i in g["itens"]]


def ordem_grupos(db):
    from models import get_config
    return _validar(get_config(db, "ordem_sidebar_grupos"), [g["id"] for g in config.GRUPOS_SIDEBAR])


def ordem_itens(db):
    from models import get_config
    return _validar(get_config(db, "ordem_sidebar"), itens_do_grupo_padrao())


def grupos_ordenados(db):
    """[(grupo, [ids dos itens na ordem configurada])] na ordem configurada."""
    por_id = {g["id"]: g for g in config.GRUPOS_SIDEBAR}
    itens = ordem_itens(db)
    return [(por_id[gid], [i for i in itens if i in por_id[gid]["itens"]]) for gid in ordem_grupos(db)]


def _pode_ver(item_id, papel):
    papeis = ITENS[item_id]["papeis"]
    return papeis is None or papel in papeis


def _montar_item(item_id, endpoint_atual):
    item = ITENS[item_id]
    rotulo = config.ROTULOS_SIDEBAR[item_id]
    return {
        "id": item_id, "rotulo": rotulo, "titulo": item.get("titulo", rotulo),
        "url": url_for(item["endpoint"]), "ativo": item["ativo"](endpoint_atual), "icone": item["icone"],
    }


def menu_do_usuario(db, papel):
    """Menu pronto pro template: Início fixo no topo, categorias com os
    itens que esse papel pode ver (categoria sem item visível some) e os
    atalhos do menu da conta."""
    endpoint = request.endpoint or ""
    grupos = []
    for grupo, ids in grupos_ordenados(db):
        itens = [_montar_item(i, endpoint) for i in ids if _pode_ver(i, papel)]
        if itens:
            grupos.append({"id": grupo["id"], "rotulo": grupo["rotulo"], "itens": itens,
                           "ativo": any(i["ativo"] for i in itens)})
    return {
        "inicio": _montar_item("inicio", endpoint),
        "grupos": grupos,
        "conta": [_montar_item(i, endpoint) for i in ITENS_MENU_CONTA if _pode_ver(i, papel)],
    }
