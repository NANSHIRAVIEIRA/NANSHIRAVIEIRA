#!/usr/bin/env bash
# Cria a estrutura de pastas do acervo.
#
#   entrada/TD/2003   TD da numeração antiga (jun-dez/2003, números na casa dos 700.000)
#   entrada/TD/2004   TD de 2004 em diante (numeração recomeçou do 1)
#   entrada/PJ/2003   PJ da numeração antiga (números na casa dos 193.000-196.000)
#   entrada/PJ/2004   PJ de 2004 em diante
#
# Dentro de cada uma, copie as pastas de milhar como estão hoje (0000-0999, 1000-1999...).
ACERVO="${ACERVO:-/acervo}"
for esp in TD PJ; do
  for serie in 2003 2004; do
    mkdir -p "$ACERVO/entrada/$esp/$serie"
  done
done
mkdir -p "$ACERVO/saida" "$ACERVO/flash_exemplos" "$ACERVO/logs"
cat > "$ACERVO/entrada/LEIA-ME.txt" <<'EOF'
Coloque as pastas de milhar dentro da especialidade e da série corretas:

  TD\2003\  -> TD registrados em 2003 (numeração antiga, ~700.000)
  TD\2004\  -> TD de 2004 em diante (numeração que recomeçou do 1)
  PJ\2003\  -> PJ registrados em 2003 (numeração antiga, ~193.000 a 196.000)
  PJ\2004\  -> PJ de 2004 em diante

"2004" quer dizer "a numeração que começou em 2004", não só o ano de 2004.
EOF
echo "Pastas criadas em $ACERVO:"
find "$ACERVO/entrada" -maxdepth 2 -type d | sort
