-- Tabela de "preparação" da conversão: guarda tudo o que o processamento gerou.
-- Depois, um script de carga leva esses dados para as tabelas do sistema novo.

CREATE SCHEMA IF NOT EXISTS conversao;

CREATE TABLE IF NOT EXISTS conversao.documento (
    id                 bigserial PRIMARY KEY,
    arquivo_origem     text NOT NULL UNIQUE,      -- ex.: 0000-0999/000123.tif
    numero             bigint,                    -- número tirado do nome do arquivo
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
CREATE INDEX IF NOT EXISTS documento_status_idx ON conversao.documento (status);
CREATE INDEX IF NOT EXISTS documento_campos_idx ON conversao.documento USING gin (campos);
-- Busca por palavras no texto (português): WHERE to_tsvector('portuguese', texto_ocr) @@ plainto_tsquery('portuguese', 'maria oliveira')
CREATE INDEX IF NOT EXISTS documento_texto_idx
    ON conversao.documento USING gin (to_tsvector('portuguese', coalesce(texto_ocr, '')));
