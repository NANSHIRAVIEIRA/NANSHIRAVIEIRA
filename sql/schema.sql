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

-- Conferência de série: aponta documentos que parecem estar na pasta errada (2003 x 2004).
-- A faixa da numeração antiga é calculada a partir do que foi colocado nas pastas 2003.
-- São ALERTAS para conferência humana, não erros: um documento pode ter averbação
-- posterior ou o OCR pode ter lido uma data errada.
CREATE OR REPLACE VIEW conversao.conferencia_series AS
WITH faixa_2003 AS (
    SELECT especialidade, min(numero) AS de, max(numero) AS ate
    FROM conversao.documento WHERE serie = 2003 GROUP BY especialidade
), anos AS (
    SELECT d.id, min(left(x, 4)::int) AS menor_ano, max(left(x, 4)::int) AS maior_ano
    FROM conversao.documento d, jsonb_array_elements_text(d.campos -> 'datas') x
    GROUP BY d.id
), base AS (
    SELECT d.codigo, d.arquivo_origem, d.especialidade, d.serie, d.numero,
           a.menor_ano, a.maior_ano, f.de AS faixa_2003_de, f.ate AS faixa_2003_ate,
           CASE
             WHEN d.serie = 2003 AND a.menor_ano >= 2004
               THEN 'pasta 2003, mas só tem datas de 2004 em diante'
             WHEN d.serie = 2004 AND d.especialidade = 'PJ' AND d.numero BETWEEN f.de AND f.ate
               THEN 'PJ na pasta 2004 com número da faixa de 2003 (o PJ ainda não chegou nessa numeração)'
             WHEN d.serie = 2004 AND d.numero BETWEEN f.de AND f.ate AND a.maior_ano <= 2003
               THEN 'pasta 2004, número na faixa de 2003 e só datas até 2003'
             WHEN d.serie = 2004 AND a.maior_ano <= 2003
               THEN 'pasta 2004, mas só tem datas até 2003'
           END AS alerta
    FROM conversao.documento d
    LEFT JOIN faixa_2003 f USING (especialidade)
    LEFT JOIN anos a ON a.id = d.id
)
SELECT * FROM base WHERE alerta IS NOT NULL;
