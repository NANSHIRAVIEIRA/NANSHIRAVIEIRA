"""
Identificação única de cada documento: especialidade + série + número.

Por que: a numeração foi zerada em 2004, então o mesmo número existe duas vezes
(série 2003 e série 2004 em diante). E TD e PJ têm numerações independentes.
O número sozinho NÃO identifica o documento.

A identificação vem das pastas da entrada:

    entrada/TD/2003/0000-0999/000500.tif   -> TD, série 2003, nº 500
    entrada/TD/2004/0000-0999/000500.tif   -> TD, série 2004, nº 500
    entrada/PJ/2004/0000-0999/000500.tif   -> PJ, série 2004, nº 500

- Especialidade: uma pasta chamada TD/RTD ou PJ/RCPJ.
- Série: uma pasta com exatamente 4 dígitos de ano (2003, 2004...). É o ano em
  que AQUELA numeração começou, não o ano de cada registro.
- Número: a maior sequência de dígitos no nome do arquivo.

Códigos gerados:
    codigo           "TD-2004-0000500"        (texto, para nomes de pasta/arquivo e leitura humana)
    codigo_numerico  20040000500              (série × 10.000.000 + número; precisa de BIGINT)
"""
from __future__ import annotations

import re
from pathlib import Path

ESPECIALIDADES = {"TD": "TD", "RTD": "TD", "PJ": "PJ", "RCPJ": "PJ"}
DIGITOS_NUMERO = 7               # até 9.999.999 registros por série
FATOR = 10 ** DIGITOS_NUMERO


def identificar(rel: Path) -> dict:
    esp = serie = None
    for parte in rel.parent.parts:
        up = parte.strip().upper()
        if esp is None and up in ESPECIALIDADES:
            esp = ESPECIALIDADES[up]
        elif serie is None and re.fullmatch(r"(19|20)\d\d", up):
            serie = int(up)
    grupos = re.findall(r"\d+", rel.stem)
    numero = int(max(grupos, key=len)) if grupos else None

    codigo = codigo_num = None
    if numero is not None:
        if numero >= FATOR:
            raise ValueError(f"número {numero} tem mais de {DIGITOS_NUMERO} dígitos")
        codigo = "-".join(x for x in (esp, str(serie) if serie else None,
                                      f"{numero:0{DIGITOS_NUMERO}d}") if x)
        if serie:
            codigo_num = serie * FATOR + numero
    return {"especialidade": esp, "serie": serie, "numero": numero,
            "codigo": codigo, "codigo_numerico": codigo_num}
