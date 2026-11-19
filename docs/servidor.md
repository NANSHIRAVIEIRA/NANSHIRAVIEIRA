# Montagem do servidor de conversão

Tudo roda dentro do servidor: OCR, IA e banco. Nenhuma imagem ou texto vai para a internet.

```
 Notebook (Windows)                       Servidor (Ubuntu Server)
 ┌────────────────────┐   rede de casa    ┌────────────────────────────────────┐
 │ Explorer:          │ ◄───────────────► │ /acervo/entrada   ← TIFF/PDF       │
 │  \\acervo\acervo   │  (Samba)          │ /acervo/saida/pdf      PDFs limpos │
 │                    │                   │ /acervo/saida/ocr      textos      │
 │ Terminal: ssh      │ ◄───────────────► │ /acervo/saida/resumos  JSON        │
 └────────────────────┘                   │ PostgreSQL  (conversao.documento)  │
                                          │ Ollama      (IA local, opcional)   │
                                          └────────────────────────────────────┘
```

---

## 1. Para o TI, na formatação

- **Ubuntu Server 24.04 LTS** (sem interface gráfica).
- **Ativar criptografia do disco (LUKS)** no instalador, em "Use an entire disk" → "Encrypt the LVM group".
  É importante: o servidor vai ter dados pessoais do acervo e vai sair do cartório.
  (Guarde a senha do disco em local seguro: sem ela os dados não podem ser recuperados.)
- Marcar **Install OpenSSH server** durante a instalação.
- Nome do servidor (hostname): `acervo`.
- Criar um usuário administrador (ex.: `renan`), com senha forte.
- Se houver vários discos: o sistema num disco, e o maior disco montado em `/acervo`.
- Anotar: **processador, memória RAM, discos e placa de vídeo** (comando `lscpu`, `free -h`, `lsblk`, `lspci | grep -i vga`).

## 2. Primeiro acesso (do notebook)

No Windows, abra o **Terminal** (ou PowerShell) e digite:

```bash
ssh renan@acervo          # se não achar pelo nome, use o IP: ssh renan@192.168.0.50
```

Para descobrir o IP, no próprio servidor: `ip -4 addr | grep inet`.

## 3. Instalar os programas

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-pip python3-venv tesseract-ocr tesseract-ocr-por \
                    postgresql samba curl

# Código deste projeto
sudo mkdir -p /opt/acervo && sudo chown $USER /opt/acervo
git clone https://github.com/nanshiravieira/nanshiravieira.git /opt/acervo
cd /opt/acervo
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo 'export PATH=/opt/acervo/.venv/bin:$PATH' >> ~/.bashrc && source ~/.bashrc
```

## 4. Pastas

```bash
sudo mkdir -p /acervo && sudo chown -R $USER:$USER /acervo
/opt/acervo/criar_pastas.sh
```

Isso cria `entrada/TD/2003`, `entrada/TD/2004`, `entrada/PJ/2003`, `entrada/PJ/2004`,
além de `saida`, `flash_exemplos` e `logs`.

## 5. Compartilhar as pastas na rede (Samba)

```bash
sudo tee -a /etc/samba/smb.conf >/dev/null <<EOF

[acervo]
   path = /acervo
   read only = no
   valid users = $USER
EOF
sudo smbpasswd -a $USER        # cria a senha de acesso pela rede
sudo systemctl restart smbd
```

No Windows: Explorer → barra de endereço → `\\acervo\acervo` (ou `\\IP\acervo`).
Clique com o direito em "Este Computador" → "Mapear unidade de rede" para virar, por exemplo, a unidade `Z:`.

## 6. Banco de dados (PostgreSQL)

```bash
sudo -u postgres createuser $USER
sudo -u postgres createdb -O $USER acervo
psql acervo -f /opt/acervo/sql/schema.sql
```

## 7. IA local (opcional, para o resumo em texto)

Só vale a pena se o servidor tiver memória e/ou placa de vídeo razoáveis — decidimos depois de ver o hardware.

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b          # ~5 GB; testaremos outros modelos numa amostra
```

## 8. Rodar um lote

1. Copie as pastas de milhar para `Z:\entrada`, **separadas por especialidade e série**:

   ```
   Z:\entrada\TD\2003\0000-0999\...   numeração de jun/2003 (antes de zerar)
   Z:\entrada\TD\2004\0000-0999\...   numeração de 2004 em diante
   Z:\entrada\PJ\2003\...
   Z:\entrada\PJ\2004\...
   ```

   A série é o ano em que **aquela numeração começou**, não o ano de cada registro.
   Arquivos fora desse padrão são processados, mas ficam sem especialidade/série no banco
   (consulta `SELECT * FROM conversao.sem_identificacao`).
2. (Recomendado) Coloque 5–10 exemplos de página de flash em `Z:\flash_exemplos`.
3. No terminal do servidor:

```bash
cd /opt/acervo
./rodar_lote.sh            # inicia (pode fechar o terminal)
./rodar_lote.sh status     # acompanha
./rodar_lote.sh parar      # interrompe; ao rodar de novo, continua de onde parou
```

O script confere antes se há espaço em disco para tudo; se não houver, avisa para processar por partes.

O lote faz, em ordem: inventário → OCR/flash/PDF → resumo IA (se ligado) → importação no banco.

Resultados em `Z:\saida\`:

| Pasta / arquivo | Conteúdo |
|---|---|
| `pdf\TD\2004\0000-0999\000123.pdf` | PDF limpo e pesquisável |
| `ocr\TD\2004\0000-0999\000123.txt` | Texto do OCR |
| `resumos\TD\2004\0000-0999\000123.json` | Campos extraídos, resumo da IA, motivo de cada página removida |
| `removidas\TD\2004\0000-0999\000123\` | Miniaturas das páginas tiradas, para conferência |
| `relatorio.csv` | Uma linha por documento — filtre `status = revisar` |
| `inventario\inventario_faltantes.csv` | Números sem imagem em cada milhar, por especialidade/série |
| `inventario\inventario_duplicados.csv` | Mesmo número duas vezes na mesma série (decidir manualmente) |

## 9. Consultas úteis no banco

```sql
-- quantos por situação
SELECT status, count(*) FROM conversao.documento GROUP BY status;

-- documentos com página em dúvida (conferir manualmente)
SELECT numero, caminho_pdf, paginas_duvida FROM conversao.documento WHERE status = 'revisar';

-- busca por nome no texto
SELECT numero, caminho_pdf FROM conversao.documento
WHERE to_tsvector('portuguese', texto_ocr) @@ plainto_tsquery('portuguese', 'maria oliveira');

-- um registro específico (especialidade + série + número)
SELECT * FROM conversao.documento WHERE codigo = 'TD-2004-0000500';

-- números repetidos na mesma série
SELECT * FROM conversao.duplicados;

-- documentos que parecem estar na pasta de série errada (2003 x 2004) — conferir
SELECT codigo, menor_ano, maior_ano, alerta FROM conversao.conferencia_series;

-- por matrícula
SELECT numero, caminho_pdf FROM conversao.documento WHERE campos->'matriculas' ? '4.567';
```

## Comandos básicos de Linux

| Comando | Para quê |
|---|---|
| `ls -lh /acervo/entrada` | listar arquivos |
| `cd /acervo` | entrar numa pasta |
| `df -h` | espaço livre em disco |
| `htop` | ver uso de CPU/memória (sair: `q`) |
| `tail -f /acervo/logs/lote.log` | acompanhar o log ao vivo (sair: `Ctrl+C`) |
| `sudo reboot` / `sudo poweroff` | reiniciar / desligar |
