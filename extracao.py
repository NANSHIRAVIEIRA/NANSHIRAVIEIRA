"""
Extração automática de campos do texto do OCR, sem IA (100% local, instantâneo).

Procura por padrões: CPF/CNPJ (com validação dos dígitos), datas, livro, folha,
matrícula, protocolo, registro, valores em moeda e o tipo provável do documento.
O OCR erra, então tudo aqui é "candidato" — confira antes de usar como verdade.
"""
from __future__ import annotations

import re
import unicodedata

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Ordem importa: o primeiro que aparecer no começo do texto ganha.
TIPOS = [
    "escritura publica de compra e venda", "escritura de compra e venda", "compra e venda",
    "escritura de doacao", "doacao", "escritura de permuta", "permuta",
    "inventario", "partilha", "formal de partilha", "carta de adjudicacao", "adjudicacao",
    "carta de arrematacao", "arrematacao", "usucapiao",
    "hipoteca", "alienacao fiduciaria", "cedula de credito", "cedula rural", "penhor",
    "penhora", "arresto", "sequestro", "indisponibilidade",
    "averbacao", "cancelamento", "retificacao", "desmembramento", "unificacao", "loteamento",
    "incorporacao", "instituicao de condominio", "convencao de condominio",
    "contrato de locacao", "locacao", "contrato social", "estatuto", "ata de assembleia", "ata",
    "procuracao", "substabelecimento", "notificacao", "pacto antenupcial", "testamento",
    "certidao", "requerimento", "mandado", "oficio", "contrato",
]

_NUM = r"(?:n[o°º.]*\s*)?"


def normalizar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"[ \t]+", " ", txt.lower())


def _cpf_valido(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _cnpj_valido(d: str) -> bool:
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
                     (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        s = sum(int(d[i]) * pesos[i] for i in range(n))
        dv = 0 if s % 11 < 2 else 11 - s % 11
        if dv != int(d[n]):
            return False
    return True


def _unicos(seq):
    vistos, out = set(), []
    for x in seq:
        if x not in vistos:
            vistos.add(x)
            out.append(x)
    return out


def _data_iso(d: int, m: int, a: int) -> str | None:
    if a < 100:
        a += 1900 if a > 30 else 2000
    if 1 <= d <= 31 and 1 <= m <= 12 and 1850 <= a <= 2100:
        return f"{a:04d}-{m:02d}-{d:02d}"
    return None


def extrair_campos(texto: str) -> dict:
    n = normalizar(texto)

    cpfs, cnpjs = [], []
    for m in re.finditer(r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}\s?-?\s?\d{2})(?!\d)", texto):
        d = re.sub(r"\D", "", m.group(1))
        if _cpf_valido(d):
            cpfs.append(f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}")
    for m in re.finditer(r"(?<!\d)(\d{2}\.?\d{3}\.?\d{3}\s?/?\s?\d{4}\s?-?\s?\d{2})(?!\d)", texto):
        d = re.sub(r"\D", "", m.group(1))
        if _cnpj_valido(d):
            cnpjs.append(f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}")

    datas = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?!\d)", n):
        iso = _data_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso:
            datas.append(iso)
    for m in re.finditer(r"(?<!\d)(\d{1,2})[o°º]?\s+de\s+(" + "|".join(MESES) + r")\s+de\s+(\d{4})", n):
        iso = _data_iso(int(m.group(1)), MESES[m.group(2)], int(m.group(3)))
        if iso:
            datas.append(iso)
    # "aos dez dias do mês de março de 1987" -> pelo menos mês/ano
    for m in re.finditer(r"mes de (" + "|".join(MESES) + r")\s+(?:do ano )?de\s+(\d{4})", n):
        datas.append(f"{int(m.group(2)):04d}-{MESES[m.group(1)]:02d}")

    def achar(padrao: str) -> list[str]:
        return _unicos(re.sub(r"\s+", "", m.group(1)).strip(".") for m in re.finditer(padrao, n))

    livros = achar(r"\blivro\s*" + _NUM + r"(\d{1,4}(?:\s?-?\s?[a-z](?![a-z]))?)")
    folhas = achar(r"\b(?:folhas?|fls?\.?|fl\.)\s*" + _NUM + r"(\d{1,4}(?:\s?v(?:erso)?\b)?)")
    matriculas = achar(r"\bmatricula\s*" + _NUM + r"(\d[\d.]{0,9})")
    protocolos = achar(r"\bprotocolo\s*" + _NUM + r"(\d[\d.]{0,9})")
    registros = achar(r"\bregistr(?:o|ado)\s+(?:sob\s+(?:o\s+)?)?" + _NUM + r"(\d[\d.]{0,9})")

    valores = _unicos(m.group(0).replace(" ", "") for m in re.finditer(
        r"(?:R\$|NCz\$|Cz\$|NCr\$|Cr\$|CR\$)\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})?", texto))

    inicio = n[:3000]
    tipo = ""
    pos_melhor = None
    for t in TIPOS:
        p = inicio.find(t)
        if p >= 0 and (pos_melhor is None or p < pos_melhor):
            tipo, pos_melhor = t, p

    return {
        "tipo_provavel": tipo,
        "cpfs": _unicos(cpfs),
        "cnpjs": _unicos(cnpjs),
        "datas": _unicos(datas),
        "livros": livros,
        "folhas": folhas,
        "matriculas": matriculas,
        "protocolos": protocolos,
        "registros": registros,
        "valores": valores,
    }
