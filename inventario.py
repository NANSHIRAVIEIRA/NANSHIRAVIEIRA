#!/usr/bin/env python3
"""
Inventário do acervo: lista quais números têm imagem e quais faltam em cada milhar.

Útil para conferir a conversão: como antigamente o número do protocolo virava o
número do registro e alguns protocolos eram devolvidos, é esperado haver lacunas.
Este relatório mostra exatamente onde elas estão.

Gera, na pasta de saída:
  inventario_arquivos.csv   um arquivo por linha (especialidade, série, número, páginas, tamanho)
  inventario_milhares.csv   resumo por especialidade/série/milhar (quantos existem, quantos faltam)
  inventario_faltantes.csv  cada número sem imagem
  inventario_duplicados.csv mesmo especialidade+série+número em mais de um arquivo

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

from identificacao import identificar

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

    # (especialidade, série) -> número -> lista de arquivos
    grupos: dict[tuple, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    sem_numero = 0
    with open(args.saida / "inventario_arquivos.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["especialidade", "serie", "numero", "codigo", "arquivo", "paginas", "tamanho_kb"])
        for p in sorted(args.entrada.rglob("*")):
            if not (p.is_file() and p.suffix.lower() in EXTS):
                continue
            rel = p.relative_to(args.entrada)
            try:
                ident = identificar(rel)
            except ValueError as e:
                print(f"AVISO: {rel}: {e}")
                ident = {"especialidade": None, "serie": None, "numero": None, "codigo": None}
            if ident["numero"] is None:
                sem_numero += 1
            else:
                grupos[(ident["especialidade"] or "", ident["serie"] or "")][ident["numero"]].append(str(rel))
            pags = "" if args.sem_paginas else contar_paginas(p)
            w.writerow([ident["especialidade"], ident["serie"], ident["numero"], ident["codigo"],
                        str(rel), pags, round(p.stat().st_size / 1024)])

    total = faltam = dup = 0
    with open(args.saida / "inventario_milhares.csv", "w", newline="", encoding="utf-8-sig") as fm, \
         open(args.saida / "inventario_faltantes.csv", "w", newline="", encoding="utf-8-sig") as ff, \
         open(args.saida / "inventario_duplicados.csv", "w", newline="", encoding="utf-8-sig") as fd:
        wm, wf, wd = (csv.writer(x, delimiter=";") for x in (fm, ff, fd))
        wm.writerow(["especialidade", "serie", "milhar", "de", "ate", "com_imagem", "sem_imagem", "menor", "maior"])
        wf.writerow(["especialidade", "serie", "numero_sem_imagem"])
        wd.writerow(["especialidade", "serie", "numero", "arquivos"])
        for (esp, serie), numeros in sorted(grupos.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            for n, arqs in sorted(numeros.items()):
                if len(arqs) > 1:
                    wd.writerow([esp, serie, n, " | ".join(arqs)])
                    dup += 1
            milhares = sorted({n // 1000 for n in numeros})
            for m in milhares:
                nums = {n for n in numeros if n // 1000 == m}
                de, ate = m * 1000, m * 1000 + 999
                # Na primeira e na última faixa da série considera só o intervalo usado
                lo = min(nums) if m == milhares[0] else de
                hi = max(nums) if m == milhares[-1] else ate
                falt = [n for n in range(lo, hi + 1) if n not in nums]
                wm.writerow([esp, serie, m, de, ate, len(nums), len(falt), min(nums), max(nums)])
                for n in falt:
                    wf.writerow([esp, serie, n])
                total += len(nums)
                faltam += len(falt)

    if any(not esp or not serie for esp, serie in grupos):
        print("AVISO: há arquivos fora do padrão de pastas ESPECIALIDADE/SÉRIE (ex.: TD/2004/...).")
    if dup:
        print(f"ATENÇÃO: {dup} número(s) duplicado(s) dentro da mesma série — ver inventario_duplicados.csv")
    print(f"{total} números com imagem, {faltam} sem imagem, {sem_numero} arquivo(s) sem número no nome.")
    print(f"Relatórios em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
