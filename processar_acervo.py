#!/usr/bin/env python3
"""
Conversão de acervo de cartório: TIFF/PDF -> PDF pesquisável limpo + OCR + campos extraídos.

Tudo roda localmente: nenhum texto ou imagem sai do servidor.

Para cada documento encontrado na pasta de entrada:
  1. Lê todas as páginas (TIFF multipágina ou PDF).
  2. Faz OCR (Tesseract, português).
  3. Detecta e remove as páginas de "flash" de microfilmagem.
  4. Gera um PDF limpo e pesquisável (imagem + camada de texto invisível).
  5. Extrai campos automaticamente (CPF/CNPJ, datas, livro, folha, matrícula, valores...).
  6. Registra tudo num relatório CSV para auditoria.

Organize a entrada por especialidade e série (ver identificacao.py):
  entrada/TD/2003/0000-0999/000500.tif

Saída (espelha as subpastas da entrada):
  saida/pdf/...      PDFs limpos
  saida/ocr/...      texto do OCR
  saida/resumos/...  JSON com campos extraídos e análise das páginas
  saida/removidas/.. miniaturas das páginas tiradas (com --salvar-removidas)

O resumo em texto por IA local é uma etapa separada (resumir_local.py), para o
OCR não ficar esperando a IA. O processamento é retomável: documentos com JSON
em saida/resumos são pulados.
"""
from __future__ import annotations

import os

# O Tesseract abre várias threads por padrão; com vários processos em paralelo
# isso faz eles brigarem pela CPU e fica MUITO mais lento. 1 thread por processo.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

import argparse
import csv
import io
import json
import logging
import re
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path

import pymupdf as fitz
import numpy as np
import pytesseract
from PIL import Image, ImageOps, ImageSequence

from extracao import extrair_campos
from identificacao import identificar

Image.MAX_IMAGE_PIXELS = None  # digitalizações grandes são legítimas

log = logging.getLogger("acervo")

EXT_TIFF = {".tif", ".tiff"}
EXT_PDF = {".pdf"}

# Palavras típicas das fichas de flash / alvo de microfilmagem.
# Ajuste conforme o padrão do seu cartório (ou use --palavras-flash arquivo.txt).
PALAVRAS_FLASH_PADRAO = [
    "inicio de rolo", "fim de rolo", "inicio do rolo", "fim do rolo",
    "continua no rolo", "continuacao do rolo", "rolo n",
    "inicio de microfilmagem", "fim de microfilmagem", "microfilmagem",
    "microfilme", "termo de abertura de rolo", "termo de encerramento de rolo",
    "carta de resolucao", "resolution chart", "iso test chart",
    "documento ilegivel", "pagina em branco", "flash",
]


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def normalizar(txt: str) -> str:
    """Minúsculas, sem acento, espaços colapsados — para comparar palavras-chave."""
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt.lower()).strip()


def dhash(img: Image.Image, tamanho: int = 16) -> int:
    """Hash perceptual (difference hash) para comparar com fichas de flash de referência."""
    g = img.convert("L").resize((tamanho + 1, tamanho), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def carregar_paginas(caminho: Path, dpi_pdf: int) -> list[Image.Image]:
    ext = caminho.suffix.lower()
    paginas: list[Image.Image] = []
    if ext in EXT_TIFF:
        with Image.open(caminho) as im:
            for frame in ImageSequence.Iterator(im):
                f = frame.copy()
                dpi = frame.info.get("dpi")
                if dpi:
                    f.info["dpi"] = dpi
                paginas.append(f)
    elif ext in EXT_PDF:
        with fitz.open(caminho) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=dpi_pdf, colorspace=fitz.csGRAY)
                im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
                im.info["dpi"] = (dpi_pdf, dpi_pdf)
                paginas.append(im)
    return paginas


def preparar_para_ocr(img: Image.Image) -> Image.Image:
    """Converte para escala de cinza / P&B mantendo a orientação EXIF."""
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("1", "L"):
        img = img.convert("L")
    return img


# ----------------------------------------------------------------------------
# Detecção de flash
# ----------------------------------------------------------------------------
@dataclass
class AnalisePagina:
    indice: int                # 1-based
    texto: str
    palavras: int
    tinta: float               # fração de pixels escuros
    altura_mediana_letra: float  # em fração da altura da página
    pontuacao_flash: float
    motivos: list[str] = field(default_factory=list)
    flash: bool = False
    duvida: bool = False


@dataclass
class ConfigFlash:
    palavras: list[str]
    hashes_referencia: list[int]
    distancia_hash: int = 40       # de 256 bits; menor = mais parecido
    limiar: float = 1.0            # pontuação >= limiar => flash
    limiar_duvida: float = 0.5     # entre duvida e limiar => marcar para revisão
    remover_brancas: bool = True


def analisar_pagina(img: Image.Image, indice: int, lang: str, cfg: ConfigFlash) -> AnalisePagina:
    g = img.convert("L")
    a = np.asarray(g)
    tinta = float((a < 128).mean())

    # Página quase toda preta: não precisa de OCR (e o Tesseract pode demorar
    # muito nela). Página clara SEMPRE passa pelo OCR: pode ter pouco texto.
    if tinta > 0.85:
        texto, palavras_validas, alt_med = "", [], 0.0
    else:
        dados = pytesseract.image_to_data(g, lang=lang, output_type=pytesseract.Output.DICT)
        alturas, palavras_validas = [], []
        linhas: dict[tuple, list[str]] = {}
        for i, txt in enumerate(dados["text"]):
            if not txt.strip():
                continue
            chave = (dados["block_num"][i], dados["par_num"][i], dados["line_num"][i])
            linhas.setdefault(chave, []).append(txt)
            try:
                conf = float(dados["conf"][i])
            except (TypeError, ValueError):
                conf = -1
            if conf >= 40:
                palavras_validas.append(txt)
                alturas.append(dados["height"][i])
        # Remonta o texto linha a linha, separando parágrafos/blocos com linha em branco
        partes, anterior = [], None
        for chave, palavras in linhas.items():
            if anterior is not None and chave[:2] != anterior[:2]:
                partes.append("")
            partes.append(" ".join(palavras))
            anterior = chave
        texto = "\n".join(partes)
        alt_med = float(np.median(alturas)) / g.height if alturas else 0.0

    pont, motivos = 0.0, []
    norm = normalizar(texto)

    # 1) Palavras-chave de microfilmagem
    hits = [p for p in cfg.palavras if p in norm]
    if hits:
        # Página de flash costuma ter pouco texto; documento que só cita a palavra tem muito.
        peso = 1.0 if len(palavras_validas) < 60 else 0.3
        pont += peso
        motivos.append(f"palavra-chave: {', '.join(hits[:3])}")

    # 2) Semelhança visual com fichas de flash de referência
    if cfg.hashes_referencia:
        h = dhash(g)
        dist = min(hamming(h, r) for r in cfg.hashes_referencia)
        if dist <= cfg.distancia_hash:
            pont += 1.0
            motivos.append(f"parecida com flash de referência (dist={dist})")
        elif dist <= cfg.distancia_hash * 1.4:
            pont += 0.4
            motivos.append(f"levemente parecida com referência (dist={dist})")

    # 3) Letras gigantes e pouco texto (ficha de identificação de rolo/livro)
    if palavras_validas and len(palavras_validas) <= 25 and alt_med >= 0.025:
        pont += 0.6
        motivos.append(f"poucas palavras ({len(palavras_validas)}) em letra grande")

    # 4) Página praticamente preta (quadro de flash) ou em branco
    if tinta > 0.85:
        pont += 1.0
        motivos.append(f"página quase toda preta ({tinta:.0%})")
    elif cfg.remover_brancas and len(palavras_validas) == 0:
        if tinta < 0.0005:
            pont += 1.0
            motivos.append(f"página em branco (tinta {tinta:.2%})")
        elif tinta < 0.003:
            # Sem texto, mas com alguma marca: pode ser só assinatura ou carimbo.
            pont += 0.5
            motivos.append(f"quase em branco, sem texto (tinta {tinta:.2%}) — pode ter assinatura/carimbo")

    an = AnalisePagina(indice, texto, len(palavras_validas), tinta, alt_med, pont, motivos)
    an.flash = pont >= cfg.limiar
    an.duvida = (not an.flash) and pont >= cfg.limiar_duvida
    return an


# ----------------------------------------------------------------------------
# PDF pesquisável
# ----------------------------------------------------------------------------
def gerar_pdf(paginas: list[Image.Image], destino: Path, lang: str) -> None:
    saida = fitz.open()
    for img in paginas:
        pdf_bytes = pytesseract.image_to_pdf_or_hocr(img, lang=lang, extension="pdf")
        with fitz.open("pdf", pdf_bytes) as p:
            saida.insert_pdf(p)
    destino.parent.mkdir(parents=True, exist_ok=True)
    saida.save(destino, garbage=4, deflate=True)
    saida.close()


# ----------------------------------------------------------------------------
# Processamento de um documento
# ----------------------------------------------------------------------------
@dataclass
class Opcoes:
    entrada: Path
    saida: Path
    lang: str
    dpi_pdf: int
    salvar_removidas: bool
    somente_detectar: bool
    cfg_flash: ConfigFlash


def caminhos_saida(rel: Path, saida: Path) -> dict[str, Path]:
    sem_ext = rel.with_suffix("")
    return {
        "pdf": saida / "pdf" / sem_ext.with_suffix(".pdf"),
        "ocr": saida / "ocr" / sem_ext.with_suffix(".txt"),
        "json": saida / "resumos" / sem_ext.with_suffix(".json"),
        "removidas": saida / "removidas" / sem_ext,
    }


def processar_documento(caminho: Path, op: Opcoes) -> dict:
    inicio = time.time()
    rel = caminho.relative_to(op.entrada)
    cam = caminhos_saida(rel, op.saida)
    ident = identificar(rel)
    reg = {"arquivo": str(rel), **ident, "status": "ok",
           "paginas_originais": 0, "paginas_removidas": "", "paginas_duvida": "", "pdf": "",
           "tipo_provavel": "", "erro": "", "segundos": 0}
    try:
        paginas = [preparar_para_ocr(p) for p in carregar_paginas(caminho, op.dpi_pdf)]
        reg["paginas_originais"] = len(paginas)
        analises = [analisar_pagina(p, i + 1, op.lang, op.cfg_flash) for i, p in enumerate(paginas)]

        removidas = [a for a in analises if a.flash]
        duvidas = [a for a in analises if a.duvida]
        reg["paginas_removidas"] = " ".join(str(a.indice) for a in removidas)
        reg["paginas_duvida"] = " ".join(str(a.indice) for a in duvidas)
        if duvidas:
            reg["status"] = "revisar"

        if op.salvar_removidas and removidas:
            cam["removidas"].mkdir(parents=True, exist_ok=True)
            for a in removidas:
                th = paginas[a.indice - 1].convert("L")
                th.thumbnail((800, 800))
                th.save(cam["removidas"] / f"pag{a.indice:04d}.png")

        mantidas = [(p, a) for p, a in zip(paginas, analises) if not a.flash]
        if not mantidas:
            reg["status"] = "todas_paginas_removidas"

        texto = "\n\n".join(f"===== Página {a.indice} =====\n{a.texto.strip()}" for _, a in mantidas)
        campos = extrair_campos(texto)
        reg["tipo_provavel"] = campos["tipo_provavel"]

        if not op.somente_detectar:
            if mantidas:
                gerar_pdf([p for p, _ in mantidas], cam["pdf"], op.lang)
                reg["pdf"] = str(cam["pdf"].relative_to(op.saida))
            cam["ocr"].parent.mkdir(parents=True, exist_ok=True)
            cam["ocr"].write_text(texto, encoding="utf-8")
            meta = {
                "arquivo_origem": str(rel),
                **ident,
                "pasta": str(rel.parent),
                "pdf": reg["pdf"],
                "ocr": str(cam["ocr"].relative_to(op.saida)),
                "paginas": [{k: v for k, v in asdict(a).items() if k != "texto"} for a in analises],
                "campos": campos,
                "resumo_ia": None,
                "registro": reg,
                "processado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            cam["json"].parent.mkdir(parents=True, exist_ok=True)
            cam["json"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        reg["status"] = "erro"
        reg["erro"] = f"{type(e).__name__}: {e}"
        log.exception("%s: erro", rel)
    reg["segundos"] = round(time.time() - inicio, 1)
    return reg


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def listar_arquivos(entrada: Path, incluir_pdf: bool) -> list[Path]:
    exts = EXT_TIFF | (EXT_PDF if incluir_pdf else set())
    return sorted(p for p in entrada.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def carregar_referencias(pasta: Path | None) -> list[int]:
    if not pasta:
        return []
    hashes = []
    for p in sorted(pasta.iterdir()):
        if p.suffix.lower() in EXT_TIFF | {".png", ".jpg", ".jpeg", ".bmp"}:
            with Image.open(p) as im:
                for fr in ImageSequence.Iterator(im):
                    hashes.append(dhash(fr))
    log.info("%d páginas de flash de referência carregadas de %s", len(hashes), pasta)
    return hashes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", type=Path, help="Pasta com os TIFF/PDF (busca em subpastas)")
    ap.add_argument("saida", type=Path, help="Pasta onde gravar PDFs, textos e relatório")
    ap.add_argument("--incluir-pdf", action="store_true", help="Processar também os PDFs (padrão: só TIFF)")
    ap.add_argument("--flash-ref", type=Path, help="Pasta com exemplos de páginas de flash (melhora muito a detecção)")
    ap.add_argument("--palavras-flash", type=Path, help="Arquivo .txt com palavras-chave de flash (uma por linha)")
    ap.add_argument("--manter-brancas", action="store_true", help="Não remover páginas em branco")
    ap.add_argument("--limiar", type=float, default=1.0, help="Pontuação mínima para remover página")
    ap.add_argument("--somente-detectar", action="store_true",
                    help="Só analisa e gera o relatório de flashes (não grava PDF/TXT) — use para calibrar")
    ap.add_argument("--salvar-removidas", action="store_true", help="Salva miniaturas das páginas removidas para conferência")
    ap.add_argument("--lang", default="por", help="Idioma(s) do Tesseract (ex.: por ou por+eng)")
    ap.add_argument("--dpi-pdf", type=int, default=300, help="DPI ao rasterizar PDFs de entrada")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--reprocessar", action="store_true", help="Ignora o que já foi processado")
    ap.add_argument("--limite", type=int, default=0, help="Processar só N arquivos (teste)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.entrada.is_dir():
        log.error("Pasta de entrada não existe: %s", args.entrada)
        return 2
    args.saida.mkdir(parents=True, exist_ok=True)

    palavras = PALAVRAS_FLASH_PADRAO
    if args.palavras_flash:
        palavras = [normalizar(l) for l in args.palavras_flash.read_text(encoding="utf-8").splitlines() if l.strip()]

    op = Opcoes(
        entrada=args.entrada.resolve(), saida=args.saida.resolve(), lang=args.lang,
        dpi_pdf=args.dpi_pdf, salvar_removidas=args.salvar_removidas,
        somente_detectar=args.somente_detectar,
        cfg_flash=ConfigFlash(palavras=palavras, hashes_referencia=carregar_referencias(args.flash_ref),
                              limiar=args.limiar, limiar_duvida=args.limiar / 2,
                              remover_brancas=not args.manter_brancas),
    )

    arquivos = listar_arquivos(op.entrada, args.incluir_pdf)
    if not args.reprocessar and not args.somente_detectar:
        arquivos = [a for a in arquivos
                    if not caminhos_saida(a.relative_to(op.entrada), op.saida)["json"].exists()]
    if args.limite:
        arquivos = arquivos[: args.limite]
    log.info("%d arquivo(s) para processar com %d worker(s)", len(arquivos), args.workers)

    nome_rel = "relatorio_deteccao.csv" if args.somente_detectar else "relatorio.csv"
    rel_path = op.saida / nome_rel
    novo = not rel_path.exists() or args.somente_detectar
    campos = ["arquivo", "especialidade", "serie", "numero", "codigo", "codigo_numerico", "status", "paginas_originais", "paginas_removidas",
              "paginas_duvida", "pdf", "tipo_provavel", "erro", "segundos"]
    contagem = {"ok": 0, "erro": 0}
    with open(rel_path, "w" if novo else "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        if novo:
            w.writeheader()
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futuros = {ex.submit(processar_documento, a, op): a for a in arquivos}
            for i, fut in enumerate(as_completed(futuros), 1):
                reg = fut.result()
                w.writerow(reg)
                f.flush()
                contagem["erro" if reg["status"] == "erro" else "ok"] += 1
                log.info("[%d/%d] %s -> %s (removidas: %s | dúvida: %s)", i, len(arquivos),
                         reg["arquivo"], reg["status"], reg["paginas_removidas"] or "-",
                         reg["paginas_duvida"] or "-")
    log.info("Concluído: %d ok, %d com erro. Relatório: %s", contagem["ok"], contagem["erro"], rel_path)
    return 0 if contagem["erro"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
