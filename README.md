# Conversão do acervo do cartório

Converte as imagens digitalizadas (TIFF/PDF) para o sistema novo, **100% local** (LGPD):

1. **OCR** em português (Tesseract).
2. **Remove as páginas de flash** da microfilmagem, além das páginas pretas e em branco.
3. Gera **PDF limpo e pesquisável**.
4. **Extrai campos** sem IA: CPF/CNPJ (validados), datas, livro, folha, matrícula, protocolo, valores, tipo do ato.
5. **Resumo em texto** opcional com IA rodando no próprio servidor (Ollama).
6. **Importa tudo no PostgreSQL** (`conversao.documento`) com busca por texto.
7. **Inventário** dos números com e sem imagem em cada milhar.

Montagem do servidor passo a passo: **[docs/servidor.md](docs/servidor.md)**.

## Identificação dos documentos

A numeração foi zerada em 2004 e TD/PJ têm numerações próprias, então o número sozinho
não identifica o documento. A chave é **especialidade + série + número**, lida das pastas:

```
entrada/TD/2003/0000-0999/000500.tif  ->  TD-2003-0000500  (codigo_numerico 20030000500)
entrada/TD/2004/0000-0999/000500.tif  ->  TD-2004-0000500  (codigo_numerico 20040000500)
```

`codigo_numerico` = série × 10.000.000 + número (até 9.999.999 por série; exige BIGINT).
Detalhes em `identificacao.py`.

A view `conversao.conferencia_series` aponta documentos que parecem estar na pasta de série
errada (ex.: na pasta 2003 mas só com datas de 2004 em diante). São alertas para conferência.

## Arquivos

| Arquivo | Etapa |
|---|---|
| `rodar_lote.sh` | Roda todas as etapas abaixo em segundo plano (`iniciar` / `status` / `parar`) |
| `inventario.py` | Lista números com/sem imagem por milhar |
| `processar_acervo.py` | OCR, remoção de flash, PDF, extração de campos |
| `criar_pastas.sh` | Cria entrada/TD/2003, TD/2004, PJ/2003, PJ/2004 |
| `identificacao.py` | Especialidade/série/número a partir das pastas |
| `extracao.py` | Regras de extração de campos (usado pelo anterior) |
| `resumir_local.py` | Resumo por IA local (Ollama) — etapa separada, retomável |
| `importar_postgres.py` | Carrega os resultados no PostgreSQL (pode repetir) |
| `sql/schema.sql` | Tabela `conversao.documento` |

## Uso manual

```bash
# calibrar a detecção de flash numa amostra (não grava PDF)
python3 processar_acervo.py /acervo/entrada /acervo/saida --somente-detectar --limite 300 --salvar-removidas

# processar
python3 processar_acervo.py /acervo/entrada /acervo/saida --flash-ref /acervo/flash_exemplos --salvar-removidas
python3 resumir_local.py /acervo/saida --modelo qwen2.5:7b      # opcional
python3 importar_postgres.py /acervo/saida --dsn postgresql:///acervo
```

Saída (espelha as pastas da entrada):

```
saida/pdf/TD/2004/0000-0999/000123.pdf       PDF limpo e pesquisável
saida/ocr/TD/2004/0000-0999/000123.txt       texto do OCR
saida/resumos/TD/2004/0000-0999/000123.json  campos, resumo IA, análise de cada página
saida/removidas/TD/2004/0000-0999/000123/    miniaturas das páginas tiradas
saida/relatorio.csv                  uma linha por documento (status "revisar" = conferir)
```

Tudo é **retomável**: interrompeu, roda de novo e continua de onde parou.

## Detecção de flash

Cada página recebe pontos; ≥ 1,0 é removida, entre 0,5 e 1,0 fica no PDF e o documento vai como `revisar`.

| Sinal | Pontos |
|---|---|
| Palavras de microfilmagem ("início de rolo", "fim de rolo"...) em página com pouco texto | 1,0 |
| Parecida com um exemplo em `--flash-ref` | 1,0 |
| Poucas palavras em letra muito grande | 0,6 |
| Página quase toda preta / em branco | 1,0 |

Ajustes: `--palavras-flash arquivo.txt`, `--manter-brancas`, `--limiar`.
