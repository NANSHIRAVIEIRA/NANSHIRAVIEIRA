# Conversão de acervo do cartório (TIFF/PDF → PDF limpo + OCR + resumo)

Script que percorre uma pasta de imagens digitalizadas e, para cada documento:

1. Lê todas as páginas (TIFF multipágina; PDF opcional com `--incluir-pdf`).
2. Faz OCR em português (Tesseract).
3. **Detecta e remove as páginas de flash** da microfilmagem (também páginas pretas e em branco).
4. Gera um **PDF limpo e pesquisável** (imagem + texto invisível, dá para buscar/copiar).
5. Gera um **resumo estruturado** com Claude (tipo do ato, partes, datas, livro/folha, matrícula, imóvel, valores).
6. Registra tudo no `relatorio.csv` (abre no Excel), indicando páginas removidas e páginas em dúvida.

## Instalação

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-por
# Windows: instale o Tesseract (UB Mannheim) com o idioma Portuguese e coloque no PATH

pip install -r requirements.txt
export ANTHROPIC_API_KEY=...   # só se for gerar resumos
```

## Uso recomendado (em etapas)

```bash
# 1) Calibrar a detecção de flash numa amostra (não grava PDF, só o relatório)
python processar_acervo.py /acervo /saida --somente-detectar --limite 300 --salvar-removidas

# 2) Conferir relatorio_deteccao.csv e as miniaturas em *_removidas/.
#    Se tiver flashes padronizados, copie alguns exemplos para uma pasta e use --flash-ref.

# 3) Rodar de verdade
python processar_acervo.py /acervo /saida --flash-ref ./exemplos_flash --salvar-removidas
```

Saída, espelhando a estrutura de pastas da entrada:

```
saida/livro01/doc001.pdf        PDF limpo e pesquisável
saida/livro01/doc001.txt        texto do OCR, por página
saida/livro01/doc001.json       resumo + análise de cada página (motivo da remoção)
saida/livro01/doc001_removidas/ miniaturas das páginas tiradas (com --salvar-removidas)
saida/relatorio.csv             uma linha por documento
```

O processamento é **retomável**: se parar, rode de novo e ele pula o que já tem `.json`.

## Como o flash é detectado

Cada página recebe uma pontuação; com pontuação ≥ 1,0 ela é removida, entre 0,5 e 1,0 fica
marcada como **dúvida** no relatório (mantida no PDF) para revisão humana.

| Sinal | Pontos |
|---|---|
| Texto com palavras de microfilmagem ("início de rolo", "fim de rolo", "microfilmagem"...) em página com pouco texto | 1,0 |
| Visualmente parecida com um exemplo de flash em `--flash-ref` | 1,0 |
| Poucas palavras em letra muito grande (ficha de identificação) | 0,6 |
| Página quase toda preta / página em branco | 1,0 |

As palavras-chave podem ser trocadas com `--palavras-flash arquivo.txt` (uma por linha).
Páginas em branco podem ser mantidas com `--manter-brancas`.

## Opções principais

| Opção | Descrição |
|---|---|
| `--incluir-pdf` | Processa também os PDFs (padrão: só TIFF) |
| `--sem-resumo` | Só OCR + PDF, sem chamar o Claude |
| `--modelo` | Modelo do resumo (padrão `claude-opus-5-5`; `claude-haiku-5-5` sai bem mais barato) |
| `--workers N` | Processos em paralelo (padrão: nº de CPUs − 1) |
| `--limite N` | Processa só N arquivos (para teste) |
| `--reprocessar` | Refaz mesmo o que já foi processado |
