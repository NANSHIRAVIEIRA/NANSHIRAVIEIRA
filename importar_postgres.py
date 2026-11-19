#!/usr/bin/env python3
"""
Etapa 3: importa os resultados (saida/resumos/*.json) para o PostgreSQL,
na tabela conversao.documento (ver sql/schema.sql).

Pode rodar quantas vezes quiser: documentos já importados são atualizados.

Exemplo:
    export PGDSN="postgresql://acervo:SENHA@localhost/acervo"
    python3 importar_postgres.py /acervo/saida
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

SQL_UPSERT = """
INSERT INTO conversao.documento (
    arquivo_origem, especialidade, serie, numero, codigo, codigo_numerico, pasta, status, paginas_originais, paginas_removidas,
    paginas_duvida, caminho_pdf, caminho_ocr, texto_ocr, tipo_provavel, campos,
    resumo_ia, erro, processado_em, importado_em)
VALUES (%(arquivo_origem)s, %(especialidade)s, %(serie)s, %(numero)s, %(codigo)s,
        %(codigo_numerico)s, %(pasta)s, %(status)s, %(paginas_originais)s,
        %(paginas_removidas)s, %(paginas_duvida)s, %(caminho_pdf)s, %(caminho_ocr)s,
        %(texto_ocr)s, %(tipo_provavel)s, %(campos)s, %(resumo_ia)s, %(erro)s,
        %(processado_em)s, now())
ON CONFLICT (arquivo_origem) DO UPDATE SET
    especialidade = EXCLUDED.especialidade, serie = EXCLUDED.serie, numero = EXCLUDED.numero,
    codigo = EXCLUDED.codigo, codigo_numerico = EXCLUDED.codigo_numerico, pasta = EXCLUDED.pasta, status = EXCLUDED.status,
    paginas_originais = EXCLUDED.paginas_originais,
    paginas_removidas = EXCLUDED.paginas_removidas, paginas_duvida = EXCLUDED.paginas_duvida,
    caminho_pdf = EXCLUDED.caminho_pdf, caminho_ocr = EXCLUDED.caminho_ocr,
    texto_ocr = EXCLUDED.texto_ocr, tipo_provavel = EXCLUDED.tipo_provavel,
    campos = EXCLUDED.campos, resumo_ia = EXCLUDED.resumo_ia, erro = EXCLUDED.erro,
    processado_em = EXCLUDED.processado_em, importado_em = now()
"""


def linha(meta: dict, saida: Path) -> dict:
    reg = meta.get("registro", {})
    ocr = saida / meta["ocr"] if meta.get("ocr") else None
    paginas = meta.get("paginas", [])
    try:
        processado = datetime.strptime(meta["processado_em"], "%Y-%m-%dT%H:%M:%S%z")
    except (KeyError, ValueError):
        processado = None
    return {
        "arquivo_origem": meta["arquivo_origem"],
        "especialidade": meta.get("especialidade"),
        "serie": meta.get("serie"),
        "numero": meta.get("numero"),
        "codigo": meta.get("codigo"),
        "codigo_numerico": meta.get("codigo_numerico"),
        "pasta": meta.get("pasta"),
        "status": reg.get("status"),
        "paginas_originais": reg.get("paginas_originais"),
        "paginas_removidas": [p["indice"] for p in paginas if p.get("flash")],
        "paginas_duvida": [p["indice"] for p in paginas if p.get("duvida")],
        "caminho_pdf": meta.get("pdf") or None,
        "caminho_ocr": meta.get("ocr"),
        "texto_ocr": ocr.read_text(encoding="utf-8") if ocr and ocr.exists() else None,
        "tipo_provavel": (meta.get("campos") or {}).get("tipo_provavel"),
        "campos": Jsonb(meta.get("campos")),
        "resumo_ia": Jsonb(meta["resumo_ia"]) if meta.get("resumo_ia") else None,
        "erro": reg.get("erro") or None,
        "processado_em": processado,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("saida", type=Path, help="Pasta de saída do processar_acervo.py")
    ap.add_argument("--dsn", default=os.environ.get("PGDSN", ""),
                    help="Conexão PostgreSQL (ou variável PGDSN)")
    ap.add_argument("--criar-tabela", action="store_true", help="Executa sql/schema.sql antes")
    args = ap.parse_args(argv)

    arquivos = sorted((args.saida / "resumos").rglob("*.json"))
    print(f"{len(arquivos)} documento(s) para importar")
    try:
        con = psycopg.connect(args.dsn)
    except psycopg.OperationalError as e:
        print(f"ERRO: não consegui conectar no PostgreSQL ({args.dsn or 'padrão'}).\n"
              f"Verifique se o banco está ligado: sudo systemctl status postgresql\n{e}")
        return 1
    with con:
        if args.criar_tabela:
            con.execute((Path(__file__).parent / "sql" / "schema.sql").read_text(encoding="utf-8"))
        with con.cursor() as cur:
            for i, p in enumerate(arquivos, 1):
                cur.execute(SQL_UPSERT, linha(json.loads(p.read_text(encoding="utf-8")), args.saida))
                if i % 500 == 0:
                    con.commit()
                    print(f"  {i}/{len(arquivos)}")
        con.commit()
    print("Importação concluída.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
