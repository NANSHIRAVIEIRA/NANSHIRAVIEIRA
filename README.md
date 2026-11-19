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

## Arquivos

| Arquivo | Etapa |
|---|---|
| `rodar_lote.sh` | Roda todas as etapas abaixo em segundo plano (`iniciar` / `status` / `parar`) |
| `inventario.py` | Lista números com/sem imagem por milhar |
| `processar_acervo.py` | OCR, remoção de flash, PDF, extração de campos |
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

Saída (espelha as pastas de milhar da entrada):

```
saida/pdf/0000-0999/000123.pdf       PDF limpo e pesquisável
saida/ocr/0000-0999/000123.txt       texto do OCR
saida/resumos/0000-0999/000123.json  campos, resumo IA, análise de cada página
saida/removidas/0000-0999/000123/    miniaturas das páginas tiradas
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
