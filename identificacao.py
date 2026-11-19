"""
Identificação única de cada documento: especialidade + série + número.

Por que: em 2003 (jun-dez) o cartório usava a numeração antiga (PJ ~193.000-196.000,
TD ~700.000). Em 2004 a numeração recomeçou do 1. O TD de 2004 em diante já passou
dos 700.000 e repetiu números de 2003; o PJ ainda não chegou lá. TD e PJ têm
numerações independentes. O número sozinho NÃO identifica o documento.

A identificação vem das pastas da entrada (crie com criar_pastas.sh):

    entrada/TD/2003/700000-700999/700500.tif  -> TD, série 2003, nº 700500
    entrada/TD/2004/700000-700999/700500.tif  -> TD, série 2004, nº 700500 (outro documento!)
    entrada/PJ/2004/0000-0999/000500.tif      -> PJ, série 2004, nº 500

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
