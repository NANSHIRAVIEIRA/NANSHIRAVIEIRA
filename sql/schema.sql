-- Tabela de "preparação" da conversão: guarda tudo o que o processamento gerou.
-- Depois, um script de carga leva esses dados para as tabelas do sistema novo.

CREATE SCHEMA IF NOT EXISTS conversao;

CREATE TABLE IF NOT EXISTS conversao.documento (
    id                 bigserial PRIMARY KEY,
    arquivo_origem     text NOT NULL UNIQUE,      -- ex.: 0000-0999/000123.tif
    especialidade      text,                      -- TD | PJ
    serie              integer,                   -- ano em que a numeração começou (2003, 2004...)
    numero             bigint,                    -- número tirado do nome do arquivo
    codigo             text,                      -- ex.: TD-2004-0000500
    codigo_numerico    bigint,                    -- ex.: 20040000500 (série × 10^7 + número)
    pasta              text,                      -- ex.: 0000-0999
    status             text,                      -- ok | revisar | erro | todas_paginas_removidas
    paginas_originais  integer,
    paginas_removidas  integer[],
    paginas_duvida     integer[],
    caminho_pdf        text,                      -- relativo à pasta de saída
    caminho_ocr        text,
    texto_ocr          text,
    tipo_provavel      text,                      -- extração automática (sem IA)
    campos             jsonb,                     -- CPFs, CNPJs, datas, livro, folha, matrícula, valores...
    resumo_ia          jsonb,                     -- resumo da IA local (se rodou)
    erro               text,
    processado_em      timestamptz,
    importado_em       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documento_numero_idx ON conversao.documento (numero);
CREATE INDEX IF NOT EXISTS documento_ident_idx ON conversao.documento (especialidade, serie, numero);
CREATE INDEX IF NOT EXISTS documento_status_idx ON conversao.documento (status);
CREATE INDEX IF NOT EXISTS documento_campos_idx ON conversao.documento USING gin (campos);
-- Busca por palavras no texto (português): WHERE to_tsvector('portuguese', texto_ocr) @@ plainto_tsquery('portuguese', 'maria oliveira')
CREATE INDEX IF NOT EXISTS documento_texto_idx
    ON conversao.documento USING gin (to_tsvector('portuguese', coalesce(texto_ocr, '')));

-- Mesmo especialidade+série+número em mais de um arquivo (precisa de decisão manual)
CREATE OR REPLACE VIEW conversao.duplicados AS
SELECT especialidade, serie, numero, count(*) AS arquivos,
       array_agg(arquivo_origem ORDER BY arquivo_origem) AS lista
FROM conversao.documento
WHERE numero IS NOT NULL
GROUP BY especialidade, serie, numero
HAVING count(*) > 1;

-- Documentos sem especialidade ou série (pasta fora do padrão TD/2004/...)
CREATE OR REPLACE VIEW conversao.sem_identificacao AS
SELECT arquivo_origem, especialidade, serie, numero
FROM conversao.documento
WHERE especialidade IS NULL OR serie IS NULL OR numero IS NULL;
