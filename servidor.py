#!/usr/bin/env python3
"""
servidor.py - a janela do TR-8S Grid, agora como pagina web local.

POR QUE SAIU DO TKINTER (15/08/2026)

O Python 3.9 do Command Line Tools traz Tk 8.5.9 - build de 2010, o Aqua
legado que a Apple abandonou. Com a janela nova (abas, faders, listas) ele
entrava em tempestade de redesenho no macOS 26: medidos 4313 eventos Expose em
2,5 s contra ~40 de uma janela comum, com a janela em branco e o processo
passando de 600 MB. Nao era o layout - a janela pedia 796x633 numa area de
820x680, cabia folgado. Widgets isolados (Canvas, Notebook, 11 Scales, Labels
com wraplength) davam 17-97 Expose; so a janela inteira explodia. E ferramenta,
nao codigo.

O QUE ESTA PAGINA MUDA E O QUE NAO MUDA

Muda so a camada de tela. O Motor, o SysEx, os Launchpads e a fila de comandos
sao os mesmos - a pagina fala com o Motor pelas MESMAS chamadas que a janela
Tk fazia (motor.enfileirar). Zero dependencia nova: http.server da stdlib.

Servidor so em 127.0.0.1 - a pagina nao sai desta maquina.

Uso:
    python3 servidor.py            abre o navegador na pagina
    python3 servidor.py --sem-abrir
"""
import http.server
import json
import mimetypes
import os
import posixpath
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_tr8s as L
import biblioteca as B
import ferramentas as F
import tones as T
import efeitos as E

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, "web")
PORTA = 8733
LOG_PATH = os.path.expanduser("~/Library/Logs/TR8S-Grid-app.log")
ARQ_SERVIDOR = os.path.expanduser("~/.lp_tr8s_servidor.json")

# O Python 3.9 nao conhece .mjs: sem isto o navegador RECUSA o modulo ES com
# "disallowed MIME type" e a pagina nao carrega nada.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/manifest+json", ".webmanifest")

# Token da sessao. Sem ele, qualquer pagina aberta no navegador poderia mandar
# POST em 127.0.0.1:8733/acao e disparar um WRITE na TR-8S - o servidor e local,
# mas nao e privado. Ver _autorizado().
TOKEN = secrets.token_urlsafe(24)

# manifest-src e obrigatorio para o "Adicionar a Dock" do Safari: com
# default-src 'none' o navegador recusa o .webmanifest calado, e o app da
# Dock nasce sem nome nem icone.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data:; connect-src 'self'; manifest-src 'self'; "
       "base-uri 'none'; form-action 'none'")
LIMITE_CORPO = 256 * 1024


class Log:
    """Log em arquivo + as ultimas linhas para a pagina mostrar."""

    def __init__(self, caminho=LOG_PATH, memoria=60):
        self.caminho, self.memoria = caminho, memoria
        self.linhas = []
        self.lock = threading.Lock()
        try:
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            if os.path.exists(caminho) and os.path.getsize(caminho) > 1_000_000:
                os.replace(caminho, caminho + ".old")
            self.f = open(caminho, "a", encoding="utf-8")
        except OSError:
            self.f = None

    def __call__(self, texto):
        texto = str(texto)
        with self.lock:
            self.linhas.append(time.strftime("%H:%M:%S ") + texto)
            del self.linhas[:-self.memoria]
        if self.f:
            try:
                self.f.write(time.strftime("%H:%M:%S  ") + texto + "\n")
                self.f.flush()
            except OSError:
                pass

    def ultimas(self, n=25):
        with self.lock:
            return list(self.linhas[-n:])


class Host:
    """Dono do Motor: sobe a thread, atende as acoes, devolve o estado.

    Mesmo contrato da janela antiga: a UI so chama enfileirar()/definir_modo()
    e le estado(bloquear=False), que devolve None se o motor estiver ocupado."""

    def __init__(self):
        self.log = Log()
        self.motor = None
        self.thread = None
        self.rodando = False
        self.estocastica = F.Estocastica()
        self.ultimo_estado = {}
        # ja avisei que nao consigo enumerar portas MIDI? (o estado roda 4x/s -
        # sem esta memoria o log viraria a mesma linha para sempre)
        self._midi_mudo = False

    # ── motor ───────────────────────────────────────────────
    def garantir_motor(self):
        if self.motor:
            return True
        # a resolucao mora em lp_tr8s (carregar_layout_resolvido): antes esta
        # regra estava copiada aqui, no gui.py e no lp_tr8s.py, e as tres
        # comparavam a lista INTEIRA de portas - por isso desligar a interface
        # de audio derrubava o app inteiro
        cfg, msgs = L.carregar_layout_resolvido()
        for m in msgs:
            self.log(("(!) " if cfg is None else "") + m)
        if cfg is None:
            return False
        try:
            L._programmer_mode(True)
            self.motor = L.Motor(cfg, log=self.log)
        except Exception as e:
            self.log(f"(!) nao consegui abrir os Launchpad: {e}")
            return False
        self.rodando = True
        self.thread = threading.Thread(target=self._laco, daemon=True)
        self.thread.start()
        return True

    def _laco(self):
        while self.rodando:
            try:
                self.motor.tick()
            except Exception as e:
                self.log(f"(!) erro no motor: {e}")
                time.sleep(0.5)
            time.sleep(0.003)

    def parar_motor(self):
        if not self.motor:
            return
        self.rodando = False
        if self.thread:
            self.thread.join(timeout=1.0)
        try:
            self.motor.fechar()
        except Exception:
            pass
        self.motor, self.thread, self.ultimo_estado = None, None, {}

    def enfileirar(self, fn, *args):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro")
            return
        self.motor.enfileirar(fn, *args)

    # ── estado para a pagina ────────────────────────────────
    def estado(self):
        e, fresco = {}, True
        if self.motor:
            try:
                novo = self.motor.estado()
            except Exception:
                novo = None
            fresco = novo is not None
            e = novo if fresco else dict(self.ultimo_estado)
            self.ultimo_estado = e
        e = dict(e)
        # o estado do motor tem set (nao vira JSON) e o resto e primitivo
        e["cache_invalido"] = sorted(e.get("cache_invalido", []) or [])
        e["ligado"] = self.motor is not None
        e["log"] = self.log.ultimas()
        # o motor devolve None quando esta ocupado (lendo a maquina): o quadro
        # e reaproveitado. Sem dizer isso, a tela mostraria dado velho como se
        # fosse novo - justamente no momento em que mais importa
        e["fresco"] = bool(fresco)
        if not self.motor:
            # Enumerar portas fala com o subsistema de MIDI do sistema
            # operativo, e ele pode nao existir (o CI do GitHub roda sem ALSA)
            # ou engasgar (CoreMIDI reiniciando). Sem este guarda a excecao
            # subia pelo handler, a conexao caia SEM RESPOSTA e a pagina
            # inteira mostrava "sem contato com o servidor" - o pior sintoma
            # possivel para o problema mais bobo. Achado pelo CI em 17/08/2026,
            # no primeiro dia dele.
            try:
                nomes = [n.upper() for _, n in L.listar_portas(True)]
            except Exception as exc:
                if not self._midi_mudo:
                    self._midi_mudo = True
                    self.log(f"(!) nao consigo enumerar portas MIDI: {exc}. "
                             "A tela vai dizer que nao ve aparelho nenhum - e "
                             "e a verdade, do ponto de vista daqui")
                nomes = []
            else:
                self._midi_mudo = False
            e["tem_tr8s"] = any(L.TR8S_MATCH.upper() in n for n in nomes)
            e["tem_clock"] = any("TR-8S" in n and L.TR8S_MATCH.upper() not in n
                                 for n in nomes)
            e["tem_lp"] = sum(1 for n in nomes
                              if L.LP_MATCH.upper() in n) >= 2
            e["mapa_fx"] = E.carregar()
        else:
            e["tem_lp"] = True
        return e


HOST = Host()


# ─────────────────────────────────────────────────────────────
# Acoes: tudo que a pagina pode pedir. Lista fechada de proposito -
# a pagina nao chama metodo arbitrario do Motor.
# ─────────────────────────────────────────────────────────────
def _acao_modo(a):
    if a.get("modo") == L.MODO_ON and not HOST.garantir_motor():
        return
    if not HOST.motor and not HOST.garantir_motor():
        return
    HOST.enfileirar(HOST.motor.definir_modo, a["modo"], a.get("estilo"))


def _acao_biblioteca(a):
    pat = next((p for p in B.PATTERNS if p["id"] == a["id"]), None)
    if not pat:
        HOST.log(f"(!) pattern '{a.get('id')}' nao existe")
        return
    HOST.enfileirar(HOST.motor.escrever_pattern, B.expandir(pat),
                    pat.get("accent", 0), pat.get("last_var", 16), pat["nome"])


def _acao_chain_armar(a):
    modo = a.get("modo", "misto")
    entradas = []
    for it in a.get("entradas", []):
        reps = max(1, int(it.get("reps", 1)))
        if modo == "misto":
            # a fila da tela: cada item diz o tipo
            if it.get("tipo") == "groove":
                pat = next((p for p in B.PATTERNS if p["id"] == it["id"]),
                           None)
                if not pat:
                    continue
                entradas.append({"tipo": "groove", "nome": pat["nome"],
                                 "dados": B.expandir(pat),
                                 "accent": pat.get("accent", 0),
                                 "reps": reps})
            elif it.get("tipo") == "pattern":
                n = int(it["alvo"]) & 0x7F
                entradas.append({"tipo": "pattern", "alvo": n,
                                 "nome": L.nome_pattern(n),
                                 "reps": reps})
        elif modo == "reescrita":
            pat = next((p for p in B.PATTERNS if p["id"] == it["alvo"]), None)
            if not pat:
                continue
            entradas.append({"nome": pat["nome"], "dados": B.expandir(pat),
                             "accent": pat.get("accent", 0), "reps": reps})
        elif modo == "variacao":
            entradas.append({"var": int(it["alvo"]), "reps": reps})
        else:
            entradas.append({"alvo": int(it["alvo"]), "reps": reps})
    if not entradas:
        HOST.log("(!) chain vazio")
        return

    # a variacao vem da tela; None = o Chain resolve sozinho (a que toca, a
    # aberta, a primeira habilitada - nessa ordem)
    var = a.get("var")
    var = int(var) if var else None
    # 1-8 e' o alcance da mascara de variacao; 9/10 sao os Fill In e o resto
    # nao existe. Sem esta validacao um var fora da faixa estourava IndexError
    # DENTRO do armar, antes da linha que anula HOST.motor.chain: sobrava um
    # Chain meio construido e todo estado() seguinte morria no resumo() dele -
    # a pagina congelava em "fresco: false" para sempre (revisao do PR #9)
    if var is not None and not 1 <= var <= 8:
        HOST.log(f"(!) variacao {var} nao serve para travar o loop (so A-H)")
        return

    def armar():
        HOST.motor.chain = F.Chain(entradas, modo, log=HOST.log, var=var)
        HOST.motor.chain.armar(HOST.motor)
        if not HOST.motor.chain.ativo:
            HOST.motor.chain = None
    HOST.enfileirar(armar)


def _acao_estocastica(a):
    seed = a.get("seed")
    HOST.estocastica.definir_seed(seed)
    op, v = a["op"], a.get("valor", 0)
    m = HOST.motor
    if not m:
        HOST.log("(!) ligue o modo ON primeiro")
        return
    # insts: None = todos; lista de indices 0-10 restringe (reforma 2)
    insts = a.get("insts")
    if insts is not None:
        insts = [i for i in map(int, insts) if 0 <= i < len(L.INSTRUMENTOS)]
        if not insts:
            insts = None
    tabela = {
        "densidade": lambda: HOST.estocastica.densidade(m, float(v), insts),
        "humanize": lambda: HOST.estocastica.humanize_vel(m, int(v), insts),
        "retrig": lambda: HOST.estocastica.retrig(m, int(v), insts=insts),
        "ghosts": lambda: HOST.estocastica.gerar_ghosts(m, int(v), insts),
        "reverter": lambda: HOST.estocastica.reverter(m),
    }
    if op in tabela:
        HOST.enfileirar(tabela[op])


def _acao_util(a):
    m = HOST.motor
    if not m:
        HOST.log("(!) ligue o modo ON primeiro")
        return
    tabela = {"playing": m.util_esta_tocando, "versao": m.util_versao,
              "write": m.util_write_pattern}
    if a["op"] == "visor":
        HOST.enfileirar(m.util_escrever_visor, a.get("texto", ""))
    elif a["op"] in tabela:
        HOST.enfileirar(tabela[a["op"]])


def _acao_externa(a):
    """Recalibrar, reiniciar e blackout saem para fora do processo, como antes."""
    HOST.parar_motor()
    if a["op"] == "recalibrar":
        script = os.path.join(AQUI, "lp_tr8s.py")
        HOST.log("Abrindo o Terminal pro 'learn' (ele faz perguntas).")
        subprocess.Popen(["osascript", "-e",
                          f'tell app "Terminal" to do script '
                          f'"python3 \\"{script}\\" learn"',
                          "-e", 'tell app "Terminal" to activate'])
    elif a["op"] == "reiniciar":
        # o cliente MIDI do rtmidi/CoreMIDI deste processo pode ficar preso
        # vendo um conjunto de portas Launchpad que nao existe mais depois de
        # um replug USB - mesmo listar_portas() abrindo um MidiIn novo a cada
        # chamada, o processo continua recusando com "o conjunto de Launchpad
        # mudou" mesmo com o hardware de volta (18/08/2026). Um processo NOVO
        # sempre ve o estado certo. O LaunchAgent tem KeepAlive, entao sair
        # do processo basta - ele volta sozinho com o cliente MIDI do zero
        HOST.log("Reiniciando o servidor (o processo volta sozinho em "
                 "seguida) para refazer a leitura das portas MIDI...")
        threading.Thread(target=_encerrar, daemon=True).start()
    else:
        subprocess.Popen([sys.executable, os.path.join(AQUI, "apagar_luzes.py")])
        HOST.log("LEDs apagados e pads soltos.")


# Motor.executar ja e um dispatcher completo (variacao, velocidade, modo,
# rolar, acc, limpar_inst, limpar_var, copiar, colar, oculto, alt). Expor com
# WHITELIST libera a barra de ferramentas inteira sem metodo novo - mas a lista
# e fechada de proposito: a pagina nao chama metodo arbitrario do Motor.
EXEC_OK = {"variacao", "velocidade", "modo", "rolar", "acc", "limpar_inst",
           "limpar_var", "copiar", "colar", "oculto", "alt"}


def _acao_exec(a):
    tipo = a.get("tipo")
    if tipo not in EXEC_OK:
        raise ValueError(f"exec '{tipo}' nao permitido")
    HOST.enfileirar(HOST.motor.executar, tipo, a.get("arg"))


ACOES = {
    "modo": _acao_modo,
    "exec": _acao_exec,
    # duplo clique na variacao: pede que ela TOQUE (o clique simples so a abre
    # no grid pra editar). Ver Motor.pedir_variacao - a escrita da mascara
    # 63-66 foi PROVADA em hardware em 16/08/2026 (tres trocas obedecidas)
    "tocar_variacao": lambda a: HOST.enfileirar(HOST.motor.pedir_variacao,
                                                int(a["var"])),
    # Alt-clique: liga/desliga a variacao no RODIZIO, sem zerar as outras -
    # o caminho de volta depois de um duplo clique, que deixa uma so
    "ciclo_variacao": lambda a: HOST.enfileirar(HOST.motor.alternar_no_ciclo,
                                                int(a["var"])),
    # quantas linhas o INST UP/DOWN anda por toque (vale pros Launchpad tambem)
    "passo_inst": lambda a: HOST.enfileirar(HOST.motor.definir_passo_inst,
                                            int(a["valor"])),
    # o Luan diz qual variacao o visor mostra; sem isso, quem sobe o app com a
    # maquina ja rodando fica em "?" (nao ha start pra ancorar a conta)
    "ancorar_variacao": lambda a: HOST.enfileirar(HOST.motor.ancorar_variacao,
                                                  int(a["var"])),
    "editor_toggle": lambda a: HOST.enfileirar(
        HOST.motor.alternar_editor, int(a["inst"]), int(a["step"]),
        bool(a.get("fraco"))),
    "step_set": lambda a: HOST.enfileirar(
        HOST.motor.definir_step, int(a["inst"]), int(a["step"]),
        int(a["vel"]), int(a.get("sub", 0)), bool(a.get("alt")),
        None if a.get("prob") is None else int(a["prob"])),
    "last_track": lambda a: HOST.enfileirar(
        HOST.motor.definir_last_track, int(a["inst"]),
        None if a.get("valor") is None else int(a["valor"])),
    "esquecer_fx": lambda a: HOST.enfileirar(HOST.motor.esquecer_fx, a["nome"]),
    "reler": lambda a: HOST.enfileirar(HOST.motor.recarregar),
    # botao de reset do volume do kit (pedido de 17/08/2026): devolve o valor
    # de quando o kit foi LIDO, que e o unico "original" que temos como saber
    "reset_kit_level": lambda a: HOST.enfileirar(HOST.motor.resetar_kit_level),
    "prob_inst": lambda a: HOST.enfileirar(HOST.motor.definir_prob_inst,
                                           int(a["inst"]), int(a["pct"])),
    # toggle do mute de UM instrumento (botao da mesa). Escrita da mascara
    # provada em hardware (REFERENCIA 2.7); o toggle mora no Motor para
    # reler a mascara fresca antes de inverter (corrida com o painel).
    "mudo": lambda a: HOST.enfileirar(HOST.motor.alternar_mudo,
                                      int(a["inst"])),
    "prob_step": lambda a: HOST.enfileirar(HOST.motor.definir_prob,
                                           int(a["inst"]), int(a["step"]),
                                           int(a["pct"])),
    "fx": lambda a: HOST.enfileirar(HOST.motor.definir_fx, a["nome"],
                                    int(a["valor"]),
                                    None if a.get("inst") is None
                                    else int(a["inst"])),
    "capturar": lambda a: HOST.enfileirar(HOST.motor.iniciar_captura_fx,
                                          a["nome"]),
    "cancelar_captura": lambda a: HOST.enfileirar(
        HOST.motor.cancelar_captura_fx),
    "anotar_opcao": lambda a: HOST.enfileirar(
        HOST.motor.anotar_opcao, a["nome"], a["rotulo"],
        None if a.get("inst") is None else int(a["inst"])),
    "ler_fx": lambda a: HOST.enfileirar(HOST.motor.ler_fx),
    "ler_kit": lambda a: HOST.enfileirar(HOST.motor.ler_kit),
    "tone": lambda a: HOST.enfileirar(HOST.motor.definir_tone,
                                      int(a["inst"]), int(a["tone_id"])),
    "biblioteca": _acao_biblioteca,
    "desfazer": lambda a: HOST.enfileirar(HOST.motor.desfazer_escrita),
    "desfazer_tudo": lambda a: HOST.enfileirar(HOST.motor.desfazer_tudo),
    # troca remota provada em 15/08/2026: agora=False troca na virada,
    # agora=True corta no meio preservando o step
    "pattern": lambda a: HOST.enfileirar(HOST.motor.definir_pattern,
                                         int(a["n"]), bool(a.get("agora"))),
    # HIPOTESE ate o primeiro teste com o visor (ver definir_kit)
    "kit": lambda a: HOST.enfileirar(HOST.motor.definir_kit, int(a["n"])),
    # tempo x 10 em 3 nibbles (OFF_TEMPO, achado no tempo_watch de 16/08)
    "bpm": lambda a: HOST.enfileirar(HOST.motor.definir_bpm,
                                     float(a["valor"])),
    "chain_armar": _acao_chain_armar,
    # passa o motor: parar o loop SOLTA a trava da variacao (sem restaurar o
    # rodizio, que e decisao de quem esta ouvindo - ver destravar_variacao)
    "chain_parar": lambda a: (HOST.motor and HOST.motor.chain
                              and HOST.enfileirar(HOST.motor.chain.parar,
                                                  HOST.motor)),
    # o rodizio de variacoes que a trava desligou, de volta. Botao proprio na
    # aba Grooves: reescrever essa mascara com a musica tocando derruba a
    # ancora do ciclo, entao quem decide o momento e o operador
    "restaurar_rodizio": lambda a: HOST.enfileirar(
        HOST.motor.destravar_variacao, True),
    "estocastica": _acao_estocastica,
    "util": _acao_util,
    "externa": _acao_externa,
    "last_var": lambda a: HOST.enfileirar(HOST.motor.definir_last_var,
                                          int(a["valor"])),
}


def dados_estaticos():
    """O que a pagina precisa uma vez so: catalogos e listas."""
    return {
        "instrumentos": L.INSTRUMENTOS,
        "variacoes": L.VARIACOES,
        "velocidades": L.VELOCIDADES,
        "modos_step": [m[0] for m in L.MODOS],
        "biblioteca": [{"id": p["id"], "nome": p["nome"], "estilo": p["estilo"],
                        "bpm": p["bpm"], "kit": p["kit"],
                        "kit_num": p.get("kit_num"), "obs": p.get("obs"),
                        "last_var": p.get("last_var", 16),
                        "accent": p.get("accent", 0),
                        "grade": {L.INSTRUMENTOS[i]: [
                            {"v": v, "s": s, "p": pr, "a": al}
                            for v, s, pr, al in linha]
                            for i, linha in B.expandir(p).items()}}
                       for p in B.PATTERNS],
        "catalogo_fx": E.CATALOGO,
        "paineis_fx": E.paineis_para_tela(),
        # o id vem NA tupla: os ids da Roland tem buracos, e supor
        # "id = posicao" foi o que carregou o tone errado em 15/08/2026
        "tones": [{"id": i, "cat": c, "nome": n, "tipo": t, "maquina": m}
                  for i, c, n, t, m in T.TONES],
        # as cores saem do Python para a tela e o LED nunca divergirem
        "cores": L.paleta_da_tela(),
        "build": time.strftime("%d/%m %H:%M", time.localtime(
            os.path.getmtime(os.path.abspath(__file__)))),
    }


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tr8s-grid"
    sys_version = ""

    def log_message(self, *a):
        pass                      # o log do servidor e ruido; o nosso e outro

    # ── seguranca ───────────────────────────────────────────
    def _host_ok(self):
        """Host tem que ser o nosso - fecha DNS rebinding (um dominio que
        resolve para 127.0.0.1 e passaria pela checagem de Origin)."""
        h = (self.headers.get("Host") or "").lower()
        return h in (f"127.0.0.1:{self.server.server_port}",
                     f"localhost:{self.server.server_port}")

    def _origem_ok(self):
        o = self.headers.get("Origin")
        if o is None:
            return True           # navegacao normal nao manda Origin
        return o.lower() in (f"http://127.0.0.1:{self.server.server_port}",
                             f"http://localhost:{self.server.server_port}")

    def _tem_cookie(self):
        bruto = self.headers.get("Cookie") or ""
        for parte in bruto.split(";"):
            nome, _, valor = parte.strip().partition("=")
            if nome == "tr8s" and secrets.compare_digest(valor, TOKEN):
                return True
        return False

    def _autorizado_post(self):
        """POST exige o header proprio: um <form> de outro site nao consegue
        emitir header custom, e um fetch cross-site dispara preflight, que
        recusamos. O cookie e SameSite=Strict, entao nem viaja de fora.

        Devolve (ok, motivo). O motivo importa: o TOKEN e sorteado a cada boot
        do servidor, entao uma pagina que ficou aberta enquanto o servidor
        reiniciou manda o token velho - e dizer "origem nao autorizada" ali
        mandava procurar o problema no lugar errado (aconteceu em 16/08/2026).
        Nao vaza nada: quem chega aqui ja esta em 127.0.0.1."""
        if not self._host_ok():
            return False, "host nao autorizado"
        if not self._origem_ok():
            return False, "origem nao autorizada"
        t = self.headers.get("X-TR8S-Token") or ""
        if not secrets.compare_digest(t, TOKEN):
            return False, ("sessao vencida - o servidor reiniciou desde que "
                           "esta pagina abriu. Recarregue (Cmd+R)")
        return True, ""

    def _responder(self, corpo, tipo="application/json; charset=utf-8",
                   codigo=200, extra=None):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, msg, codigo=400):
        self._responder(json.dumps({"erro": msg}), codigo=codigo)

    # ── GET ─────────────────────────────────────────────────
    def _servir_pagina(self):
        """Serve a pagina e ENTREGA A SESSAO a quem abriu esta URL.

        Antes o cookie so vinha com ?t=<token> na query - o jeito como o .app
        abre o navegador. Isso trancava dois casos legitimos: abrir a pagina
        noutro navegador, e o app de "Adicionar a Dock" do Safari, que guarda
        uma URL fixa enquanto o token muda a cada vez que o servidor sobe.

        Por que dar a sessao a qualquer um que peca / e seguro: o servidor so
        escuta em 127.0.0.1, entao quem chega aqui ja esta nesta maquina; uma
        pagina de outro site consegue ate NAVEGAR para ca, mas nao consegue
        LER a resposta (cross-origin) nem alcancar o cookie (HttpOnly), e
        SameSite=Strict impede o cookie de viajar numa requisicao dela. A
        defesa do POST continua sendo Host + Origin + header proprio, que e
        onde ela sempre esteve. O _host_ok() aqui fecha DNS rebinding, que e
        o unico jeito de um site externo virar "mesma origem" que nos."""
        extra = {"Content-Security-Policy": CSP}
        if self._host_ok():
            extra["Set-Cookie"] = (f"tr8s={TOKEN}; Path=/; SameSite=Strict; "
                                   "HttpOnly; Max-Age=86400")
        alvo = os.path.join(WEB, "index.html")
        if not os.path.exists(alvo):
            alvo = os.path.join(AQUI, "pagina.html")   # ate a Fase 1 chegar
        try:
            with open(alvo, "rb") as f:
                return self._responder(f.read(), "text/html; charset=utf-8",
                                       extra=extra)
        except OSError:
            return self._responder("pagina nao encontrada", "text/plain", 500)

    def _servir_estatico(self, rota):
        rel = posixpath.normpath(urllib.parse.unquote(rota[len("/web/"):]))
        if rel.startswith(("..", "/")):
            return self._erro("caminho invalido", 403)
        alvo = os.path.realpath(os.path.join(WEB, rel))
        # realpath + commonpath fecha symlink e ../ de uma vez
        if os.path.commonpath([alvo, os.path.realpath(WEB)]) != \
                os.path.realpath(WEB):
            return self._erro("fora do diretorio web", 403)
        if os.path.splitext(alvo)[1] not in (".css", ".mjs", ".js", ".svg",
                                             ".png", ".woff2", ".html",
                                             ".webmanifest"):
            return self._erro("extensao nao servida", 403)
        try:
            with open(alvo, "rb") as f:
                dados = f.read()
        except OSError:
            return self._erro("nao encontrado", 404)
        tipo = mimetypes.guess_type(alvo)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        return self._responder(dados, tipo)

    def do_GET(self):
        if not self._host_ok():
            return self._erro("host nao autorizado", 403)
        rota = urllib.parse.urlparse(self.path).path
        if rota in ("/", "/index.html"):
            return self._servir_pagina()
        if rota == "/ping":
            # e assim que a segunda instancia sabe que quem esta na porta somos
            # nos, em vez de supor (o que o _porta_livre antigo fazia)
            return self._responder(json.dumps(
                {"app": "tr8s-grid", "pid": os.getpid()}))
        if rota.startswith("/web/"):
            return self._servir_estatico(rota)
        if rota == "/token":
            # so a nossa pagina consegue: o cookie e SameSite=Strict e a
            # resposta nao tem CORS, entao outro site nao le o corpo
            if not self._tem_cookie():
                return self._erro("sem cookie de sessao", 403)
            return self._responder(json.dumps({"token": TOKEN}))
        if rota == "/estado":
            return self._responder(json.dumps(HOST.estado(), default=str))
        if rota == "/dados":
            return self._responder(json.dumps(dados_estaticos(), default=str))
        return self._erro("nao encontrado", 404)

    def do_OPTIONS(self):
        # sem nenhum Access-Control-Allow-*: preflight de outro site morre aqui
        self._responder(b"", "text/plain", 204)

    # ── POST ────────────────────────────────────────────────
    def do_POST(self):
        ok, motivo = self._autorizado_post()
        if not ok:
            HOST.log(f"(!) POST recusado em {self.path}: {motivo}")
            return self._erro(motivo, 403)
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._erro("tamanho invalido")
        if n > LIMITE_CORPO:
            return self._erro("corpo grande demais", 413)
        try:
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._erro("json invalido")
        if not isinstance(corpo, dict):
            return self._erro("json invalido")
        if self.path == "/sair":
            self._responder(json.dumps({"ok": True}))
            threading.Thread(target=_encerrar, daemon=True).start()
            return
        if self.path != "/acao":
            return self._erro("nao encontrado", 404)
        nome = corpo.get("acao")
        fn = ACOES.get(nome)
        if not fn:
            return self._erro(f"acao desconhecida: {nome}")
        # acao que precisa do motor sem motor: devolve erro DE VERDADE, para a
        # tela poder avisar - antes isso virava so uma linha de log
        if nome not in ("modo", "externa") and not HOST.motor:
            HOST.log("(!) ligue o modo ON primeiro")
            return self._erro("motor desligado - ligue o modo ON", 409)
        try:
            fn(corpo)
        except Exception as e:
            HOST.log(f"(!) acao '{nome}' falhou: {e}")
            return self._erro(f"{nome}: {e}", 500)
        return self._responder(json.dumps({"ok": True}))


def _encerrar():
    time.sleep(0.3)
    HOST.parar_motor()
    try:
        os.remove(ARQ_SERVIDOR)
    except OSError:
        pass
    os._exit(0)


def _instancia_viva():
    """Se JA existe um TR-8S Grid rodando, devolve a URL dele (com token).

    Antes isto era um chute: qualquer coisa escutando na porta era tratada
    como 'sou eu mesmo'. Agora o processo deixa um bilhete em ~/ e a segunda
    instancia confirma pelo /ping - se for outro programa na porta, seguimos
    para a proxima porta em vez de abrir o navegador na cara dele."""
    try:
        with open(ARQ_SERVIDOR) as f:
            info = json.load(f)
        porta, token = int(info["porta"]), info["token"]
    except (OSError, ValueError, KeyError):
        return None
    try:
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{porta}/ping", timeout=1.0) as r:
            if json.loads(r.read()).get("app") != "tr8s-grid":
                return None
    except Exception:
        return None
    return f"http://127.0.0.1:{porta}/?t={urllib.parse.quote(token)}"


def _porta_livre(base=PORTA):
    for p in range(base, base + 12):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return None


def _anotar_instancia(porta):
    try:
        with open(ARQ_SERVIDOR, "w") as f:
            json.dump({"porta": porta, "token": TOKEN, "pid": os.getpid()}, f)
        os.chmod(ARQ_SERVIDOR, 0o600)      # o token nao e de todo mundo
    except OSError:
        pass


def main():
    ja = _instancia_viva()
    if ja:
        # o macOS ativa o app ja aberto em vez de subir outro: em vez de uma
        # segunda instancia brigando pela porta CTRL, so traz a pagina de volta
        print(f"O TR-8S Grid ja esta rodando - abrindo a pagina.")
        webbrowser.open(ja)
        return
    porta = _porta_livre()
    if porta is None:
        print("Nenhuma porta livre entre "
              f"{PORTA} e {PORTA + 11}. Feche o que estiver usando.")
        return
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    _anotar_instancia(porta)
    url = f"http://127.0.0.1:{porta}/?t={urllib.parse.quote(TOKEN)}"
    HOST.log(f"servidor no ar em http://127.0.0.1:{porta}/")
    print(f"TR-8S Grid em {url}   (Ctrl+C encerra)")
    if "--sem-abrir" not in sys.argv:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nsaindo...")
    finally:
        HOST.parar_motor()
        try:
            os.remove(ARQ_SERVIDOR)
        except OSError:
            pass


if __name__ == "__main__":
    main()
