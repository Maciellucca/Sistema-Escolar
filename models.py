"""
SISTEMA ESCOLAR - camada de dados.

Suporta dois bancos, escolhidos por config.DB_BACKEND ("sqlite" ou
"mysql"), sem que o resto da aplicação precise saber qual está em uso:
routes/ e scripts/ sempre chamam get_db() e escrevem SQL com "?" como
placeholder — a tradução para MySQL (%s) acontece aqui dentro.

- sqlite (padrão): zero configuração, ótimo para rodar local e para os
  testes automatizados.
- mysql: banco relacional "de verdade", pensado para o projeto integrador
  (docs/MYSQL.md tem o passo a passo de configuração).
"""
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import config


def agora():
    """Timestamp atual em UTC, no formato aceito por ambos os bancos.
    Usado no código Python em vez de datetime('now')/NOW() do SQL, para
    o mesmo código funcionar nos dois backends sem depender da timezone
    configurada no servidor do banco."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------- SQLite ----
SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    nome TEXT NOT NULL,
    setor TEXT,
    papel TEXT NOT NULL CHECK (papel IN ('admin','professor','aee','secretaria','direcao','pot')),
    ativo INTEGER NOT NULL DEFAULT 1,
    rg TEXT,
    nome_completo_declaracao TEXT,
    email TEXT,
    trocar_senha INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Códigos de "Esqueci minha senha" enviados por e-mail: só o hash do
-- código fica salvo; vale por poucos minutos, uma vez, e com limite de
-- tentativas erradas.
CREATE TABLE IF NOT EXISTS password_reset_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    codigo_hash TEXT NOT NULL,
    expira_em TEXT NOT NULL,
    tentativas INTEGER NOT NULL DEFAULT 0,
    usado INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_interno TEXT UNIQUE,
    nis TEXT,
    bolsa_familia INTEGER NOT NULL DEFAULT 0,
    ra_prodesp TEXT,
    inep TEXT,
    nome TEXT NOT NULL,
    nome_social TEXT,
    filiacao1 TEXT,
    data_nascimento TEXT,
    turma TEXT NOT NULL,
    serie TEXT,
    situacao TEXT,
    foto_path TEXT,
    guardian_token_hash TEXT,
    guardian_codigo TEXT UNIQUE,
    aee INTEGER NOT NULL DEFAULT 0,
    rg TEXT,
    certidao_nascimento TEXT,
    municipio_nascimento TEXT,
    recomendacoes TEXT,
    alteracoes_pendentes TEXT,
    data_transferencia TEXT,
    estado_nascimento TEXT,
    nacionalidade TEXT,
    rg_data_expedicao TEXT,
    rg_orgao_expedidor TEXT,
    rg_estado_emissor TEXT,
    certidao_numero TEXT,
    certidao_folha TEXT,
    certidao_livro TEXT,
    certidao_distrito_municipio TEXT,
    certidao_uf TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aee_info (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    eol TEXT,
    laudo TEXT,
    observacoes TEXT,
    deficiencia TEXT,
    turno TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    ano INTEGER NOT NULL,
    bimestre INTEGER NOT NULL,
    disciplina TEXT NOT NULL,
    faltas INTEGER,
    compensacoes INTEGER,
    frequencia REAL,
    conceito TEXT,
    situacao_conselho TEXT,
    origem TEXT DEFAULT 'importado',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, ano, bimestre, disciplina)
);

CREATE TABLE IF NOT EXISTS access_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    referencia TEXT,
    acao TEXT NOT NULL,
    ip TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo TEXT,
    ano INTEGER NOT NULL,
    bimestre INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','confirmado','descartado')),
    criado_por TEXT,
    total_alunos INTEGER DEFAULT 0,
    total_nao_localizados INTEGER DEFAULT 0,
    total_gravado INTEGER DEFAULT 0,
    processando INTEGER NOT NULL DEFAULT 0,
    erro_mensagem TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    confirmado_em TEXT
);

CREATE TABLE IF NOT EXISTS grades_staging (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id INTEGER NOT NULL REFERENCES import_lotes(id) ON DELETE CASCADE,
    aluno_key TEXT NOT NULL,
    turma_pdf TEXT,
    nome_pdf TEXT,
    student_id INTEGER REFERENCES students(id),
    disciplina TEXT NOT NULL,
    faltas INTEGER,
    compensacoes INTEGER,
    frequencia REAL,
    conceito TEXT,
    situacao_conselho TEXT,
    incluir INTEGER NOT NULL DEFAULT 1
);

-- Resultado final digitado à mão pela equipe para anos/séries que o
-- sistema não tem em `grades` (anos anteriores à adoção do sistema, aluno
-- transferido de outra escola, etc.) — usado para completar o Histórico
-- Escolar. Quando há dado em `grades` para a série atual do aluno, ele tem
-- prioridade; isto aqui é só para preencher o que falta.
CREATE TABLE IF NOT EXISTS historico_manual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    serie TEXT NOT NULL,
    disciplina TEXT NOT NULL,
    resultado TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, serie, disciplina)
);

-- Configurações simples de chave/valor (ex: ID da Unidade de Ensino na
-- SPTrans) — evita criar uma coluna/tabela nova a cada ajuste pequeno.
CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Código de Curso/Turma que a própria SPTrans atribui (documento "Cursos e
-- Turmas" da SPTrans, fora do nosso sistema) — cadastrado uma vez por
-- turma pela secretaria, reaproveitado em toda exportação.
CREATE TABLE IF NOT EXISTS sptrans_turma_codigo (
    turma TEXT PRIMARY KEY,
    codigo_curso TEXT,
    codigo_turma TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Turno de cada turma (Manhã/Tarde/Integral) — organização específica de
-- cada escola, por isso fica configurável (não é regra fixa do sistema).
-- Turma sem linha aqui aparece como "Turno não definido" no painel.
CREATE TABLE IF NOT EXISTS turma_turno (
    turma TEXT PRIMARY KEY,
    turno TEXT NOT NULL CHECK (turno IN ('Manhã','Tarde','Integral')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dados pessoais extras exigidos SÓ pela planilha de matrícula da SPTrans
-- (passe livre estudantil) — ficam numa tabela própria, separados do
-- cadastro principal do aluno, porque incluem CPF e endereço (dado
-- sensível que a maioria das telas do sistema não precisa enxergar).
CREATE TABLE IF NOT EXISTS sptrans_dados_aluno (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    cpf TEXT,
    rg_numero TEXT,
    rg_digito TEXT,
    rg_uf TEXT,
    cep TEXT,
    endereco_numero TEXT,
    endereco_complemento TEXT,
    telefone TEXT,
    email TEXT,
    nome_responsavel TEXT,
    tipo_gratuidade TEXT NOT NULL DEFAULT '0',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Telefones de contato dos responsáveis — separado do cadastro principal
-- (mesmo espírito de sptrans_dados_aluno): número de cada filiação, o
-- responsável legal (pode ser diferente dos pais) e um número de recados
-- (ex: vizinho, outro parente) para quando não conseguir contato direto.
CREATE TABLE IF NOT EXISTS contatos_responsaveis (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    telefone_filiacao1 TEXT,
    telefone_filiacao2 TEXT,
    responsavel_legal TEXT,
    telefone_recados TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Bolsa Família / Programa Frequência (F75) — frequência mensal lançada
-- manualmente pela secretaria (faltas do mês + motivo quando abaixo do
-- mínimo), pra organizar o que depois é transcrito à mão no portal do
-- governo (Sistema Presença) a cada período bimestral.
CREATE TABLE IF NOT EXISTS frequencia_mensal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    ano INTEGER NOT NULL,
    mes INTEGER NOT NULL,
    faltas INTEGER,
    motivo TEXT,
    percentual INTEGER,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, ano, mes)
);
CREATE INDEX IF NOT EXISTS idx_frequencia_student ON frequencia_mensal(student_id);

-- Conferência de documentos: o que cada aluno ainda deve (RG, RG
-- alfabetizado, histórico, prontuário). "entregue" = ticado na tela; o
-- texto original da planilha importada fica em documentos_status.
CREATE TABLE IF NOT EXISTS documentos_pendencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    documento TEXT NOT NULL,
    entregue INTEGER NOT NULL DEFAULT 0,
    entregue_em TEXT,
    entregue_por TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, documento)
);
CREATE TABLE IF NOT EXISTS documentos_status (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    status_original TEXT,
    importado_em TEXT
);

-- Feriados e dias sem aula: na lista de chamada a coluna do dia leva
-- FERIADO (aba Chamadas, onde a lista é editada).
CREATE TABLE IF NOT EXISTS feriados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL UNIQUE,
    descricao TEXT
);

-- Turmas de projeto (ex: PAP, Aprender e Ensinar), importadas do relatório
-- "Alunos da Turma" do SGP. Não mexem na turma regular do aluno: cada
-- aluno do projeto fica em turma_projeto_alunos, ligado pelo código EOL.
CREATE TABLE IF NOT EXISTS turmas_projeto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    turma TEXT,
    descricao TEXT,
    turno TEXT,
    ano INTEGER,
    unidade TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS turma_projeto_alunos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turma_projeto_id INTEGER NOT NULL REFERENCES turmas_projeto(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    codigo_eol TEXT NOT NULL,
    numero TEXT,
    nome TEXT NOT NULL,
    situacao TEXT,
    data_inclusao TEXT,
    UNIQUE(turma_projeto_id, codigo_eol)
);
CREATE INDEX IF NOT EXISTS idx_turma_projeto_alunos_student ON turma_projeto_alunos(student_id);

-- Arquivos enviados (fotos dos alunos, fotos dos relatórios escolares)
-- guardados no próprio banco — veja arquivos.py.
CREATE TABLE IF NOT EXISTS arquivos (
    categoria TEXT NOT NULL,
    nome TEXT NOT NULL,
    conteudo BLOB NOT NULL,
    tipo TEXT,
    tamanho INTEGER,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (categoria, nome)
);

-- Modelos de mensagem de WhatsApp (tela WhatsApp). Os que têm chave são os
-- padrões do sistema (whatsapp.MODELOS_PADRAO): podem ser editados, não
-- excluídos. Os sem chave são os criados pela escola.
CREATE TABLE IF NOT EXISTS whatsapp_modelos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave TEXT UNIQUE,
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    atualizado_por TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Códigos de motivo da baixa frequência cadastrados pela escola, além da
-- lista oficial fixa (motivos_frequencia.MOTIVOS).
CREATE TABLE IF NOT EXISTS motivos_frequencia_escola (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    categoria TEXT NOT NULL,
    descricao TEXT NOT NULL,
    criado_por TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dias letivos de cada mês do ano letivo, cadastrados manualmente pela
-- secretaria (segue o calendário oficial da rede, que varia por ano) —
-- usado pra calcular a % de frequência a partir das faltas lançadas em
-- frequencia_mensal, sem o sistema ter que adivinhar um calendário.
-- Situação coletiva do mês no Bolsa Família (férias, greve, recesso...):
-- vale para todos os alunos do programa e sai na Declaração de Frequência,
-- na célula ao lado da % do mês.
CREATE TABLE IF NOT EXISTS situacoes_coletivas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ano INTEGER NOT NULL,
    mes INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    criado_por TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ano, mes)
);

-- Chamada diária (grupo Equipe): um registro por aluno e dia letivo.
-- status C = compareceu, F = faltou; justificada = 1 marca a falta com o
-- círculo vermelho e guarda o motivo (que aparece ao passar o mouse).
CREATE TABLE IF NOT EXISTS chamada_diaria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('C', 'F')),
    justificada INTEGER NOT NULL DEFAULT 0,
    motivo TEXT,
    registrado_por TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, data)
);

-- Fichas de matrícula preenchidas na guia "Ficha de Matrícula": os dados
-- digitados ficam em JSON (dados) e saem nos modelos oficiais em PDF
-- (Ficha de Matrícula, Ficha de Saúde e Dados do Responsável).
CREATE TABLE IF NOT EXISTS fichas_matricula (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    nome TEXT NOT NULL,
    turma TEXT,
    ano INTEGER,
    dados TEXT NOT NULL,
    criado_por TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dias_letivos_mensais (
    ano INTEGER NOT NULL,
    mes INTEGER NOT NULL,
    dias_letivos INTEGER NOT NULL,
    PRIMARY KEY (ano, mes)
);

-- TEG (Transporte Escolar Gratuito) — dados de cada aluno inscrito no
-- transporte, importados da planilha "Inscritos_Teg" gerada pelo
-- sistema da rede. Uma linha por aluno (o mesmo aluno não aparece duas
-- vezes na planilha de origem).
CREATE TABLE IF NOT EXISTS teg_alunos (
    student_id INTEGER PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    turno TEXT,
    motivo_codigo INTEGER,
    motivo_descricao TEXT,
    distancia_metros INTEGER,
    cadeirante TEXT,
    tipo_logradouro TEXT,
    logradouro TEXT,
    numero_endereco TEXT,
    complemento TEXT,
    bairro TEXT,
    cep TEXT,
    placa_veiculo TEXT,
    nome_condutor TEXT,
    capacidade_veiculo INTEGER,
    barreira_fisica TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Telefone de cada condutor do TEG — preenchido manualmente pela escola
-- (a planilha de origem não traz telefone), pra facilitar contato caso
-- uma criança fique pra trás e não consiga identificar com clareza
-- quem é o transportador dela.
CREATE TABLE IF NOT EXISTS teg_condutores (
    nome_condutor TEXT PRIMARY KEY,
    telefone TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Arquivo morto: registro permanente de todo aluno que já passou pela
-- escola (inclusive de décadas atrás, antes deste sistema existir),
-- organizado por letra (a mesma divisão em 26 abas do arquivo em
-- planilha). Quando um aluno é marcado como transferido, entra aqui
-- automaticamente no fim da letra correspondente — student_id fica
-- preenchido nesse caso (permite voltar pro cadastro), mas fica vazio
-- pros registros só importados da planilha histórica (pré-existem ao
-- sistema, não têm um cadastro de aluno correspondente aqui).
CREATE TABLE IF NOT EXISTS arquivo_morto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    letra TEXT NOT NULL,
    numero TEXT,
    nome TEXT NOT NULL,
    data_nascimento TEXT,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    origem TEXT NOT NULL DEFAULT 'importado' CHECK (origem IN ('importado', 'transferencia', 'manual')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_arquivo_morto_letra ON arquivo_morto(letra);

-- Lista de cursos gratuitos recomendados (ex: Escola Virtual.gov/ENAP),
-- organizada pelos 3 ciclos oficiais do Ensino Fundamental na Rede
-- Municipal de SP (Alfabetização 1º-3º, Interdisciplinar 4º-6º, Autoral
-- 7º-9º) — mantida manualmente pela equipe, não sincronizada automaticamente
-- com nenhuma plataforma externa (o catálogo delas muda com frequência).
CREATE TABLE IF NOT EXISTS cursos_recomendados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    descricao TEXT,
    url TEXT,
    ciclo TEXT NOT NULL CHECK (ciclo IN ('Alfabetização','Interdisciplinar','Autoral')),
    fonte TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Agenda de atendimento com responsáveis — comunicação entre
-- secretaria/gestão e as famílias. Pode ou não estar ligado a um aluno
-- específico (às vezes é um assunto geral da secretaria).
CREATE TABLE IF NOT EXISTS atendimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    nome_responsavel TEXT NOT NULL,
    telefone_contato TEXT,
    assunto TEXT NOT NULL,
    observacoes TEXT,
    responsavel_atendimento TEXT,
    status TEXT NOT NULL DEFAULT 'agendado' CHECK (status IN ('agendado','realizado','cancelado','faltou')),
    criado_por TEXT,
    atendido_por TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Relatório Escolar (modelo oficial em papel da escola) preenchido a partir
-- de um atendimento da agenda — um por atendimento. Os campos do topo
-- (aluno, turma, nº, telefones...) começam com os dados do atendimento e
-- podem ser ajustados; "texto" é o corpo livre do relatório.
CREATE TABLE IF NOT EXISTS relatorios_escolares (
    atendimento_id INTEGER PRIMARY KEY REFERENCES atendimentos(id) ON DELETE CASCADE,
    nome_aluno TEXT,
    turma TEXT,
    numero TEXT,
    preenchido_por TEXT,
    recebido_por TEXT,
    data TEXT,
    telefone1 TEXT,
    telefone2 TEXT,
    texto TEXT,
    atualizado_por TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Fotos da ocorrência anexadas ao relatório (arquivo salvo em
-- RELATORIO_FOTOS_DIR, fora da pasta static/).
CREATE TABLE IF NOT EXISTS relatorio_fotos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    atendimento_id INTEGER NOT NULL REFERENCES atendimentos(id) ON DELETE CASCADE,
    arquivo TEXT NOT NULL,
    legenda TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_relatorio_fotos_atendimento ON relatorio_fotos(atendimento_id);

-- Afastamento por motivo de saúde — "motivo" é campo livre e OPCIONAL,
-- não pensado para guardar diagnóstico/condição médica, só o suficiente
-- pra equipe se organizar (ex: "afastamento médico", sem detalhar qual).
-- Serve de "guarda-chuva" para as atividades enviadas durante a ausência,
-- em atividades_afastamento.
CREATE TABLE IF NOT EXISTS afastamentos_saude (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    data_inicio TEXT NOT NULL,
    data_fim TEXT,
    motivo TEXT,
    observacoes TEXT,
    criado_por TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS atividades_afastamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    afastamento_id INTEGER NOT NULL REFERENCES afastamentos_saude(id) ON DELETE CASCADE,
    disciplina TEXT,
    titulo TEXT NOT NULL,
    descricao TEXT,
    data_envio TEXT NOT NULL,
    enviado_por TEXT,
    status TEXT NOT NULL DEFAULT 'enviada' CHECK (status IN ('enviada','entregue','pendente')),
    data_entrega TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Turno de cada turma (Manhã/Tarde/Integral) — usado só pra organizar o
-- painel principal em seções; configurado manualmente pela equipe porque
-- não tem como deduzir com certeza a partir dos dados importados.
CREATE TABLE IF NOT EXISTS turma_turno (
    turma TEXT PRIMARY KEY,
    turno TEXT NOT NULL CHECK (turno IN ('Manhã','Tarde','Integral')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_students_turma ON students(turma);
CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id);
CREATE INDEX IF NOT EXISTS idx_staging_lote ON grades_staging(lote_id);
CREATE INDEX IF NOT EXISTS idx_historico_manual_student ON historico_manual(student_id);
CREATE INDEX IF NOT EXISTS idx_atendimentos_data ON atendimentos(data_hora);
CREATE INDEX IF NOT EXISTS idx_atendimentos_student ON atendimentos(student_id);
CREATE INDEX IF NOT EXISTS idx_afastamentos_student ON afastamentos_saude(student_id);
CREATE INDEX IF NOT EXISTS idx_atividades_afastamento ON atividades_afastamento(afastamento_id);

-- Diário Oficial: servidores acompanhados (lista importada pela secretaria),
-- publicações encontradas no Diário Oficial da Cidade e o registro de cada
-- verificação diária (pra diagnóstico).
CREATE TABLE IF NOT EXISTS servidores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rf TEXT NOT NULL,
    vinculo TEXT NOT NULL DEFAULT '1',
    nome TEXT NOT NULL,
    cargo TEXT,
    funcao TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(rf, vinculo)
);

CREATE TABLE IF NOT EXISTS diario_publicacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    servidor_id INTEGER NOT NULL REFERENCES servidores(id) ON DELETE CASCADE,
    data_publicacao TEXT NOT NULL,
    titulo TEXT,
    trecho TEXT,
    url TEXT,
    encontrado_por TEXT,
    chave TEXT NOT NULL UNIQUE,
    visto INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_diario_pub_visto ON diario_publicacoes(visto);

CREATE TABLE IF NOT EXISTS diario_verificacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_referencia TEXT NOT NULL,
    status TEXT NOT NULL,
    mensagem TEXT,
    detalhes TEXT,
    encontrados INTEGER NOT NULL DEFAULT 0,
    automatica INTEGER NOT NULL DEFAULT 1,
    iniciado_em TEXT NOT NULL,
    concluido_em TEXT
);

-- Recomendações do conselho de classe, uma por aluno e bimestre (editadas
-- na aba Boletim & Frequência; aparecem ao responsável no bimestre).
CREATE TABLE IF NOT EXISTS recomendacoes_bimestre (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    ano INTEGER NOT NULL,
    bimestre INTEGER NOT NULL,
    texto TEXT NOT NULL,
    atualizado_por TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(student_id, ano, bimestre)
);
"""


# ---------------------------------------------------------------- MySQL ----
SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(80) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nome VARCHAR(150) NOT NULL,
    setor VARCHAR(100),
    papel VARCHAR(20) NOT NULL CHECK (papel IN ('admin','professor','aee','secretaria','direcao','pot')),
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    rg VARCHAR(30),
    nome_completo_declaracao VARCHAR(150),
    email VARCHAR(150),
    trocar_senha TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS password_reset_codes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    codigo_hash VARCHAR(255) NOT NULL,
    expira_em DATETIME NOT NULL,
    tentativas INT NOT NULL DEFAULT 0,
    usado TINYINT(1) NOT NULL DEFAULT 0,
    ip VARCHAR(45),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo_interno VARCHAR(50) UNIQUE,
    nis VARCHAR(20),
    bolsa_familia TINYINT(1) NOT NULL DEFAULT 0,
    ra_prodesp VARCHAR(50),
    inep VARCHAR(50),
    nome VARCHAR(150) NOT NULL,
    nome_social VARCHAR(150),
    filiacao1 VARCHAR(150),
    data_nascimento VARCHAR(20),
    turma VARCHAR(20) NOT NULL,
    serie VARCHAR(30),
    situacao VARCHAR(30),
    foto_path VARCHAR(255),
    guardian_token_hash VARCHAR(64),
    guardian_codigo VARCHAR(6) UNIQUE,
    aee TINYINT(1) NOT NULL DEFAULT 0,
    rg VARCHAR(30),
    certidao_nascimento VARCHAR(60),
    municipio_nascimento VARCHAR(150),
    recomendacoes TEXT,
    alteracoes_pendentes TEXT,
    data_transferencia VARCHAR(20),
    estado_nascimento VARCHAR(60),
    nacionalidade VARCHAR(60),
    rg_data_expedicao VARCHAR(20),
    rg_orgao_expedidor VARCHAR(60),
    rg_estado_emissor VARCHAR(2),
    certidao_numero VARCHAR(60),
    certidao_folha VARCHAR(20),
    certidao_livro VARCHAR(20),
    certidao_distrito_municipio VARCHAR(150),
    certidao_uf VARCHAR(2),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS aee_info (
    student_id INT PRIMARY KEY,
    eol VARCHAR(50),
    laudo TEXT,
    observacoes TEXT,
    deficiencia VARCHAR(150),
    turno VARCHAR(30),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS grades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    ano INT NOT NULL,
    bimestre INT NOT NULL,
    disciplina VARCHAR(150) NOT NULL,
    faltas INT,
    compensacoes INT,
    frequencia FLOAT,
    conceito VARCHAR(10),
    situacao_conselho VARCHAR(30),
    origem VARCHAR(30) DEFAULT 'importado',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_nota (student_id, ano, bimestre, disciplina),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS access_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL,
    referencia VARCHAR(150),
    acao VARCHAR(255) NOT NULL,
    ip VARCHAR(45),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS import_lotes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    arquivo VARCHAR(255),
    ano INT NOT NULL,
    bimestre INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','confirmado','descartado')),
    criado_por VARCHAR(150),
    total_alunos INT DEFAULT 0,
    total_nao_localizados INT DEFAULT 0,
    total_gravado INT DEFAULT 0,
    processando TINYINT(1) NOT NULL DEFAULT 0,
    erro_mensagem TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmado_em TIMESTAMP NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS grades_staging (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lote_id INT NOT NULL,
    aluno_key VARCHAR(255) NOT NULL,
    turma_pdf VARCHAR(20),
    nome_pdf VARCHAR(150),
    student_id INT,
    disciplina VARCHAR(150) NOT NULL,
    faltas INT,
    compensacoes INT,
    frequencia FLOAT,
    conceito VARCHAR(10),
    situacao_conselho VARCHAR(30),
    incluir TINYINT(1) NOT NULL DEFAULT 1,
    FOREIGN KEY (lote_id) REFERENCES import_lotes(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES students(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS historico_manual (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    serie VARCHAR(30) NOT NULL,
    disciplina VARCHAR(150) NOT NULL,
    resultado VARCHAR(30),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_historico_manual (student_id, serie, disciplina),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS configuracoes (
    chave VARCHAR(100) PRIMARY KEY,
    valor TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sptrans_turma_codigo (
    turma VARCHAR(20) PRIMARY KEY,
    codigo_curso VARCHAR(30),
    codigo_turma VARCHAR(30),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS turma_turno (
    turma VARCHAR(20) PRIMARY KEY,
    turno VARCHAR(10) NOT NULL CHECK (turno IN ('Manhã','Tarde','Integral')),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sptrans_dados_aluno (
    student_id INT PRIMARY KEY,
    cpf VARCHAR(20),
    rg_numero VARCHAR(20),
    rg_digito VARCHAR(5),
    rg_uf VARCHAR(2),
    cep VARCHAR(12),
    endereco_numero VARCHAR(20),
    endereco_complemento VARCHAR(100),
    telefone VARCHAR(100),
    email VARCHAR(150),
    nome_responsavel VARCHAR(150),
    tipo_gratuidade VARCHAR(5) NOT NULL DEFAULT '0',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS contatos_responsaveis (
    student_id INT PRIMARY KEY,
    telefone_filiacao1 VARCHAR(100),
    telefone_filiacao2 VARCHAR(100),
    responsavel_legal VARCHAR(150),
    telefone_recados VARCHAR(100),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS frequencia_mensal (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    ano INT NOT NULL,
    mes INT NOT NULL,
    faltas INT,
    motivo VARCHAR(255),
    percentual INT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_frequencia (student_id, ano, mes),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS documentos_pendencias (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    documento VARCHAR(30) NOT NULL,
    entregue TINYINT(1) NOT NULL DEFAULT 0,
    entregue_em VARCHAR(30),
    entregue_por VARCHAR(150),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_documento_aluno (student_id, documento),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS documentos_status (
    student_id INT PRIMARY KEY,
    status_original VARCHAR(500),
    importado_em VARCHAR(30),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feriados (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data VARCHAR(10) NOT NULL UNIQUE,
    descricao VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS turmas_projeto (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(40) NOT NULL UNIQUE,
    nome VARCHAR(500) NOT NULL,
    turma VARCHAR(100),
    descricao VARCHAR(500),
    turno VARCHAR(40),
    ano INT,
    unidade VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS turma_projeto_alunos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    turma_projeto_id INT NOT NULL,
    student_id INT,
    codigo_eol VARCHAR(40) NOT NULL,
    numero VARCHAR(10),
    nome VARCHAR(255) NOT NULL,
    situacao VARCHAR(60),
    data_inclusao VARCHAR(20),
    UNIQUE KEY uniq_turma_projeto_aluno (turma_projeto_id, codigo_eol),
    INDEX idx_turma_projeto_alunos_student (student_id),
    FOREIGN KEY (turma_projeto_id) REFERENCES turmas_projeto(id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS arquivos (
    categoria VARCHAR(30) NOT NULL,
    nome VARCHAR(200) NOT NULL,
    conteudo LONGBLOB NOT NULL,
    tipo VARCHAR(100),
    tamanho INT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (categoria, nome)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS whatsapp_modelos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chave VARCHAR(40) UNIQUE,
    titulo VARCHAR(120) NOT NULL,
    texto TEXT NOT NULL,
    atualizado_por VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS motivos_frequencia_escola (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL UNIQUE,
    categoria VARCHAR(255) NOT NULL,
    descricao TEXT NOT NULL,
    criado_por VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS situacoes_coletivas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ano INT NOT NULL,
    mes INT NOT NULL,
    motivo VARCHAR(120) NOT NULL,
    criado_por VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_situacao_coletiva (ano, mes)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chamada_diaria (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    data VARCHAR(10) NOT NULL,
    status VARCHAR(1) NOT NULL,
    justificada TINYINT(1) NOT NULL DEFAULT 0,
    motivo VARCHAR(255),
    registrado_por VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_chamada_diaria (student_id, data),
    KEY idx_chamada_diaria_data (data),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fichas_matricula (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NULL,
    nome VARCHAR(150) NOT NULL,
    turma VARCHAR(20),
    ano INT,
    dados MEDIUMTEXT NOT NULL,
    criado_por VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_fichas_matricula_aluno (student_id),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dias_letivos_mensais (
    ano INT NOT NULL,
    mes INT NOT NULL,
    dias_letivos INT NOT NULL,
    PRIMARY KEY (ano, mes)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS teg_alunos (
    student_id INT PRIMARY KEY,
    turno VARCHAR(30),
    motivo_codigo INT,
    motivo_descricao VARCHAR(255),
    distancia_metros INT,
    cadeirante VARCHAR(5),
    tipo_logradouro VARCHAR(30),
    logradouro VARCHAR(150),
    numero_endereco VARCHAR(20),
    complemento VARCHAR(100),
    bairro VARCHAR(150),
    cep VARCHAR(15),
    placa_veiculo VARCHAR(15),
    nome_condutor VARCHAR(150),
    capacidade_veiculo INT,
    barreira_fisica VARCHAR(255),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS teg_condutores (
    nome_condutor VARCHAR(150) PRIMARY KEY,
    telefone VARCHAR(100),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS arquivo_morto (
    id INT AUTO_INCREMENT PRIMARY KEY,
    letra VARCHAR(2) NOT NULL,
    numero VARCHAR(20),
    nome VARCHAR(150) NOT NULL,
    data_nascimento VARCHAR(20),
    student_id INT,
    origem VARCHAR(15) NOT NULL DEFAULT 'importado' CHECK (origem IN ('importado', 'transferencia', 'manual')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL,
    INDEX idx_arquivo_morto_letra (letra)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cursos_recomendados (
    id INT AUTO_INCREMENT PRIMARY KEY,
    titulo VARCHAR(200) NOT NULL,
    descricao TEXT,
    url VARCHAR(500),
    ciclo VARCHAR(20) NOT NULL CHECK (ciclo IN ('Alfabetização','Interdisciplinar','Autoral')),
    fonte VARCHAR(150),
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS atendimentos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_hora DATETIME NOT NULL,
    student_id INT,
    nome_responsavel VARCHAR(150) NOT NULL,
    telefone_contato VARCHAR(100),
    assunto VARCHAR(255) NOT NULL,
    observacoes TEXT,
    responsavel_atendimento VARCHAR(150),
    status VARCHAR(15) NOT NULL DEFAULT 'agendado' CHECK (status IN ('agendado','realizado','cancelado','faltou')),
    criado_por VARCHAR(150),
    atendido_por VARCHAR(150),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS relatorios_escolares (
    atendimento_id INT PRIMARY KEY,
    nome_aluno VARCHAR(200),
    turma VARCHAR(30),
    numero VARCHAR(10),
    preenchido_por VARCHAR(150),
    recebido_por VARCHAR(150),
    data DATE,
    telefone1 VARCHAR(30),
    telefone2 VARCHAR(30),
    texto MEDIUMTEXT,
    atualizado_por VARCHAR(150),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (atendimento_id) REFERENCES atendimentos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS relatorio_fotos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    atendimento_id INT NOT NULL,
    arquivo VARCHAR(255) NOT NULL,
    legenda VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (atendimento_id) REFERENCES atendimentos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS afastamentos_saude (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE,
    motivo TEXT,
    observacoes TEXT,
    criado_por VARCHAR(150),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS atividades_afastamento (
    id INT AUTO_INCREMENT PRIMARY KEY,
    afastamento_id INT NOT NULL,
    disciplina VARCHAR(150),
    titulo VARCHAR(255) NOT NULL,
    descricao TEXT,
    data_envio DATE NOT NULL,
    enviado_por VARCHAR(150),
    status VARCHAR(15) NOT NULL DEFAULT 'enviada' CHECK (status IN ('enviada','entregue','pendente')),
    data_entrega DATE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (afastamento_id) REFERENCES afastamentos_saude(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS turma_turno (
    turma VARCHAR(20) PRIMARY KEY,
    turno VARCHAR(10) NOT NULL CHECK (turno IN ('Manhã','Tarde','Integral')),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS servidores (
    id INT AUTO_INCREMENT PRIMARY KEY,
    rf VARCHAR(15) NOT NULL,
    vinculo VARCHAR(5) NOT NULL DEFAULT '1',
    nome VARCHAR(200) NOT NULL,
    cargo VARCHAR(200),
    funcao VARCHAR(255),
    ativo TINYINT(1) NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_servidor (rf, vinculo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS diario_publicacoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    servidor_id INT NOT NULL,
    data_publicacao DATE NOT NULL,
    titulo VARCHAR(500),
    trecho TEXT,
    url VARCHAR(1000),
    encontrado_por VARCHAR(20),
    chave VARCHAR(64) NOT NULL UNIQUE,
    visto TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (servidor_id) REFERENCES servidores(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS diario_verificacoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_referencia DATE NOT NULL,
    status VARCHAR(20) NOT NULL,
    mensagem TEXT,
    detalhes MEDIUMTEXT,
    encontrados INT NOT NULL DEFAULT 0,
    automatica TINYINT(1) NOT NULL DEFAULT 1,
    iniciado_em DATETIME NOT NULL,
    concluido_em DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recomendacoes_bimestre (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    ano INT NOT NULL,
    bimestre INT NOT NULL,
    texto TEXT NOT NULL,
    atualizado_por VARCHAR(150),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_recomendacao (student_id, ano, bimestre),
    FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_INDICES_MYSQL = [
    "CREATE INDEX idx_students_turma ON students(turma)",
    "CREATE INDEX idx_grades_student ON grades(student_id)",
    "CREATE INDEX idx_staging_lote ON grades_staging(lote_id)",
    "CREATE INDEX idx_historico_manual_student ON historico_manual(student_id)",
    "CREATE INDEX idx_atendimentos_data ON atendimentos(data_hora)",
    "CREATE INDEX idx_atendimentos_student ON atendimentos(student_id)",
    "CREATE INDEX idx_afastamentos_student ON afastamentos_saude(student_id)",
    "CREATE INDEX idx_atividades_afastamento ON atividades_afastamento(afastamento_id)",
    "CREATE INDEX idx_frequencia_student ON frequencia_mensal(student_id)",
    "CREATE INDEX idx_relatorio_fotos_atendimento ON relatorio_fotos(atendimento_id)",
    "CREATE INDEX idx_diario_pub_visto ON diario_publicacoes(visto)",
]


# --------------------------------------------------------- camada comum ----
class _MySQLRow(dict):
    """Linha do MySQL que se comporta como sqlite3.Row: aceita row["coluna"]
    e row[0], e percorrer a linha (tuple(row)) dá os valores."""

    def __getitem__(self, chave):
        if isinstance(chave, int):
            return list(self.values())[chave]
        return super().__getitem__(chave)

    def __iter__(self):
        return iter(list(self.values()))


def _conversores_mysql():
    """Datas e horas do MySQL voltam como texto ("2026-09-20",
    "2026-11-10 09:00:00"), igual ao SQLite — o resto do código trata data
    como texto."""
    from pymysql.constants import FIELD_TYPE
    from pymysql.converters import conversions
    conv = dict(conversions)
    for tipo in (FIELD_TYPE.DATE, FIELD_TYPE.DATETIME, FIELD_TYPE.TIMESTAMP, FIELD_TYPE.TIME):
        conv[tipo] = str
    return conv


class _MySQLCursor:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        r = self._cur.fetchone()
        return None if r is None else _MySQLRow(r)

    def fetchall(self):
        return [_MySQLRow(r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount


class _MySQLConn:
    """Faz uma conexão pymysql se comportar como uma sqlite3.Connection o
    suficiente para o resto do código não precisar saber qual banco está
    em uso: aceita "?" como placeholder (convertido para "%s") e devolve
    linhas com acesso por chave — igual ao sqlite3.Row."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        # "%" literal (ex: LIKE '%x%' escrito no SQL) vira "%%" para o pymysql
        cur.execute(sql.replace("%", "%%").replace("?", "%s"), tuple(params))
        return _MySQLCursor(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        for stmt in filter(None, (s.strip() for s in sql.split(";"))):
            cur.execute(stmt)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


_SSL_CA_TEMP = None


def _ssl_mysql():
    """Contexto SSL para o MySQL conforme MYSQL_SSL / MYSQL_SSL_CA (None =
    sem SSL). "required" criptografa sem conferir o certificado (como o
    ssl-mode=REQUIRED do cliente mysql); com um CA ou "verify", confere."""
    global _SSL_CA_TEMP
    import ssl
    modo, ca = config.MYSQL_SSL, config.MYSQL_SSL_CA
    if not modo and not ca:
        return None
    if ca.startswith("-----BEGIN"):  # conteúdo do ca.pem colado na variável de ambiente
        if _SSL_CA_TEMP is None:
            import tempfile
            arq = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
            arq.write(ca.replace("\\n", "\n"))
            arq.close()
            _SSL_CA_TEMP = arq.name
        ca = _SSL_CA_TEMP
    if ca or modo == "verify":
        try:
            import certifi
            padrao = certifi.where()
        except ImportError:
            padrao = None
        ctx = ssl.create_default_context(cafile=ca or padrao)
        ctx.check_hostname = modo == "verify" or not ca
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


@contextmanager
def get_db():
    if config.DB_BACKEND == "mysql":
        import pymysql
        import pymysql.cursors

        conn = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE,
            ssl=_ssl_mysql(),
            connect_timeout=15,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            conv=_conversores_mysql(),
            # as consultas foram escritas para o SQLite, que aceita colunas
            # fora do GROUP BY; no MySQL isso exige tirar ONLY_FULL_GROUP_BY
            init_command="SET SESSION sql_mode = REPLACE(@@sql_mode, 'ONLY_FULL_GROUP_BY', ''), time_zone = '+00:00'",
        )
        db = _MySQLConn(conn)
    else:
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        db = conn
    try:
        yield db
        db.commit()
    finally:
        db.close()


def _migrar_import_lotes(db):
    """Bancos criados antes do processamento em segundo plano não têm essas
    colunas — adiciona de forma idempotente, sem mexer no CHECK de status
    (evita ter que recriar a tabela em produção)."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM import_lotes").fetchall()}
        if "processando" not in cols:
            db.execute("ALTER TABLE import_lotes ADD COLUMN processando TINYINT(1) NOT NULL DEFAULT 0")
        if "erro_mensagem" not in cols:
            db.execute("ALTER TABLE import_lotes ADD COLUMN erro_mensagem TEXT")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(import_lotes)")}
        if "processando" not in cols:
            db.execute("ALTER TABLE import_lotes ADD COLUMN processando INTEGER NOT NULL DEFAULT 0")
        if "erro_mensagem" not in cols:
            db.execute("ALTER TABLE import_lotes ADD COLUMN erro_mensagem TEXT")


def _migrar_students_historico(db):
    """Bancos criados antes dos campos de documento/histórico manual (e,
    depois, recomendações/pendências cadastrais/transferência/cabeçalho
    completo do histórico) não têm essas colunas — adiciona de forma
    idempotente."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM students").fetchall()}
        for coluna, tipo in (
            ("rg", "VARCHAR(30)"), ("certidao_nascimento", "VARCHAR(60)"),
            ("municipio_nascimento", "VARCHAR(150)"),
            ("recomendacoes", "TEXT"), ("alteracoes_pendentes", "TEXT"),
            ("data_transferencia", "VARCHAR(20)"),
            ("estado_nascimento", "VARCHAR(60)"), ("nacionalidade", "VARCHAR(60)"),
            ("rg_data_expedicao", "VARCHAR(20)"), ("rg_orgao_expedidor", "VARCHAR(60)"),
            ("rg_estado_emissor", "VARCHAR(2)"), ("certidao_numero", "VARCHAR(60)"),
            ("certidao_folha", "VARCHAR(20)"), ("certidao_livro", "VARCHAR(20)"),
            ("certidao_distrito_municipio", "VARCHAR(150)"), ("certidao_uf", "VARCHAR(2)"),
            ("nome_social", "VARCHAR(150)"),
        ):
            if coluna not in cols:
                db.execute(f"ALTER TABLE students ADD COLUMN {coluna} {tipo}")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(students)")}
        for coluna in (
            "rg", "certidao_nascimento", "municipio_nascimento",
            "recomendacoes", "alteracoes_pendentes",
            "data_transferencia",
            "estado_nascimento", "nacionalidade", "rg_data_expedicao",
            "rg_orgao_expedidor", "rg_estado_emissor", "certidao_numero",
            "certidao_folha", "certidao_livro", "certidao_distrito_municipio",
            "certidao_uf", "nome_social",
        ):
            if coluna not in cols:
                db.execute(f"ALTER TABLE students ADD COLUMN {coluna} TEXT")


def _migrar_atendimentos(db):
    """Bancos criados antes do campo 'responsavel_atendimento' (quem da
    equipe vai conduzir o atendimento) não têm essa coluna."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM atendimentos").fetchall()}
        if "responsavel_atendimento" not in cols:
            db.execute("ALTER TABLE atendimentos ADD COLUMN responsavel_atendimento VARCHAR(150)")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(atendimentos)")}
        if "responsavel_atendimento" not in cols:
            db.execute("ALTER TABLE atendimentos ADD COLUMN responsavel_atendimento TEXT")


def _migrar_students_guardian_codigo(db):
    """Bancos criados antes do código fixo de 6 números do responsável
    (substitui o token longo mostrado uma vez só) não têm a coluna."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM students").fetchall()}
        if "guardian_codigo" not in cols:
            db.execute("ALTER TABLE students ADD COLUMN guardian_codigo VARCHAR(6)")
            db.execute("CREATE UNIQUE INDEX uniq_guardian_codigo ON students(guardian_codigo)")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(students)")}
        if "guardian_codigo" not in cols:
            db.execute("ALTER TABLE students ADD COLUMN guardian_codigo TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_guardian_codigo ON students(guardian_codigo)")


def trocar_todos_codigos_responsavel(db):
    """Dá um código NOVO de 6 números a todos os alunos (sem repetir) e
    desativa todos os tokens longos antigos — nenhum acesso anterior de
    responsável continua valendo. Devolve quantos alunos receberam código."""
    ids = [r["id"] for r in db.execute("SELECT id FROM students ORDER BY id").fetchall()]
    codigos = secrets.SystemRandom().sample(range(10**6), len(ids))
    db.execute("UPDATE students SET guardian_codigo = NULL, guardian_token_hash = NULL")
    for student_id, codigo in zip(ids, codigos):
        db.execute("UPDATE students SET guardian_codigo = ? WHERE id = ?", (f"{codigo:06d}", student_id))
    return len(ids)


def _migrar_troca_geral_codigos_responsavel(db):
    """Uma única vez: troca o acesso de TODOS os responsáveis pelo código de
    6 números (inclusive quem tinha o token longo antigo, que deixa de valer).
    Fica marcado em configuracoes pra não repetir a cada reinício."""
    if get_config(db, "codigos_responsavel_troca_geral"):
        return
    n = trocar_todos_codigos_responsavel(db)
    set_config(db, "codigos_responsavel_troca_geral", f"{agora()} ({n} alunos)")


def _migrar_users_email(db):
    """Bancos criados antes do "Esqueci minha senha" não têm users.email."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM users").fetchall()}
        if "email" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN email VARCHAR(150)")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "email" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN email TEXT")


def _migrar_users_trocar_senha(db):
    """users.trocar_senha: 1 quando o admin gerou uma senha provisória e a
    pessoa ainda não criou a própria (o sistema obriga a troca)."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM users").fetchall()}
        if "trocar_senha" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN trocar_senha TINYINT(1) NOT NULL DEFAULT 0")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "trocar_senha" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN trocar_senha INTEGER NOT NULL DEFAULT 0")


# colunas do MySQL alargadas depois (SQLite não tem limite de tamanho):
# padrão do nome da coluna -> tamanho mínimo
_TAMANHOS_MYSQL = {"telefone%": 100, "acao": 255, "turma": 20, "turma_pdf": 20}


def _migrar_mysql_tamanhos(db):
    """Bancos MySQL criados com colunas curtas demais (telefone com dois
    números, nome de turma de projeto, ação longa no log) são alargados."""
    if config.DB_BACKEND != "mysql":
        return
    for padrao, tamanho in _TAMANHOS_MYSQL.items():
        colunas = db.execute(
            """SELECT TABLE_NAME AS tabela, COLUMN_NAME AS coluna, IS_NULLABLE AS nulo, COLUMN_DEFAULT AS padrao
               FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME LIKE ? AND DATA_TYPE = 'varchar'
                 AND CHARACTER_MAXIMUM_LENGTH < ?""",
            (padrao, tamanho),
        ).fetchall()
        for c in colunas:
            nulo = "NULL" if c["nulo"] == "YES" else "NOT NULL"
            padrao_sql = "" if c["padrao"] is None else " DEFAULT " + db._conn.escape(c["padrao"])
            db.execute(f"ALTER TABLE `{c['tabela']}` MODIFY `{c['coluna']}` VARCHAR({tamanho}) {nulo}{padrao_sql}")


def _migrar_users_papeis(db):
    """Bancos criados antes dos perfis Direção e POT têm um CHECK em
    users.papel que só aceita admin/professor/aee/secretaria.

    SQLite não altera CHECK com ALTER TABLE; como a mudança não mexe no
    formato gravado, troca-se o texto do CREATE TABLE no sqlite_master
    (procedimento descrito na documentação do SQLite, "ALTER TABLE" >
    "other kinds of table schema changes"). No MySQL o CHECK antigo é
    removido e recriado (MySQL < 8.0.16 ignora CHECK: nada a fazer)."""
    antigo = "papel IN ('admin','professor','aee','secretaria')"
    novo = "papel IN ('admin','professor','aee','secretaria','direcao','pot')"
    if config.DB_BACKEND == "mysql":
        try:
            linhas = db.execute(
                """SELECT cc.CONSTRAINT_NAME AS nome FROM information_schema.CHECK_CONSTRAINTS cc
                   JOIN information_schema.TABLE_CONSTRAINTS tc
                     ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME
                   WHERE tc.TABLE_SCHEMA = DATABASE() AND tc.TABLE_NAME = 'users'
                     AND cc.CHECK_CLAUSE LIKE '%papel%' AND cc.CHECK_CLAUSE NOT LIKE '%direcao%'"""
            ).fetchall()
        except Exception:  # MySQL antigo, sem CHECK_CONSTRAINTS: o CHECK não é aplicado
            return
        for r in linhas:
            db.execute(f"ALTER TABLE users DROP CHECK `{r['nome']}`")
            db.execute(f"ALTER TABLE users ADD CONSTRAINT `{r['nome']}` CHECK ({novo})")
        return
    linha = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()
    if not linha or antigo not in linha["sql"]:
        return
    versao = db.execute("PRAGMA schema_version").fetchone()[0]
    db.execute("PRAGMA writable_schema = ON")
    db.execute("UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = 'users'",
               (linha["sql"].replace(antigo, novo),))
    db.execute(f"PRAGMA schema_version = {versao + 1}")
    db.execute("PRAGMA writable_schema = OFF")
    db.commit()
    resultado = db.execute("PRAGMA integrity_check").fetchone()[0]
    if resultado != "ok":
        raise RuntimeError(f"Migração dos perfis de usuário: integrity_check = {resultado}")


def _migrar_frequencia_percentual(db):
    """Bancos criados antes da importação de ciclos anteriores não têm a
    coluna 'percentual' (a % oficial trazida pela planilha importada)."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM frequencia_mensal").fetchall()}
        if "percentual" not in cols:
            db.execute("ALTER TABLE frequencia_mensal ADD COLUMN percentual INT")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(frequencia_mensal)")}
        if "percentual" not in cols:
            db.execute("ALTER TABLE frequencia_mensal ADD COLUMN percentual INTEGER")


def _migrar_students_bolsa_familia(db):
    """Bancos criados antes da aba Bolsa Família não têm 'nis'/'bolsa_familia'
    em students — adiciona de forma idempotente."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM students").fetchall()}
        if "nis" not in cols:
            db.execute("ALTER TABLE students ADD COLUMN nis VARCHAR(20)")
        if "bolsa_familia" not in cols:
            db.execute("ALTER TABLE students ADD COLUMN bolsa_familia TINYINT(1) NOT NULL DEFAULT 0")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(students)")}
        if "nis" not in cols:
            db.execute("ALTER TABLE students ADD COLUMN nis TEXT")
        if "bolsa_familia" not in cols:
            db.execute("ALTER TABLE students ADD COLUMN bolsa_familia INTEGER NOT NULL DEFAULT 0")


def _migrar_users_declaracao(db):
    """Bancos criados antes da aba Declaração de Matrícula não têm 'rg'/
    'nome_completo_declaracao' em users — adiciona de forma idempotente."""
    if config.DB_BACKEND == "mysql":
        cols = {r["Field"] for r in db.execute("SHOW COLUMNS FROM users").fetchall()}
        if "rg" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN rg VARCHAR(30)")
        if "nome_completo_declaracao" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN nome_completo_declaracao VARCHAR(150)")
    else:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "rg" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN rg TEXT")
        if "nome_completo_declaracao" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN nome_completo_declaracao TEXT")


def _migrar_arquivo_morto_manual(db):
    """Bancos criados antes da inserção manual no Arquivo Morto têm o
    CHECK de 'origem' sem 'manual'. MySQL aceita ALTER de CHECK
    diretamente; SQLite não permite alterar CHECK via ALTER TABLE, então
    a tabela precisa ser recriada preservando os dados (idempotente: só
    mexe se o CHECK salvo ainda não incluir 'manual')."""
    if config.DB_BACKEND == "mysql":
        try:
            db.execute("ALTER TABLE arquivo_morto DROP CHECK arquivo_morto_chk_1")
        except Exception:
            pass
        try:
            db.execute(
                "ALTER TABLE arquivo_morto ADD CONSTRAINT arquivo_morto_origem_chk "
                "CHECK (origem IN ('importado', 'transferencia', 'manual'))"
            )
        except Exception:
            pass
        return

    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='arquivo_morto'"
    ).fetchone()
    if not row or not row["sql"] or "'manual'" in row["sql"]:
        return
    db.execute("ALTER TABLE arquivo_morto RENAME TO arquivo_morto_old")
    db.execute("""
        CREATE TABLE arquivo_morto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            letra TEXT NOT NULL,
            numero TEXT,
            nome TEXT NOT NULL,
            data_nascimento TEXT,
            student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
            origem TEXT NOT NULL DEFAULT 'importado' CHECK (origem IN ('importado', 'transferencia', 'manual')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute(
        """INSERT INTO arquivo_morto (id, letra, numero, nome, data_nascimento, student_id, origem, created_at)
           SELECT id, letra, numero, nome, data_nascimento, student_id, origem, created_at FROM arquivo_morto_old"""
    )
    db.execute("DROP TABLE arquivo_morto_old")
    db.execute("CREATE INDEX IF NOT EXISTS idx_arquivo_morto_letra ON arquivo_morto(letra)")


def init_db():
    with get_db() as db:
        if config.DB_BACKEND == "mysql":
            db.executescript(SCHEMA_MYSQL)
            for sql in _INDICES_MYSQL:
                try:
                    db.execute(sql)
                except Exception as e:  # índice já existe em execuções anteriores
                    if "1061" not in str(e) and "Duplicate" not in str(e):
                        raise
        else:
            db.executescript(SCHEMA_SQLITE)
        _migrar_import_lotes(db)
        _migrar_students_historico(db)
        _migrar_atendimentos(db)
        _migrar_students_bolsa_familia(db)
        _migrar_frequencia_percentual(db)
        _migrar_users_email(db)
        _migrar_users_trocar_senha(db)
        _migrar_users_papeis(db)
        _migrar_mysql_tamanhos(db)
        _migrar_students_guardian_codigo(db)
        _migrar_troca_geral_codigos_responsavel(db)
        _migrar_users_declaracao(db)
        _migrar_arquivo_morto_manual(db)
        sincronizar_arquivo_morto(db)


# ------------------------------------------------------- upserts portáveis
# MySQL e SQLite têm sintaxes diferentes de "insere ou atualiza"
# (ON DUPLICATE KEY UPDATE vs. ON CONFLICT ... DO UPDATE). Em vez de manter
# duas versões de cada query, fazemos o padrão check-then-write em Python,
# que funciona igual nos dois bancos.
def salvar_aee_info(db, student_id, eol, laudo, observacoes, deficiencia, turno):
    existente = db.execute(
        "SELECT student_id FROM aee_info WHERE student_id = ?", (student_id,)
    ).fetchone()
    if existente:
        db.execute(
            """UPDATE aee_info SET eol=?, laudo=?, observacoes=?, deficiencia=?, turno=?, updated_at=?
               WHERE student_id=?""",
            (eol, laudo, observacoes, deficiencia, turno, agora(), student_id),
        )
    else:
        db.execute(
            """INSERT INTO aee_info (student_id, eol, laudo, observacoes, deficiencia, turno, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (student_id, eol, laudo, observacoes, deficiencia, turno, agora()),
        )


def salvar_nota(db, student_id, ano, bimestre, disciplina, faltas, compensacoes,
                 frequencia, conceito, situacao_conselho, origem):
    existente = db.execute(
        "SELECT id FROM grades WHERE student_id=? AND ano=? AND bimestre=? AND disciplina=?",
        (student_id, ano, bimestre, disciplina),
    ).fetchone()
    if existente:
        db.execute(
            """UPDATE grades SET faltas=?, compensacoes=?, frequencia=?, conceito=?,
                 situacao_conselho=?, origem=?, updated_at=? WHERE id=?""",
            (faltas, compensacoes, frequencia, conceito, situacao_conselho, origem,
             agora(), existente["id"]),
        )
    else:
        db.execute(
            """INSERT INTO grades (student_id, ano, bimestre, disciplina, faltas, compensacoes,
                 frequencia, conceito, situacao_conselho, origem, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (student_id, ano, bimestre, disciplina, faltas, compensacoes, frequencia,
             conceito, situacao_conselho, origem, agora()),
        )


def salvar_frequencia_mensal(db, student_id, ano, mes, faltas, motivo, percentual=None):
    """'percentual' é a % oficial vinda de planilha importada. Lançamento
    manual (sem percentual) apaga a % importada, e a tela volta a calcular
    a partir das faltas + dias letivos."""
    existente = db.execute(
        "SELECT id FROM frequencia_mensal WHERE student_id=? AND ano=? AND mes=?",
        (student_id, ano, mes),
    ).fetchone()
    if existente:
        db.execute(
            "UPDATE frequencia_mensal SET faltas=?, motivo=?, percentual=?, updated_at=? WHERE id=?",
            (faltas, motivo, percentual, agora(), existente["id"]),
        )
    else:
        db.execute(
            """INSERT INTO frequencia_mensal (student_id, ano, mes, faltas, motivo, percentual, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (student_id, ano, mes, faltas, motivo, percentual, agora()),
        )


def salvar_dias_letivos(db, ano, mes, dias_letivos):
    existente = db.execute(
        "SELECT ano FROM dias_letivos_mensais WHERE ano=? AND mes=?", (ano, mes)
    ).fetchone()
    if existente:
        db.execute(
            "UPDATE dias_letivos_mensais SET dias_letivos=? WHERE ano=? AND mes=?",
            (dias_letivos, ano, mes),
        )
    else:
        db.execute(
            "INSERT INTO dias_letivos_mensais (ano, mes, dias_letivos) VALUES (?,?,?)",
            (ano, mes, dias_letivos),
        )


def get_config(db, chave, padrao=None):
    row = db.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    return row["valor"] if row and row["valor"] is not None else padrao


def set_config(db, chave, valor):
    existente = db.execute("SELECT chave FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    if existente:
        db.execute("UPDATE configuracoes SET valor=?, updated_at=? WHERE chave=?", (valor, agora(), chave))
    else:
        db.execute("INSERT INTO configuracoes (chave, valor, updated_at) VALUES (?,?,?)", (chave, valor, agora()))


def salvar_sptrans_turma_codigo(db, turma, codigo_curso, codigo_turma):
    existente = db.execute("SELECT turma FROM sptrans_turma_codigo WHERE turma = ?", (turma,)).fetchone()
    if existente:
        db.execute(
            "UPDATE sptrans_turma_codigo SET codigo_curso=?, codigo_turma=?, updated_at=? WHERE turma=?",
            (codigo_curso, codigo_turma, agora(), turma),
        )
    else:
        db.execute(
            "INSERT INTO sptrans_turma_codigo (turma, codigo_curso, codigo_turma, updated_at) VALUES (?,?,?,?)",
            (turma, codigo_curso, codigo_turma, agora()),
        )


def salvar_turma_turno(db, turma, turno):
    """turno=None apaga a configuração (turma volta a ficar sem turno
    definido, em vez de gravar um valor inválido)."""
    if not turno:
        db.execute("DELETE FROM turma_turno WHERE turma = ?", (turma,))
        return
    existente = db.execute("SELECT turma FROM turma_turno WHERE turma = ?", (turma,)).fetchone()
    if existente:
        db.execute("UPDATE turma_turno SET turno=?, updated_at=? WHERE turma=?", (turno, agora(), turma))
    else:
        db.execute(
            "INSERT INTO turma_turno (turma, turno, updated_at) VALUES (?,?,?)", (turma, turno, agora())
        )


def salvar_turma_turno(db, turma, turno):
    """turno: 'Manhã', 'Tarde' ou 'Integral'; passe None pra apagar a
    configuração (turma volta a aparecer em 'Sem turno definido')."""
    existente = db.execute("SELECT turma FROM turma_turno WHERE turma = ?", (turma,)).fetchone()
    if not turno:
        if existente:
            db.execute("DELETE FROM turma_turno WHERE turma = ?", (turma,))
        return
    if existente:
        db.execute("UPDATE turma_turno SET turno=?, updated_at=? WHERE turma=?", (turno, agora(), turma))
    else:
        db.execute(
            "INSERT INTO turma_turno (turma, turno, updated_at) VALUES (?,?,?)", (turma, turno, agora())
        )


def salvar_sptrans_dados_aluno(db, student_id, **campos):
    """campos aceitos: cpf, rg_numero, rg_digito, rg_uf, cep, endereco_numero,
    endereco_complemento, telefone, email, nome_responsavel, tipo_gratuidade"""
    existente = db.execute(
        "SELECT student_id FROM sptrans_dados_aluno WHERE student_id = ?", (student_id,)
    ).fetchone()
    colunas = [
        "cpf", "rg_numero", "rg_digito", "rg_uf", "cep", "endereco_numero",
        "endereco_complemento", "telefone", "email", "nome_responsavel", "tipo_gratuidade",
    ]
    valores = [campos.get(c) for c in colunas]
    if valores[colunas.index("tipo_gratuidade")] is None:
        valores[colunas.index("tipo_gratuidade")] = "0"
    if existente:
        db.execute(
            f"""UPDATE sptrans_dados_aluno SET {', '.join(f'{c}=?' for c in colunas)}, updated_at=?
                WHERE student_id=?""",
            valores + [agora(), student_id],
        )
    else:
        db.execute(
            f"""INSERT INTO sptrans_dados_aluno (student_id, {', '.join(colunas)}, updated_at)
                VALUES (?, {', '.join(['?'] * len(colunas))}, ?)""",
            [student_id] + valores + [agora()],
        )


def salvar_contato_responsavel(db, student_id, **campos):
    """campos aceitos: telefone_filiacao1, telefone_filiacao2, responsavel_legal,
    telefone_recados"""
    existente = db.execute(
        "SELECT student_id FROM contatos_responsaveis WHERE student_id = ?", (student_id,)
    ).fetchone()
    colunas = ["telefone_filiacao1", "telefone_filiacao2", "responsavel_legal", "telefone_recados"]
    valores = [campos.get(c) for c in colunas]
    if existente:
        db.execute(
            f"""UPDATE contatos_responsaveis SET {', '.join(f'{c}=?' for c in colunas)}, updated_at=?
                WHERE student_id=?""",
            valores + [agora(), student_id],
        )
    else:
        db.execute(
            f"""INSERT INTO contatos_responsaveis (student_id, {', '.join(colunas)}, updated_at)
                VALUES (?, {', '.join(['?'] * len(colunas))}, ?)""",
            [student_id] + valores + [agora()],
        )


TEG_COLUNAS = [
    "turno", "motivo_codigo", "motivo_descricao", "distancia_metros", "cadeirante",
    "tipo_logradouro", "logradouro", "numero_endereco", "complemento", "bairro", "cep",
    "placa_veiculo", "nome_condutor", "capacidade_veiculo", "barreira_fisica",
]


def salvar_teg_aluno(db, student_id, **campos):
    """campos aceitos: ver TEG_COLUNAS."""
    existente = db.execute(
        "SELECT student_id FROM teg_alunos WHERE student_id = ?", (student_id,)
    ).fetchone()
    valores = [campos.get(c) for c in TEG_COLUNAS]
    if existente:
        db.execute(
            f"""UPDATE teg_alunos SET {', '.join(f'{c}=?' for c in TEG_COLUNAS)}, updated_at=?
                WHERE student_id=?""",
            valores + [agora(), student_id],
        )
    else:
        db.execute(
            f"""INSERT INTO teg_alunos (student_id, {', '.join(TEG_COLUNAS)}, updated_at)
                VALUES (?, {', '.join(['?'] * len(TEG_COLUNAS))}, ?)""",
            [student_id] + valores + [agora()],
        )


def salvar_teg_condutor_telefone(db, nome_condutor, telefone):
    existente = db.execute(
        "SELECT nome_condutor FROM teg_condutores WHERE nome_condutor = ?", (nome_condutor,)
    ).fetchone()
    if existente:
        db.execute(
            "UPDATE teg_condutores SET telefone=?, updated_at=? WHERE nome_condutor=?",
            (telefone, agora(), nome_condutor),
        )
    else:
        db.execute(
            "INSERT INTO teg_condutores (nome_condutor, telefone, updated_at) VALUES (?,?,?)",
            (nome_condutor, telefone, agora()),
        )


def _arquivo_morto_duplicado(db, letra, nome, data_nascimento):
    """Considera duplicado um registro já existente na mesma letra com o
    mesmo nome (sem diferenciar maiúscula/espaço) — e, quando alguma das
    duas datas de nascimento existir, só se elas também baterem (nome
    igual com nascimento diferente pode ser gente diferente; nome igual
    sem nascimento nos dois lados é tratado como o mesmo registro)."""
    nome_norm = nome.strip().upper()
    candidatos = db.execute(
        "SELECT data_nascimento FROM arquivo_morto WHERE letra = ? AND UPPER(TRIM(nome)) = ?",
        (letra, nome_norm),
    ).fetchall()
    for c in candidatos:
        if not c["data_nascimento"] or not data_nascimento or c["data_nascimento"] == data_nascimento:
            return True
    return False


def _proximo_numero_arquivo_morto(db, letra):
    numeros = db.execute("SELECT numero FROM arquivo_morto WHERE letra = ?", (letra,)).fetchall()
    maior_numero = 0
    for linha in numeros:
        try:
            maior_numero = max(maior_numero, int(linha["numero"]))
        except (TypeError, ValueError):
            continue
    return maior_numero + 1 if numeros else 1


def _numero_liberado(db, letra):
    """Registro da letra que foi liberado (ficou em branco, ex: aluno
    duplicado) e ainda espera o próximo aluno — o de menor número, se
    houver mais de um."""
    vagos = db.execute(
        "SELECT id, numero FROM arquivo_morto WHERE letra = ? AND TRIM(nome) = ''", (letra,)
    ).fetchall()

    def ordem(r):
        try:
            return (0, int(r["numero"]))
        except (TypeError, ValueError):
            return (1, 0)

    return min(vagos, key=ordem) if vagos else None


def _gravar_no_arquivo_morto(db, letra, nome, data_nascimento, student_id, origem):
    """Ocupa um número liberado da letra, se houver; senão, entra no fim."""
    vago = _numero_liberado(db, letra)
    if vago:
        db.execute(
            """UPDATE arquivo_morto SET nome = ?, data_nascimento = ?, student_id = ?, origem = ?, created_at = ?
               WHERE id = ?""",
            (nome, data_nascimento, student_id, origem, agora(), vago["id"]),
        )
        return
    db.execute(
        """INSERT INTO arquivo_morto (letra, numero, nome, data_nascimento, student_id, origem)
           VALUES (?,?,?,?,?,?)""",
        (letra, str(_proximo_numero_arquivo_morto(db, letra)), nome, data_nascimento, student_id, origem),
    )


def liberar_numero_arquivo_morto(db, registro_id):
    """Deixa o registro em branco (ex: aluno cadastrado em duplicidade),
    mantendo letra e número: o próximo aluno que entrar nessa letra ocupa
    esse número em vez de ir para o fim. Devolve o registro como era, ou
    None se não existir / já estiver liberado."""
    registro = db.execute("SELECT * FROM arquivo_morto WHERE id = ?", (registro_id,)).fetchone()
    if not registro or not (registro["nome"] or "").strip():
        return None
    db.execute(
        "UPDATE arquivo_morto SET nome = '', data_nascimento = NULL, student_id = NULL WHERE id = ?",
        (registro_id,),
    )
    return registro


def adicionar_ao_arquivo_morto(db, student_id, nome, data_nascimento):
    """Chamada quando um aluno é marcado como transferido — entra no
    arquivo morto automaticamente, no fim da letra correspondente (a
    letra vem da primeira letra do nome, igual à organização em abas
    do arquivo em planilha original). Devolve False sem inserir nada se
    esse aluno já constar no arquivo morto (ex: foi reativado e
    transferido de novo) — quem chama decide como avisar disso."""
    nome = (nome or "").strip()
    if not nome:
        return True
    letra = nome[0].upper()
    if _arquivo_morto_duplicado(db, letra, nome, data_nascimento):
        return False

    _gravar_no_arquivo_morto(db, letra, nome, data_nascimento, student_id, "transferencia")
    return True




def feriados_do_ano(db, ano):
    """{date: descricao} dos feriados cadastrados no ano."""
    from datetime import date as _date
    linhas = db.execute(
        "SELECT data, descricao FROM feriados WHERE data LIKE ? ORDER BY data", (f"{ano}-%",)
    ).fetchall()
    resultado = {}
    for l in linhas:
        try:
            resultado[_date.fromisoformat(l["data"])] = l["descricao"] or ""
        except ValueError:
            continue
    return resultado


def sincronizar_arquivo_morto(db):
    """Acerta nome e nascimento de todos os registros do Arquivo Morto
    ligados a um aluno do sistema (os que entraram por transferência)
    pelos dados atuais do cadastro. A letra e o número não mudam: são a
    posição física da pasta no arquivo. Roda em toda inicialização, o que
    corrige registros que ficaram desatualizados antes da propagação
    automática existir."""
    db.execute(
        """UPDATE arquivo_morto SET
               nome = (SELECT s.nome FROM students s WHERE s.id = arquivo_morto.student_id),
               data_nascimento = COALESCE(
                   (SELECT s.data_nascimento FROM students s WHERE s.id = arquivo_morto.student_id),
                   data_nascimento)
           WHERE student_id IS NOT NULL
             AND EXISTS (SELECT 1 FROM students s WHERE s.id = arquivo_morto.student_id
                         AND s.nome IS NOT NULL AND TRIM(s.nome) <> '')"""
    )


def propagar_dados_aluno(db, student_id, antes=None):
    """Depois de mudar nome, nome social, turma ou nascimento no cadastro
    do aluno, leva a mudança para os lugares que guardam uma cópia desses
    dados em vez de ler do cadastro:

    - Arquivo Morto: nome e nascimento (a letra e o número da pasta ficam
      como estão);
    - Relatório escolar (Agenda de atendimento): nome e turma do aluno,
      mas só onde ainda está o valor antigo, sem apagar uma correção
      digitada à mão no próprio relatório.

    "antes" é a linha do aluno lida antes da alteração, com nome,
    nome_social e turma. Sem ela, só o Arquivo Morto é atualizado.
    As outras telas (turmas, Bolsa Família, TEG, SPTrans, carteirinhas,
    telefones, agenda...) já leem direto do cadastro."""
    aluno = db.execute(
        "SELECT id, nome, nome_social, turma, data_nascimento FROM students WHERE id = ?", (student_id,)
    ).fetchone()
    if not aluno:
        return
    if (aluno["nome"] or "").strip():
        db.execute(
            "UPDATE arquivo_morto SET nome = ?, data_nascimento = COALESCE(?, data_nascimento) WHERE student_id = ?",
            (aluno["nome"], aluno["data_nascimento"], student_id),
        )
    if antes is None:
        return
    nome_novo = aluno["nome_social"] or aluno["nome"] or ""
    nomes_antigos = {n for n in (antes["nome_social"], antes["nome"]) if n} - {nome_novo}
    atendimentos = "SELECT id FROM atendimentos WHERE student_id = ?"
    for antigo in nomes_antigos:
        db.execute(
            f"""UPDATE relatorios_escolares SET nome_aluno = ?
                WHERE atendimento_id IN ({atendimentos}) AND UPPER(TRIM(nome_aluno)) = UPPER(TRIM(?))""",
            (nome_novo, student_id, antigo),
        )
    if antes["turma"] and aluno["turma"] and antes["turma"] != aluno["turma"]:
        db.execute(
            f"""UPDATE relatorios_escolares SET turma = ?
                WHERE atendimento_id IN ({atendimentos}) AND TRIM(turma) = ?""",
            (aluno["turma"], student_id, antes["turma"]),
        )


def inserir_arquivo_morto_manual(db, nome, data_nascimento):
    """Inserção manual pela tela "Novo registro" do Arquivo Morto — mesma
    checagem de duplicidade de adicionar_ao_arquivo_morto. Devolve False
    sem inserir se já existir um registro equivalente."""
    nome = (nome or "").strip()
    if not nome:
        return False
    letra = nome[0].upper()
    if _arquivo_morto_duplicado(db, letra, nome, data_nascimento):
        return False

    _gravar_no_arquivo_morto(db, letra, nome, data_nascimento, None, "manual")
    return True


def salvar_recomendacao_bimestre(db, student_id, ano, bimestre, texto, autor):
    """Grava (ou apaga, se texto vazio) a recomendação do conselho de classe
    do aluno naquele bimestre."""
    existente = db.execute(
        "SELECT id FROM recomendacoes_bimestre WHERE student_id=? AND ano=? AND bimestre=?",
        (student_id, ano, bimestre),
    ).fetchone()
    if not texto:
        if existente:
            db.execute("DELETE FROM recomendacoes_bimestre WHERE id=?", (existente["id"],))
        return
    if existente:
        db.execute(
            "UPDATE recomendacoes_bimestre SET texto=?, atualizado_por=?, updated_at=? WHERE id=?",
            (texto, autor, agora(), existente["id"]),
        )
    else:
        db.execute(
            """INSERT INTO recomendacoes_bimestre (student_id, ano, bimestre, texto, atualizado_por, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (student_id, ano, bimestre, texto, autor, agora()),
        )


def recomendacoes_por_bimestre(db, student_id):
    """{(ano, bimestre): linha} — pra montar o boletim."""
    return {
        (r["ano"], r["bimestre"]): r
        for r in db.execute(
            "SELECT * FROM recomendacoes_bimestre WHERE student_id = ?", (student_id,)
        ).fetchall()
    }
