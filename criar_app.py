#!/usr/bin/env python3
"""
criar_app.py - monta o "TR-8S Grid.app" no Desktop.

    python3 criar_app.py            # cria/atualiza em ~/Desktop
    python3 criar_app.py --em /pasta

O bundle carrega uma COPIA dos scripts dentro dele. Depois de editar o gui.py
ou o lp_tr8s.py, rode isto de novo pra atualizar o app.

Por que copia, e nao um atalho pro projeto: a pasta Documents e protegida pelo
TCC do macOS e um .app nao assinado nem consegue pedir permissao - ele leva
"Operation not permitted" em silencio, sem abrir nada e sem dizer por que.

O icone e desenhado aqui mesmo - o PIL nao esta instalado, entao tem um
codificador de PNG de 20 linhas em zlib puro. O sips e o iconutil (que vem no
macOS) fazem o resto.
"""
import os, sys, zlib, struct, shutil, subprocess, tempfile

AQUI    = os.path.dirname(os.path.abspath(__file__))
NOME    = "TR-8S Grid"
# Os scripts vao pra DENTRO do bundle. Nao e capricho: a pasta Documents e
# protegida pelo TCC do macOS, e um .app nao assinado nem consegue pedir
# permissao - ele leva "Operation not permitted" em silencio. Rodando de dentro
# do proprio bundle, o app nao toca em pasta protegida nenhuma.
ARQUIVOS = ("gui.py", "lp_tr8s.py", "apagar_luzes.py")
MARCA   = "Contents/.tr8s-grid-app"   # so sobrescrevemos bundles com esta marca.
                                     # Tem que ficar em Contents/: o codesign
                                     # recusa "unsealed contents" na raiz.
IDENT   = "com.luanmoura.tr8s-grid"


# ── PNG em python puro ──────────────────────────────────────
def escrever_png(caminho, largura, altura, linhas):
    """linhas = lista de listas de (r, g, b)."""
    cru = b"".join(b"\x00" + bytes(v for px in linha for v in px)
                   for linha in linhas)

    def bloco(tipo, dados):
        return (struct.pack(">I", len(dados)) + tipo + dados +
                struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    with open(caminho, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura,
                                           8, 2, 0, 0, 0)))
        f.write(bloco(b"IDAT", zlib.compress(cru, 9)))
        f.write(bloco(b"IEND", b""))


def desenhar_icone(lado=1024):
    """O grid 16x8 como ele fica na mesa: notas acesas, o playhead verde, e as
    ultimas colunas quase pretas por estarem fora do LAST STEP."""
    FUNDO, VAZIO   = (18, 16, 14), (38, 35, 32)
    NOTA, SUB      = (255, 59, 48), (255, 149, 0)
    PLAY, FORA     = (51, 209, 122), (12, 12, 12)

    acesas = {(0, 0), (0, 4), (0, 8), (2, 4), (2, 12), (4, 2), (4, 10),
              (6, 0), (6, 3), (6, 6), (6, 9), (7, 1), (7, 5), (7, 9)}
    subs   = {(3, 6), (5, 11), (1, 2)}
    playhead, last = 8, 13

    px = [[FUNDO] * lado for _ in range(lado)]
    margem = int(lado * 0.09)
    celula = (lado - 2 * margem) // 16
    alturagrid = celula * 8
    topo = (lado - alturagrid) // 2
    folga = max(2, celula // 7)

    for l in range(8):
        for c in range(16):
            if c >= last:            cor = FORA
            elif c == playhead:      cor = PLAY
            elif (l, c) in acesas:   cor = NOTA
            elif (l, c) in subs:     cor = SUB
            else:                    cor = VAZIO
            x0, y0 = margem + c * celula + folga, topo + l * celula + folga
            for y in range(y0, y0 + celula - 2 * folga):
                linha = px[y]
                for x in range(x0, x0 + celula - 2 * folga):
                    linha[x] = cor
    return px


def montar_icns(destino):
    conj = destino + ".iconset"
    shutil.rmtree(conj, ignore_errors=True)
    os.makedirs(conj)
    mestre = os.path.join(conj, "mestre.png")
    escrever_png(mestre, 1024, 1024, desenhar_icone(1024))
    for tam in (16, 32, 128, 256, 512):
        for escala, sufixo in ((1, ""), (2, "@2x")):
            alvo = os.path.join(conj, f"icon_{tam}x{tam}{sufixo}.png")
            subprocess.run(["sips", "-z", str(tam*escala), str(tam*escala),
                            mestre, "--out", alvo],
                           check=True, capture_output=True)
    os.remove(mestre)
    subprocess.run(["iconutil", "-c", "icns", conj, "-o", destino], check=True)
    shutil.rmtree(conj, ignore_errors=True)


PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>                <string>{nome}</string>
  <key>CFBundleDisplayName</key>         <string>{nome}</string>
  <key>CFBundleIdentifier</key>          <string>{ident}</string>
  <key>CFBundleExecutable</key>          <string>{exe}</string>
  <key>CFBundleIconFile</key>            <string>icone</string>
  <key>CFBundlePackageType</key>         <string>APPL</string>
  <key>CFBundleVersion</key>             <string>1.0</string>
  <key>CFBundleShortVersionString</key>  <string>1.0</string>
  <key>NSHighResolutionCapable</key>     <true/>
  <key>LSRequiresNativeExecution</key>   <true/>
  <key>LSArchitecturePriority</key>
  <array><string>arm64</string><string>x86_64</string></array>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Para ler os scripts do projeto tr8s-grid.</string>
  <key>NSDesktopFolderUsageDescription</key>
  <string>Para ler os scripts do projeto tr8s-grid.</string>
</dict>
</plist>
"""

LANCADOR = """#!/bin/sh
# Gerado pelo criar_app.py. Roda a copia que mora dentro do proprio bundle -
# ver o comentario sobre TCC no topo do criar_app.py.
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
LOG="$HOME/Library/Logs/tr8s-grid.log"

# O Finder lanca app baseado em script como x86_64. O /usr/bin/python3 e
# universal e obedece calado, mas o rtmidi instalado e arm64 e nao carrega sob
# Rosetta - "have arm64, need x86_64". Do Terminal isso nunca aparece, porque la
# o shell ja e nativo. Forca o arch nativo quando a maquina e Apple Silicon.
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
    exec /usr/bin/arch -arm64 /usr/bin/python3 "$DIR/gui.py" >>"$LOG" 2>&1
fi
exec /usr/bin/python3 "$DIR/gui.py" >>"$LOG" 2>&1
"""


def criar(pasta):
    destino = os.path.join(pasta, NOME + ".app")
    # Monta e assina num diretorio temporario, e so entao move. O Desktop e
    # sincronizado pelo iCloud, que re-carimba xattrs a qualquer momento: assinar
    # la vira corrida perdida ("resource fork, Finder information ... not allowed").
    tmp = tempfile.mkdtemp(prefix="tr8s-app-")
    app = os.path.join(tmp, NOME + ".app")
    if os.path.exists(destino):
        # a marca ja morou na raiz do bundle; aceita as duas pra nao travar
        # em cima de um app que este mesmo script criou antes
        nosso = any(os.path.exists(os.path.join(destino, m))
                    for m in (MARCA, ".tr8s-grid-app"))
        if not nosso:
            print(f"(!) Ja existe um {destino} que nao foi criado por este "
                  f"script.\n    Nao vou mexer nele. Apague ou renomeie a mao "
                  f"primeiro.")
            shutil.rmtree(tmp, ignore_errors=True)
            return 1

    exe = "tr8s-grid"
    macos = os.path.join(app, "Contents", "MacOS")
    recursos = os.path.join(app, "Contents", "Resources")
    os.makedirs(macos); os.makedirs(recursos)

    with open(os.path.join(app, "Contents", "Info.plist"), "w") as f:
        f.write(PLIST.format(nome=NOME, ident=IDENT, exe=exe))

    lancador = os.path.join(macos, exe)
    with open(lancador, "w") as f:
        f.write(LANCADOR)
    os.chmod(lancador, 0o755)

    for nome in ARQUIVOS:
        origem = os.path.join(AQUI, nome)
        if not os.path.exists(origem):
            print(f"(!) {nome} nao encontrado em {AQUI} - o app vai faltar peca.")
            continue
        shutil.copy2(origem, os.path.join(recursos, nome))

    open(os.path.join(app, MARCA), "w").close()

    try:
        montar_icns(os.path.join(recursos, "icone.icns"))
        icone = "com icone"
    except Exception as e:
        icone = f"sem icone ({e})"

    # assinatura ad-hoc: da ao bundle uma identidade estavel, sem a qual o
    # macOS nega acessos em silencio em vez de perguntar. Tem que vir DEPOIS de
    # copiar os arquivos, senao a assinatura ja nasce quebrada.
    # o iCloud carimba xattrs no Desktop e o codesign recusa bundle com
    # "resource fork, Finder information, or similar detritus"
    subprocess.run(["xattr", "-cr", app], check=False)
    r = subprocess.run(["codesign", "--force", "--deep", "--sign", "-", app],
                       capture_output=True, text=True)
    assinado = "assinado" if r.returncode == 0 else f"sem assinatura ({r.stderr.strip()[:60]})"

    if os.path.exists(destino):
        shutil.rmtree(destino)
    shutil.move(app, destino)
    shutil.rmtree(tmp, ignore_errors=True)
    app = destino

    # o Finder as vezes segura o icone antigo em cache
    subprocess.run(["touch", app], check=False)

    print(f"Criado: {app}")
    print(f"  {icone} · {assinado} · {len(ARQUIVOS)} scripts embutidos")
    print("Duplo-clique pra abrir.")
    print("ATENCAO: o app roda a COPIA que esta dentro dele. Depois de editar o")
    print("gui.py ou o lp_tr8s.py, rode este script de novo pra atualizar.")
    print("Se ele nao abrir, o motivo aparece em ~/Library/Logs/tr8s-grid.log")
    return 0


if __name__ == "__main__":
    pasta = os.path.expanduser("~/Desktop")
    if "--em" in sys.argv:
        pasta = os.path.abspath(sys.argv[sys.argv.index("--em") + 1])
    sys.exit(criar(pasta))
