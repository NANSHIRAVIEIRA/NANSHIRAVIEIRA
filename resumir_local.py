#!/usr/bin/env python3
"""
Etapa 2 (opcional): resumo em texto com IA rodando no próprio servidor (Ollama).

Lê os documentos já processados por processar_acervo.py (saida/resumos/*.json),
manda o texto do OCR para o modelo local e grava o resultado no campo "resumo_ia"
do mesmo JSON. Nada sai do servidor.

Retomável: só pega os JSON que ainda não têm resumo_ia.

Exemplo:
    python3 resumir_local.py /acervo/saida --modelo qwen2.5:7b
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

log = logging.getLogger("resumo")

SCHEMA_RESUMO = {
    "type": "object",
    "required": ["tipo_documento", "resumo", "partes", "imovel", "observacoes"],
    "properties": {
        "tipo_documento": {"type": "string"},
        "resumo": {"type": "string"},
        "partes": {"type": "array", "items": {
            "type": "object",
            "required": ["nome", "papel"],
            "properties": {"nome": {"type": "string"}, "papel": {"type": "string"}},
        }},
        "imovel": {"type": "string"},
        "observacoes": {"type": "string"},
    },
}

PROMPT_SISTEMA = """Você analisa documentos digitalizados de um cartório brasileiro.
Recebe o texto obtido por OCR (pode ter erros de leitura) e responde em JSON com:
- tipo_documento: o tipo do ato (ex.: escritura de compra e venda, averbação, hipoteca, procuração).
- resumo: resumo objetivo em 2 a 5 frases, em português.
- partes: pessoas e empresas envolvidas, com o papel de cada uma (vendedor, comprador, outorgante...).
- imovel: descrição curta do imóvel, se houver; senão "".
- observacoes: trechos ilegíveis ou dúvidas; senão "".
Use somente o que está no texto. Não invente nomes, números ou datas."""


def chamar_ollama(url: str, modelo: str, texto: str, nome: str, num_ctx: int, timeout: int) -> dict:
    corpo = {
        "model": modelo,
        "stream": False,
        "format": SCHEMA_RESUMO,
        "options": {"temperature": 0, "num_ctx": num_ctx},
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": f"Arquivo: {nome}\n\n<texto_ocr>\n{texto}\n</texto_ocr>"},
        ],
    }
    req = urllib.request.Request(url.rstrip("/") + "/api/chat",
                                 data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.load(r)
    return json.loads(resp["message"]["content"])


def processar(json_path: Path, saida: Path, args) -> tuple[Path, str]:
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    ocr = saida / meta["ocr"]
    texto = ocr.read_text(encoding="utf-8") if ocr.exists() else ""
    if not texto.strip():
        return json_path, "sem_texto"
    truncado = len(texto) > args.max_chars
    if truncado:
        texto = texto[: args.max_chars] + "\n[... texto truncado ...]"
    inicio = time.time()
    resumo = chamar_ollama(args.url, args.modelo, texto, meta["arquivo_origem"],
                           args.num_ctx, args.timeout)
    resumo["_modelo"] = args.modelo
    resumo["_texto_truncado"] = truncado
    resumo["_segundos"] = round(time.time() - inicio, 1)
    meta["resumo_ia"] = resumo
    tmp = json_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(json_path)
    return json_path, f"ok ({resumo['_segundos']}s)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saida", type=Path, help="Mesma pasta de saída usada no processar_acervo.py")
    ap.add_argument("--modelo", default="qwen2.5:7b", help="Modelo instalado no Ollama")
    ap.add_argument("--url", default="http://localhost:11434", help="Endereço do Ollama")
    ap.add_argument("--max-chars", type=int, default=20_000, help="Máx. de caracteres enviados por documento")
    ap.add_argument("--num-ctx", type=int, default=16_384, help="Janela de contexto do modelo (tokens)")
    ap.add_argument("--paralelo", type=int, default=1, help="Pedidos simultâneos (1 em CPU; 2-4 com GPU)")
    ap.add_argument("--timeout", type=int, default=1800, help="Tempo máximo por documento (s)")
    ap.add_argument("--limite", type=int, default=0, help="Processar só N documentos (teste)")
    ap.add_argument("--refazer", action="store_true", help="Refaz mesmo os que já têm resumo")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    pendentes = []
    for p in sorted((args.saida / "resumos").rglob("*.json")):
        if args.refazer or json.loads(p.read_text(encoding="utf-8")).get("resumo_ia") is None:
            pendentes.append(p)
    if args.limite:
        pendentes = pendentes[: args.limite]
    log.info("%d documento(s) sem resumo; modelo %s", len(pendentes), args.modelo)

    erros = 0
    with ThreadPoolExecutor(max_workers=args.paralelo) as ex:
        futs = {ex.submit(processar, p, args.saida, args): p for p in pendentes}
        for i, f in enumerate(as_completed(futs), 1):
            p = futs[f]
            try:
                _, st = f.result()
                log.info("[%d/%d] %s -> %s", i, len(pendentes), p.relative_to(args.saida), st)
            except urllib.error.URLError as e:
                log.error("Não consegui falar com o Ollama em %s: %s", args.url, e)
                erros += 1
            except Exception as e:
                log.error("[%d/%d] %s -> erro: %s", i, len(pendentes), p.relative_to(args.saida), e)
                erros += 1
    log.info("Concluído. Erros: %d", erros)
    return 0 if erros == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
