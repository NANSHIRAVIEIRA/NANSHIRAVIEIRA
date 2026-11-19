#!/usr/bin/env python3
"""
Inventário do acervo: lista quais números têm imagem e quais faltam em cada milhar.

Útil para conferir a conversão: como antigamente o número do protocolo virava o
número do registro e alguns protocolos eram devolvidos, é esperado haver lacunas.
Este relatório mostra exatamente onde elas estão.

Gera, na pasta de saída:
  inventario_arquivos.csv  um arquivo por linha (pasta, número, páginas, tamanho)
  inventario_milhares.csv  resumo por milhar (quantos existem, quantos faltam)
  inventario_faltantes.csv cada número sem imagem

Exemplo:
    python3 inventario.py /acervo/entrada /acervo/saida
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

EXTS = {".tif", ".tiff", ".pdf"}


def contar_paginas(p: Path) -> int | str:
    try:
        if p.suffix.lower() == ".pdf":
            import pymupdf
            with pymupdf.open(p) as d:
                return len(d)
        with Image.open(p) as im:
            return getattr(im, "n_frames", 1)
    except Exception as e:
        return f"erro: {e}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", type=Path)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--sem-paginas", action="store_true", help="Não abre os arquivos (mais rápido)")
    args = ap.parse_args(argv)
    args.saida.mkdir(parents=True, exist_ok=True)

    por_milhar: dict[int, set[int]] = defaultdict(set)
    sem_numero = 0
    with open(args.saida / "inventario_arquivos.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["pasta", "arquivo", "numero", "paginas", "tamanho_kb"])
        for p in sorted(args.entrada.rglob("*")):
            if not (p.is_file() and p.suffix.lower() in EXTS):
                continue
            grupos = re.findall(r"\d+", p.stem)
            num = int(max(grupos, key=len)) if grupos else None
            if num is None:
                sem_numero += 1
            else:
                por_milhar[num // 1000].add(num)
            pags = "" if args.sem_paginas else contar_paginas(p)
            w.writerow([str(p.parent.relative_to(args.entrada)), p.name, num, pags,
                        round(p.stat().st_size / 1024)])

    total = faltam = 0
    with open(args.saida / "inventario_milhares.csv", "w", newline="", encoding="utf-8-sig") as fm, \
         open(args.saida / "inventario_faltantes.csv", "w", newline="", encoding="utf-8-sig") as ff:
        wm, wf = csv.writer(fm, delimiter=";"), csv.writer(ff, delimiter=";")
        wm.writerow(["milhar", "de", "ate", "com_imagem", "sem_imagem", "menor", "maior"])
        wf.writerow(["numero_sem_imagem"])
        for m in sorted(por_milhar):
            nums = por_milhar[m]
            de, ate = m * 1000, m * 1000 + 999
            # Na primeira e na última faixa considera só o intervalo efetivamente usado
            lo = min(nums) if m == min(por_milhar) else de
            hi = max(nums) if m == max(por_milhar) else ate
            falt = [n for n in range(lo, hi + 1) if n not in nums]
            wm.writerow([m, de, ate, len(nums), len(falt), min(nums), max(nums)])
            for n in falt:
                wf.writerow([n])
            total += len(nums)
            faltam += len(falt)

    print(f"{total} números com imagem, {faltam} sem imagem, {sem_numero} arquivo(s) sem número no nome.")
    print(f"Relatórios em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
