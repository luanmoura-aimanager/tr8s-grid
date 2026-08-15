#!/usr/bin/env python3
"""
gui.py - janela do TR-8S Grid.

Reescrita de 14/08/2026. A versao anterior quebrava no Tk 8.5.9 Aqua (o do
Python 3.9 do CLT, que e o que o .app usa): tk.Button e tk.Checkbutton ignoram
bg/fg/bd ali, entao os botoes de modo nunca mostravam o modo ativo e os
checkboxes de mute transbordavam por cima dos vizinhos. As regras desta versao:

  - tudo que precisa de COR e desenhado em tk.Canvas (o Aqua respeita Canvas -
    os LEDs de status ja provavam isso); o que e neutro fica em ttk com o clam
  - janela de tamanho FIXO, sem geometry("") - o relayout dinamico era a fonte
    de ghosting no Tk 8.5
  - abas (ttk.Notebook) no lugar das secoes que abriam e fechavam
  - a UI NAO chama metodos do Motor: poe na fila dele (motor.enfileirar) e o
    tick() executa com o lock, na thread do motor. A janela le estado() a
    20 fps sem bloquear - se o motor estiver ocupado, pula o quadro
  - log vai para ~/Library/Logs/TR8S-Grid.log; a ultima linha aparece no rodape

Tres modos, exclusivos entre si:
    ON        o grid escreve na TR-8S (precisa da porta CTRL)
    off       LEDs apagados; os pads so fazem ondinha
    standby   ondas coloridas nascendo sozinhas ('standby' = chuva, 'ambiente'
              = lento e fraco)
"""
import os, sys, time, json, threading, queue, subprocess
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_tr8s as L
import biblioteca as B
import ferramentas as F
import tones as T
import efeitos as E

BG, CARD, INK, MUTED, LINHA = "#141210", "#1e1b18", "#ece8e2", "#9a938a", "#33302c"
VERDE, VERMELHO, AMARELO, ROXO = "#4ade80", "#f87171", "#fbbf24", "#a855f7"
CINZA_MODO = "#6b7280"

# celulas do editor: mesma paleta do launchpad, que espelha o painel da TR-8S
COR_CEL_FORA   = "#101010"     # step alem do last step
COR_CEL_VAZIA  = "#26221e"     # step desligado (com contraste real sobre BG)
COR_CEL_MUDA   = "#38445c"     # linha mutada na maquina
COR_CEL_ALT    = "#ff3450"     # ALTERNATE (rosa)
COR_CEL_FLAM   = "#a43afe"     # flam (lilas)
COR_CEL_SUB    = "#ffe000"     # sub step (amarelo)
COR_CEL_NOTA   = "#ff3b30"     # nota (vermelho)
COR_CEL_ACC    = "#ffe600"
COR_CEL_ALERTA = "#4a2020"     # linha com cache invalido (leitura falhou)

# NAO chamar de TR8S-Grid.log: o disco do macOS nao distingue maiusculas, e o
# lancador do .app ja usa ~/Library/Logs/tr8s-grid.log para o stderr - os dois
# viravam o MESMO arquivo, e o nosso log apagava justamente o traceback que
# explicaria uma falha de abertura (aconteceu em 14/08/2026).
LOG_PATH = os.path.expanduser("~/Library/Logs/TR8S-Grid-app.log")

# indice da paleta Novation -> hex, so os que o grid usa de fato
PALETA = {0: "#1a1a1a", 1: "#3a3a3a", 3: "#ffffff", 5: "#ff3b30", 7: "#5c1512",
          9: "#ff9500", 11: "#5c3a0f", 13: "#ffe600", 21: "#33d17a",
          23: "#14532d", 45: "#3b82f6", 49: "#a855f7"}


def cor_hex(cor):
    """Cor do motor (indice da paleta ou tupla RGB de 0-127) -> hex do Tk."""
    if isinstance(cor, tuple):
        r, g, b = (min(255, int(c * 2)) for c in cor)
        return f"#{r:02x}{g:02x}{b:02x}"
    return PALETA.get(cor, "#1a1a1a")


class LogArquivo:
    """Log em arquivo com timestamp. A janela mostra so a ultima linha."""

    def __init__(self, caminho=LOG_PATH):
        self.caminho = caminho
        try:
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            if os.path.exists(caminho) and os.path.getsize(caminho) > 1_000_000:
                os.replace(caminho, caminho + ".old")
            self.f = open(caminho, "a", encoding="utf-8")
        except OSError:
            self.f = None

    def escrever(self, texto):
        if not self.f:
            return
        try:
            self.f.write(time.strftime("%H:%M:%S  ") + texto + "\n")
            self.f.flush()
        except OSError:
            pass


class BotaoCanvas(tk.Canvas):
    """Botao desenhado a mao: o Tk 8.5 Aqua ignora cores de tk.Button, mas
    pinta Canvas direitinho. definir_ativo() e a indicacao de modo ativo que
    a versao anterior nunca conseguiu mostrar."""

    def __init__(self, pai, texto, comando, largura=96, altura=42,
                 cor_ativa=VERDE, fonte=("Helvetica", 14, "bold")):
        super().__init__(pai, width=largura, height=altura, bg=BG,
                         highlightthickness=0)
        self.comando, self.cor_ativa, self.ativo = comando, cor_ativa, False
        self.fundo = self.create_rectangle(1, 1, largura - 2, altura - 2,
                                           fill=CARD, outline=LINHA)
        self.rotulo = self.create_text(largura // 2, altura // 2, text=texto,
                                       fill=MUTED, font=fonte)
        self.bind("<Button-1>", lambda e: self.comando())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, dentro):
        self.itemconfig(self.fundo, outline=INK if dentro else LINHA)

    def definir_ativo(self, ativo):
        if ativo == self.ativo:
            return
        self.ativo = ativo
        self.itemconfig(self.fundo, fill=self.cor_ativa if ativo else CARD)
        self.itemconfig(self.rotulo, fill="#0b0b0b" if ativo else MUTED)


class EditorPattern(tk.Canvas):
    """Grade estilo TR-EDITOR: 11 instrumentos + ACC x 16 steps.

    Sempre visivel: sem motor, mostra o esqueleto (celulas com outline sobre o
    fundo) - a versao anterior nascia invisivel porque as celulas tinham quase
    a cor do fundo e so pintava depois de clicar num modo.

    Repintura por DIFF: 192 celulas x 20 fps de itemconfig engasgam o Tk 8.5;
    aqui so o que mudou e tocado."""

    CEL, ALT_CEL = 26, 22
    ESQ = 42                    # margem dos rotulos

    def __init__(self, pai, ao_clicar=None, cel=None, alt_cel=None):
        self.CEL = cel or self.CEL
        self.ALT_CEL = alt_cel or self.ALT_CEL
        n = len(L.INSTRUMENTOS) + 1                     # + ACCENT
        larg = self.ESQ + 16 * self.CEL + 4
        alt = 16 + n * self.ALT_CEL + 4
        super().__init__(pai, width=larg, height=alt, bg=BG,
                         highlightthickness=0)
        self.ao_clicar = ao_clicar
        self.cel, self.cor_atual = [], {}
        self.marca_prob, self.prob_atual = {}, {}
        # regua de numeros, cabeca de tempo a cada 4
        for s in range(16):
            self.create_text(self.ESQ + s * self.CEL + self.CEL // 2, 8,
                             text=str(s + 1), fill=INK if s % 4 == 0 else MUTED,
                             font=("Menlo", 9))
        for r in range(n):
            nome = L.INSTRUMENTOS[r] if r < len(L.INSTRUMENTOS) else "ACC"
            y = 16 + r * self.ALT_CEL
            self.create_text(4, y + self.ALT_CEL // 2, text=nome, anchor="w",
                             fill=MUTED, font=("Menlo", 11))
            linha = []
            for s in range(16):
                x = self.ESQ + s * self.CEL
                cid = self.create_rectangle(
                    x + 1, y + 2, x + self.CEL - 2, y + self.ALT_CEL - 2,
                    fill=COR_CEL_VAZIA, outline="#1e1a17")
                linha.append(cid)
                self.cor_atual[cid] = COR_CEL_VAZIA
                if r < len(L.INSTRUMENTOS):
                    # cantinho da probability: triangulo, escondido por padrao
                    m = self.create_polygon(
                        x + self.CEL - 8, y + 2, x + self.CEL - 2, y + 2,
                        x + self.CEL - 2, y + 8, fill="", outline="")
                    self.marca_prob[(r, s)] = m
                    self.prob_atual[(r, s)] = False
            self.cel.append(linha)
        # regua do last step + playhead (retangulo de contorno movido, nunca
        # recriado)
        self.regua = self.create_line(0, 0, 0, 0, fill=AMARELO)
        self.play = self.create_rectangle(0, 0, 0, 0, outline=VERDE, width=2)
        self.itemconfigure(self.play, state="hidden")
        self._play_col = None
        if ao_clicar:
            self.bind("<Button-1>", self._clique)
            self.bind("<Shift-Button-1>", lambda ev: self._clique(ev, True))
            self.bind("<Double-Button-1>", self._duplo)

    def _pos(self, ev):
        s = (ev.x - self.ESQ) // self.CEL
        r = (ev.y - 16) // self.ALT_CEL
        if 0 <= s < 16 and 0 <= r <= len(L.INSTRUMENTOS):
            return int(r), int(s)
        return None

    def _clique(self, ev, fraco=False):
        if not self.ao_clicar:
            return
        # clique no NOME do instrumento (faixa dos rotulos) abre o seletor
        # de tone - o gesto INST do TR-EDITOR
        if ev.x < self.ESQ:
            r = (ev.y - 16) // self.ALT_CEL
            if 0 <= r < len(L.INSTRUMENTOS):
                self.ao_clicar(int(r), -1, "inst")
            return
        p = self._pos(ev)
        if p:
            self.ao_clicar(p[0], p[1], "fraco" if fraco else "toggle")

    def _duplo(self, ev):
        p = self._pos(ev)
        if p and self.ao_clicar and p[0] < len(L.INSTRUMENTOS):
            self.ao_clicar(p[0], p[1], "prob")

    def _cor(self, cid, cor):
        if self.cor_atual.get(cid) != cor:
            self.itemconfig(cid, fill=cor)
            self.cor_atual[cid] = cor

    def pintar(self, e):
        ptn, subs = e.get("pattern", {}), e.get("subs", {})
        alts, probs = e.get("alts", {}), e.get("probs", {})
        invalido = e.get("cache_invalido", set())
        for i in range(len(L.INSTRUMENTOS)):
            lim = min(e["last_var"], e["last_track"][i] or 16)
            for s in range(16):
                v = ptn.get(i, [0] * 16)[s]
                sub = subs.get(i, [0] * 16)[s]
                alt = alts.get(i, [0] * 16)[s]
                if i in invalido:                cor = COR_CEL_ALERTA
                elif s >= lim:                   cor = COR_CEL_FORA
                elif v == 0:                     cor = COR_CEL_VAZIA
                elif e["mudo"][i]:               cor = COR_CEL_MUDA
                elif alt:                        cor = COR_CEL_ALT
                elif sub == L.SUB_FLAM:          cor = COR_CEL_FLAM
                elif sub:                        cor = COR_CEL_SUB
                else:                            cor = COR_CEL_NOTA
                self._cor(self.cel[i][s], cor)
                p = probs.get(i, [100] * 16)[s]
                quer = bool(v) and p < 100 and s < lim and i not in invalido
                if self.prob_atual[(i, s)] != quer:
                    self.itemconfig(self.marca_prob[(i, s)],
                                    fill="#ffffff" if quer else "")
                    self.prob_atual[(i, s)] = quer
        r = len(L.INSTRUMENTOS)
        for s in range(16):
            lig = e["acc"] & (1 << s)
            self._cor(self.cel[r][s],
                      COR_CEL_ACC if lig else
                      (COR_CEL_FORA if s >= e["last_var"] else COR_CEL_VAZIA))
        x = self.ESQ + e["last_var"] * self.CEL
        self.coords(self.regua, x, 14,
                    x, 16 + (len(L.INSTRUMENTOS) + 1) * self.ALT_CEL)
        # playhead: coluna inteira, so quando o grid esta na variacao que toca
        col = e["passo"] if (e.get("playhead_visivel") and e.get("tocando")
                             and e["passo"] >= 0) else None
        if col != self._play_col:
            self._play_col = col
            if col is None:
                self.itemconfigure(self.play, state="hidden")
            else:
                x = self.ESQ + col * self.CEL
                self.coords(self.play, x, 15, x + self.CEL - 1,
                            16 + (len(L.INSTRUMENTOS) + 1) * self.ALT_CEL)
                self.itemconfigure(self.play, state="normal")


class App:
    def __init__(self, raiz):
        self.raiz = raiz
        raiz.title("TR-8S Grid")
        raiz.configure(bg=BG)
        raiz.geometry("820x680")
        raiz.minsize(820, 680)

        self.motor = None
        self.thread = None
        self.rodando = False
        self.fila_log = queue.Queue()
        self.arquivo_log = LogArquivo()
        self.ultimo_estado = {}
        self._silencio_ui = False
        self._t_status = 0.0

        estilo = ttk.Style()
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        estilo.configure("TFrame", background=BG)
        estilo.configure("TLabel", background=BG, foreground=INK)
        estilo.configure("TNotebook", background=BG, borderwidth=0)
        estilo.configure("TNotebook.Tab", background=CARD, foreground=MUTED,
                         padding=(14, 6), borderwidth=0)
        estilo.map("TNotebook.Tab",
                   background=[("selected", LINHA)],
                   foreground=[("selected", INK)])
        estilo.configure("TCombobox", fieldbackground=CARD, background=CARD,
                         foreground=INK, arrowcolor=INK)
        estilo.configure("Horizontal.TScale", background=BG, troughcolor=CARD)

        self._montar()
        self.raiz.after(50, self._laco_ui)
        self.raiz.protocol("WM_DELETE_WINDOW", self.sair)

    # ── construcao ──────────────────────────────────────────
    def _montar(self):
        topo = tk.Frame(self.raiz, bg=BG)
        topo.pack(fill="x", padx=12, pady=(10, 4))
        self.pontos = {}
        for chave, rotulo in (("ctrl", "TR-8S CTRL"), ("lp", "Launchpad"),
                              ("clock", "clock")):
            cel = tk.Frame(topo, bg=BG); cel.pack(side="left", padx=(0, 14))
            p = tk.Canvas(cel, width=10, height=10, bg=BG, highlightthickness=0)
            p.create_oval(1, 1, 9, 9, fill=VERMELHO, outline="")
            p.pack(side="left", padx=(0, 5))
            tk.Label(cel, text=rotulo, bg=BG, fg=MUTED,
                     font=("Helvetica", 11)).pack(side="left")
            self.pontos[chave] = p

        botoes = tk.Frame(self.raiz, bg=BG)
        botoes.pack(fill="x", padx=12, pady=6)
        # os dois estilos de standby sao o MESMO modo com parametros diferentes;
        # viraram dois botoes pra nao esconder o estilo num seletor
        self.b_modo = {}
        for chave, texto, cor, cmd in (
                ("on", "ON", VERDE,
                 lambda: self.trocar_modo(L.MODO_ON)),
                ("off", "off", CINZA_MODO,
                 lambda: self.trocar_modo(L.MODO_OFF)),
                ("chuva", "standby", ROXO,
                 lambda: self.trocar_modo(L.MODO_STANDBY, L.ESTILO_CHUVA)),
                ("ambiente", "ambiente", ROXO,
                 lambda: self.trocar_modo(L.MODO_STANDBY, L.ESTILO_AMBIENTE))):
            b = BotaoCanvas(botoes, texto, cmd, cor_ativa=cor)
            b.pack(side="left", padx=(0, 8))
            self.b_modo[chave] = b
        for texto, cmd in (("Recalibrar", self.recalibrar),
                           ("Apagar e soltar os pads", self.blackout)):
            BotaoCanvas(botoes, texto, cmd, largura=170, altura=42,
                        cor_ativa=CARD, fonte=("Helvetica", 11)
                        ).pack(side="left", padx=(0, 8))

        self.rotulo_estado = tk.Label(self.raiz, text="—", bg=BG, fg=MUTED,
                                      font=("Helvetica", 11), anchor="w")
        self.rotulo_estado.pack(fill="x", padx=12, pady=(2, 4))

        self.abas = ttk.Notebook(self.raiz)
        self.abas.pack(fill="both", expand=True, padx=8, pady=(0, 2))
        # sem aba de grid: o grid fisico (launchpads) ja mostra e edita steps;
        # a janela fica com o que o fisico nao tem (mixer/FX, tones, chain...)
        self.aba_mixer = ttk.Frame(self.abas)
        self.aba_inst = ttk.Frame(self.abas)
        self.aba_bib = ttk.Frame(self.abas)
        self.aba_chain = ttk.Frame(self.abas)
        self.aba_estoc = ttk.Frame(self.abas)
        self.aba_avanc = ttk.Frame(self.abas)
        for aba, titulo in ((self.aba_mixer, "Mixer & FX"),
                            (self.aba_inst, "Instrumento"),
                            (self.aba_bib, "Biblioteca"),
                            (self.aba_chain, "Chain"),
                            (self.aba_estoc, "Estocástica"),
                            (self.aba_avanc, "Avançado")):
            self.abas.add(aba, text=titulo)
        self._montar_mixer(self.aba_mixer)
        self._montar_instrumento(self.aba_inst)
        self._montar_biblioteca(self.aba_bib)
        self._montar_chain(self.aba_chain)
        self._montar_estocastica(self.aba_estoc)
        self._montar_avancado(self.aba_avanc)

        # rodape: ultima linha do log (o log inteiro vive no arquivo) e a data
        # do build. O build importa: o macOS ATIVA a janela ja aberta em vez de
        # abrir o .app recem-gerado, e uma janela velha esquecida se passa pela
        # nova (aconteceu em 14/08/2026 - a de 12 h atras estava com 1,6 GB)
        try:
            build = time.strftime("%d/%m %H:%M", time.localtime(
                os.path.getmtime(os.path.abspath(__file__))))
        except OSError:
            build = "?"
        self.rotulo_log = tk.Label(self.raiz, text=f"build {build}", bg=BG,
                                   fg=MUTED, font=("Menlo", 10), anchor="w")
        self.rotulo_log.pack(fill="x", padx=12, pady=(0, 6))

    def _montar_placeholder(self, pai, texto):
        tk.Label(pai, text=texto, bg=BG, fg=MUTED,
                 font=("Helvetica", 12)).pack(pady=40)

    # ── biblioteca de estilos ───────────────────────────────
    def _montar_biblioteca(self, pai):
        esq = tk.Frame(pai, bg=BG); esq.pack(side="left", fill="y",
                                             padx=(8, 4), pady=8)
        self.arvore_bib = ttk.Treeview(esq, show="tree", height=22)
        self.arvore_bib.pack(fill="y", expand=True)
        self._bib_por_iid = {}
        for estilo, pats in B.por_estilo().items():
            no = self.arvore_bib.insert("", "end", text=estilo, open=False)
            for p in pats:
                iid = self.arvore_bib.insert(no, "end", text=p["nome"])
                self._bib_por_iid[iid] = p
        self.arvore_bib.bind("<<TreeviewSelect>>", self._escolher_pattern)

        dirta = tk.Frame(pai, bg=BG); dirta.pack(side="left", fill="both",
                                                 expand=True, padx=8, pady=8)
        self.rotulo_bib = tk.Label(dirta, text="escolha um pattern na lista",
                                   bg=BG, fg=INK, font=("Helvetica", 13),
                                   anchor="w", justify="left")
        self.rotulo_bib.pack(fill="x")
        self.rotulo_bib_obs = tk.Label(dirta, text="", bg=BG, fg=AMARELO,
                                       font=("Helvetica", 11), anchor="w",
                                       justify="left", wraplength=380)
        self.rotulo_bib_obs.pack(fill="x")
        self.preview_bib = EditorPattern(dirta, cel=20, alt_cel=17)
        self.preview_bib.pack(anchor="w", pady=(6, 8))
        linha_b = tk.Frame(dirta, bg=BG); linha_b.pack(fill="x")
        self.b_escrever = BotaoCanvas(linha_b, "Escrever na TR-8S",
                                      self._escrever_pattern, largura=180,
                                      altura=40, cor_ativa=VERMELHO,
                                      fonte=("Helvetica", 12, "bold"))
        self.b_escrever.pack(side="left", padx=(0, 8))
        BotaoCanvas(linha_b, "Desfazer última escrita",
                    self._desfazer_pattern, largura=180, altura=40,
                    cor_ativa=CARD, fonte=("Helvetica", 11)
                    ).pack(side="left")
        self.rotulo_bib_alvo = tk.Label(dirta, text="", bg=BG, fg=MUTED,
                                        font=("Helvetica", 10), anchor="w",
                                        justify="left", wraplength=380)
        self.rotulo_bib_alvo.pack(fill="x", pady=(6, 0))
        self._bib_sel, self._bib_armado_t = None, 0.0

    def _estado_falso(self, pat):
        """expandir() -> o dicionario que o EditorPattern.pintar espera."""
        dados = B.expandir(pat)
        n = len(L.INSTRUMENTOS)
        return {
            "pattern": {i: [v for v, _, _, _ in dados[i]] for i in range(n)},
            "subs": {i: [s for _, s, _, _ in dados[i]] for i in range(n)},
            "alts": {i: [a for _, _, _, a in dados[i]] for i in range(n)},
            "probs": {i: [p for _, _, p, _ in dados[i]] for i in range(n)},
            "mudo": [False] * n, "acc": pat.get("accent", 0),
            "last_var": pat.get("last_var", 16), "last_track": [16] * n,
            "cache_invalido": set(), "passo": -1,
            "playhead_visivel": False, "tocando": False,
        }

    def _escolher_pattern(self, _ev=None):
        sel = self.arvore_bib.selection()
        pat = self._bib_por_iid.get(sel[0]) if sel else None
        self._bib_sel = pat
        self._desarmar_escrita()
        if not pat:
            return
        self.rotulo_bib.config(
            text=f"{pat['nome']}  ·  {pat['bpm']} bpm  ·  kit: {pat['kit']}")
        self.rotulo_bib_obs.config(text=pat.get("obs", ""))
        self.preview_bib.pintar(self._estado_falso(pat))

    def _desarmar_escrita(self):
        self._bib_armado_t = 0.0
        self.b_escrever.definir_ativo(False)
        self.b_escrever.itemconfig(self.b_escrever.rotulo,
                                   text="Escrever na TR-8S")

    def _escrever_pattern(self):
        pat = self._bib_sel
        if not pat:
            self.log("(!) escolha um pattern na lista primeiro"); return
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        e = self.ultimo_estado
        if e.get("modo_geral") != L.MODO_ON or not e.get("carregado"):
            self.log("(!) escrever pattern so no modo ON"); return
        agora = time.time()
        if agora - self._bib_armado_t > 2.0:
            # primeiro clique: arma e avisa o alvo (padrao do CLEAR variacao)
            self._bib_armado_t = agora
            self.b_escrever.definir_ativo(True)
            self.b_escrever.itemconfig(self.b_escrever.rotulo,
                                       text="Clique de novo (2 s)")
            alvo = e.get("variacao_nome", "?")
            tocando = (e.get("variacao_tocando") == e.get("variacao"))
            self.rotulo_bib_alvo.config(
                text=f"vai sobrescrever a variação {alvo}"
                     + (" — que está TOCANDO agora" if tocando else "")
                     + ". O Desfazer volta o que estava.")
            return
        self._desarmar_escrita()
        self.rotulo_bib_alvo.config(text="")
        self.motor.enfileirar(self.motor.escrever_pattern, B.expandir(pat),
                              pat.get("accent", 0), pat.get("last_var", 16),
                              pat["nome"])

    def _desfazer_pattern(self):
        if self.motor:
            self.motor.enfileirar(self.motor.desfazer_escrita)

    # ── chain ───────────────────────────────────────────────
    MODOS_CHAIN = [
        ("reescrita", "biblioteca (reescrita — funciona hoje)"),
        ("variacao", "variação A-H (requer sessão C)"),
        ("pattern", "pattern da máquina (requer sessão B)"),
        ("pc", "program change (requer sessão B)"),
    ]

    def _montar_chain(self, pai):
        topo = tk.Frame(pai, bg=BG); topo.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(topo, text="modo", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        self.var_chain_modo = tk.StringVar(value=self.MODOS_CHAIN[0][1])
        ttk.Combobox(topo, textvariable=self.var_chain_modo, width=38,
                     state="readonly",
                     values=[r for _, r in self.MODOS_CHAIN]
                     ).pack(side="left", padx=(4, 0))

        linha = tk.Frame(pai, bg=BG); linha.pack(fill="x", padx=8, pady=4)
        tk.Label(linha, text="entrada", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        self.var_chain_alvo = tk.StringVar()
        self.cb_chain_alvo = ttk.Combobox(
            linha, textvariable=self.var_chain_alvo, width=26,
            values=[p["nome"] for p in B.PATTERNS])
        self.cb_chain_alvo.pack(side="left", padx=(4, 10))
        tk.Label(linha, text="repetições", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        self.var_chain_reps = tk.StringVar(value="2")
        ttk.Combobox(linha, textvariable=self.var_chain_reps, width=3,
                     state="readonly", values=[str(i) for i in range(1, 17)]
                     ).pack(side="left", padx=(4, 10))
        BotaoCanvas(linha, "Adicionar", self._chain_adicionar, largura=100,
                    altura=32, cor_ativa=CARD, fonte=("Helvetica", 11)
                    ).pack(side="left")
        self.var_chain_modo.trace_add("write",
                                      lambda *a: self._chain_trocar_modo())
        tk.Label(pai, text="no modo variação: A-H · no modo pattern/PC: "
                          "A1..H16 (banco+numero)", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).pack(anchor="w", padx=8)

        meio = tk.Frame(pai, bg=BG); meio.pack(fill="x", padx=8, pady=4)
        self.lista_chain = ttk.Treeview(
            meio, show="headings", columns=("nome", "reps"), height=8)
        self.lista_chain.heading("nome", text="pattern")
        self.lista_chain.heading("reps", text="reps")
        self.lista_chain.column("nome", width=280)
        self.lista_chain.column("reps", width=60, anchor="center")
        self.lista_chain.pack(side="left")
        lado = tk.Frame(meio, bg=BG); lado.pack(side="left", padx=8)
        for texto, cmd in (("▲", lambda: self._chain_mover(-1)),
                           ("▼", lambda: self._chain_mover(+1)),
                           ("remover", self._chain_remover)):
            BotaoCanvas(lado, texto, cmd, largura=90, altura=30,
                        cor_ativa=CARD, fonte=("Helvetica", 11)
                        ).pack(pady=2)

        rodape = tk.Frame(pai, bg=BG); rodape.pack(fill="x", padx=8, pady=6)
        self.b_chain_armar = BotaoCanvas(rodape, "Armar", self._chain_armar,
                                         largura=110, altura=40,
                                         cor_ativa=VERDE)
        self.b_chain_armar.pack(side="left", padx=(0, 8))
        BotaoCanvas(rodape, "Parar", self._chain_parar, largura=110,
                    altura=40, cor_ativa=CARD).pack(side="left")
        self.rotulo_chain = tk.Label(pai, text="", bg=BG, fg=MUTED,
                                     font=("Helvetica", 11), anchor="w",
                                     justify="left", wraplength=680)
        self.rotulo_chain.pack(fill="x", padx=8)
        self._chain_entradas = []      # [(rotulo, entrada_do_ferramentas)]

    def _chain_modo(self):
        rot = self.var_chain_modo.get()
        return next(m for m, r in self.MODOS_CHAIN if r == rot)

    def _chain_trocar_modo(self):
        modo = self._chain_modo()
        if modo == "reescrita":
            self.cb_chain_alvo.config(values=[p["nome"] for p in B.PATTERNS])
        elif modo == "variacao":
            self.cb_chain_alvo.config(values=list("ABCDEFGH"))
        else:
            self.cb_chain_alvo.config(
                values=[f"{b}{n}" for b in "ABCDEFGH" for n in range(1, 17)])
        self.var_chain_alvo.set("")
        # trocar de modo invalida a lista (entradas de tipos diferentes)
        self._chain_entradas.clear()
        for iid in self.lista_chain.get_children():
            self.lista_chain.delete(iid)

    def _chain_adicionar(self):
        alvo, modo = self.var_chain_alvo.get().strip(), self._chain_modo()
        reps = int(self.var_chain_reps.get())
        try:
            if modo == "reescrita":
                pat = next(p for p in B.PATTERNS if p["nome"] == alvo)
                ent = {"nome": pat["nome"], "dados": B.expandir(pat),
                       "accent": pat.get("accent", 0), "reps": reps}
                rotulo = pat["nome"]
            elif modo == "variacao":
                v = "ABCDEFGH".index(alvo.upper()) + 1
                ent, rotulo = {"var": v, "reps": reps}, f"variação {alvo.upper()}"
            else:
                n = L._num_pattern(alvo)
                if not 0 <= n <= 127:
                    raise ValueError(alvo)
                ent, rotulo = {"alvo": n, "reps": reps}, f"pattern {alvo.upper()}"
        except (StopIteration, ValueError, IndexError):
            self.log(f"(!) entrada invalida: '{alvo}'"); return
        self._chain_entradas.append((rotulo, ent))
        self.lista_chain.insert("", "end", values=(rotulo, reps))

    def _chain_sel_idx(self):
        sel = self.lista_chain.selection()
        if not sel:
            return None
        return self.lista_chain.index(sel[0])

    def _chain_remover(self):
        i = self._chain_sel_idx()
        if i is not None:
            self._chain_entradas.pop(i)
            self.lista_chain.delete(self.lista_chain.get_children()[i])

    def _chain_mover(self, d):
        i = self._chain_sel_idx()
        if i is None or not 0 <= i + d < len(self._chain_entradas):
            return
        ents = self._chain_entradas
        ents[i], ents[i+d] = ents[i+d], ents[i]
        iid = self.lista_chain.get_children()[i]
        self.lista_chain.move(iid, "", i + d)

    def _chain_armar(self):
        if not self._chain_entradas:
            self.log("(!) chain vazio - adicione entradas"); return
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        modo = self._chain_modo()
        entradas = [e for _, e in self._chain_entradas]
        def armar():
            self.motor.chain = F.Chain(entradas, modo, log=self.motor.log)
            self.motor.chain.armar(self.motor)
            if not self.motor.chain.ativo:
                self.motor.chain = None
        self.motor.enfileirar(armar)

    def _chain_parar(self):
        if self.motor and self.motor.chain:
            self.motor.enfileirar(self.motor.chain.parar)

    # ── estocastica ─────────────────────────────────────────
    def _montar_estocastica(self, pai):
        self.estocastica = F.Estocastica()
        tk.Label(pai, text="opera na variação aberta; o primeiro uso guarda "
                          "um snapshot — Reverter volta tudo. Probability é "
                          "nativa da TR-8S (a máquina sorteia a cada volta).",
                 bg=BG, fg=MUTED, font=("Helvetica", 11), wraplength=680,
                 justify="left").pack(anchor="w", padx=8, pady=(8, 4))

        topo = tk.Frame(pai, bg=BG); topo.pack(fill="x", padx=8, pady=2)
        tk.Label(topo, text="seed", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        self.var_seed = tk.StringVar(value="1")
        tk.Entry(topo, textvariable=self.var_seed, width=8, bg=CARD, fg=INK,
                 insertbackground=INK, highlightthickness=0,
                 font=("Menlo", 11)).pack(side="left", padx=(4, 4))
        tk.Label(topo, text="(mesma seed sobre o mesmo pattern = mesmo "
                            "resultado)", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).pack(side="left")

        self.escalas = {}
        for chave, rotulo, de, ate, ini in (
                ("densidade", "densidade (×)", 0.25, 2.0, 1.0),
                ("humanize", "humanize velocity (±)", 0, 40, 15),
                ("retrig", "retrig / sub steps (%)", 0, 50, 15),
                ("ghosts", "ghost notes (%)", 0, 50, 20)):
            linha = tk.Frame(pai, bg=BG); linha.pack(fill="x", padx=8, pady=3)
            tk.Label(linha, text=rotulo, bg=BG, fg=INK, width=22, anchor="w",
                     font=("Helvetica", 11)).pack(side="left")
            v = tk.DoubleVar(value=ini)
            ttk.Scale(linha, variable=v, from_=de, to=ate, length=260
                      ).pack(side="left", padx=(0, 6))
            mostra = tk.Label(linha, text=str(ini), bg=BG, fg=MUTED, width=5,
                              font=("Menlo", 11))
            mostra.pack(side="left", padx=(0, 8))
            v.trace_add("write", lambda *a, vv=v, m=mostra, c=chave:
                        m.config(text=f"{vv.get():.2f}" if c == "densidade"
                                 else f"{vv.get():.0f}"))
            BotaoCanvas(linha, "Aplicar", lambda c=chave: self._estoc_aplicar(c),
                        largura=90, altura=30, cor_ativa=CARD,
                        fonte=("Helvetica", 11)).pack(side="left")
            self.escalas[chave] = v

        # regua de probability por step: a visao geral que o painel nao tem
        # (la e um step por vez, long-press + VALUE). Nao e espelho do grid
        # fisico - o launchpad nao mostra probability.
        tira = tk.Frame(pai, bg=BG); tira.pack(fill="x", padx=8, pady=(10, 0))
        tk.Label(tira, text="probability por step", bg=BG, fg=INK,
                 font=("Helvetica", 11, "bold")).pack(side="left")
        self.var_prob_inst = tk.StringVar(value=L.INSTRUMENTOS[0])
        ttk.Combobox(tira, textvariable=self.var_prob_inst, width=4,
                     state="readonly", values=L.INSTRUMENTOS
                     ).pack(side="left", padx=6)
        tk.Label(tira, text="(steps apagados ficam travados)", bg=BG,
                 fg=MUTED, font=("Helvetica", 10)).pack(side="left")
        fila = tk.Frame(pai, bg=BG); fila.pack(fill="x", padx=8, anchor="w")
        self.prob_vars, self.prob_escalas, self.prob_rotulos = [], [], []
        for s in range(16):
            cel = tk.Frame(fila, bg=BG)
            rot = tk.Label(cel, text="—", bg=BG, fg=MUTED, font=("Menlo", 8))
            rot.pack()
            v = tk.DoubleVar(value=100)
            esc = ttk.Scale(cel, variable=v, from_=100, to=10,
                            orient="vertical", length=60)
            esc.pack()
            esc.bind("<ButtonPress-1>",
                     lambda ev: setattr(self, "_fx_arrastando", True))
            esc.bind("<ButtonRelease-1>",
                     lambda ev, k=s, vv=v: (
                         setattr(self, "_fx_arrastando", False),
                         self._prob_step_aplicar(k, int(round(vv.get())))))
            v.trace_add("write", lambda *a, vv=v, r=rot:
                        r.config(text=str(int(round(vv.get())))))
            tk.Label(cel, text=str(s + 1), bg=BG,
                     fg=INK if s % 4 == 0 else MUTED,
                     font=("Menlo", 8)).pack()
            cel.pack(side="left", padx=1)
            self.prob_vars.append(v)
            self.prob_escalas.append(esc)
            self.prob_rotulos.append(rot)

        rodape = tk.Frame(pai, bg=BG); rodape.pack(fill="x", padx=8, pady=8)
        BotaoCanvas(rodape, "Reverter tudo", self._estoc_reverter, largura=130,
                    altura=40, cor_ativa=VERMELHO,
                    fonte=("Helvetica", 12, "bold")).pack(side="left")

    def _estoc_aplicar(self, chave):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        try:
            seed = int(self.var_seed.get())
        except ValueError:
            seed = self.var_seed.get() or None
        self.estocastica.definir_seed(seed)
        v = self.escalas[chave].get()
        m = self.motor
        acao = {"densidade": lambda: self.estocastica.densidade(m, round(v, 2)),
                "humanize": lambda: self.estocastica.humanize_vel(m, int(v)),
                "retrig": lambda: self.estocastica.retrig(m, int(v)),
                "ghosts": lambda: self.estocastica.gerar_ghosts(m, int(v))}[chave]
        m.enfileirar(acao)

    def _estoc_reverter(self):
        if self.motor:
            self.motor.enfileirar(self.estocastica.reverter, self.motor)

    def _prob_step_aplicar(self, s, pct):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        i = L.INSTRUMENTOS.index(self.var_prob_inst.get())
        self.motor.enfileirar(self.motor.definir_prob, i, s, pct)

    def _pintar_estocastica(self, e):
        if self._fx_arrastando:
            return
        i = L.INSTRUMENTOS.index(self.var_prob_inst.get())
        vels = (e.get("pattern") or {}).get(i, [0] * 16)
        probs = (e.get("probs") or {}).get(i, [100] * 16)
        for s in range(16):
            ligado = bool(vels[s])
            estava = "disabled" not in self.prob_escalas[s].state()
            if ligado != estava:
                self.prob_escalas[s].state(
                    ["!disabled"] if ligado else ["disabled"])
            if not ligado:
                if self.prob_rotulos[s].cget("text") != "·":
                    self.prob_rotulos[s].config(text="·")
            elif int(round(self.prob_vars[s].get())) != probs[s]:
                self.prob_vars[s].set(probs[s])

    # ── avancado (bloco utility - NADA testado em hardware) ─
    def _montar_avancado(self, pai):
        tk.Label(pai, text="comandos do mapa oficial da Roland (achados nas "
                           "capturas do ARIA). NENHUM foi testado nesta "
                           "máquina: cada botão é uma mini-sessão — observe a "
                           "TR-8S e o resultado vai para a REFERENCIA.",
                 bg=BG, fg=AMARELO, font=("Helvetica", 11), wraplength=680,
                 justify="left").pack(anchor="w", padx=8, pady=(8, 6))

        self.rotulo_avanc = tk.Label(pai, text="pattern atual: ?  ·  kit "
                                               "atual: ?",
                                     bg=BG, fg=INK, font=("Menlo", 11),
                                     anchor="w")
        self.rotulo_avanc.pack(fill="x", padx=8, pady=(0, 6))

        linha1 = tk.Frame(pai, bg=BG); linha1.pack(fill="x", padx=8, pady=3)
        BotaoCanvas(linha1, "Está tocando?",
                    lambda: self._avanc(self.motor.util_esta_tocando)
                    if self.motor else None,
                    largura=140, altura=36, cor_ativa=CARD,
                    fonte=("Helvetica", 11)).pack(side="left", padx=(0, 8))
        BotaoCanvas(linha1, "Versão do firmware",
                    lambda: self._avanc(self.motor.util_versao)
                    if self.motor else None,
                    largura=150, altura=36, cor_ativa=CARD,
                    fonte=("Helvetica", 11)).pack(side="left")

        linha2 = tk.Frame(pai, bg=BG); linha2.pack(fill="x", padx=8, pady=3)
        self.var_visor = tk.StringVar(value="TR-8S GRID")
        tk.Entry(linha2, textvariable=self.var_visor, width=32, bg=CARD,
                 fg=INK, insertbackground=INK, highlightthickness=0,
                 font=("Menlo", 11)).pack(side="left", padx=(0, 8))
        BotaoCanvas(linha2, "Escrever no visor",
                    lambda: self._avanc(self.motor.util_escrever_visor,
                                        self.var_visor.get())
                    if self.motor else None,
                    largura=150, altura=36, cor_ativa=CARD,
                    fonte=("Helvetica", 11)).pack(side="left")

        linha3 = tk.Frame(pai, bg=BG); linha3.pack(fill="x", padx=8, pady=(12, 3))
        self.b_write = BotaoCanvas(linha3, "WRITE (salvar pattern)",
                                   self._avanc_write, largura=190, altura=40,
                                   cor_ativa=VERMELHO,
                                   fonte=("Helvetica", 12, "bold"))
        self.b_write.pack(side="left")
        tk.Label(linha3, text="grava o pattern atual na memória da máquina — "
                              "2 cliques; teste de verdade é religar depois",
                 bg=BG, fg=MUTED, font=("Helvetica", 10), wraplength=380,
                 justify="left").pack(side="left", padx=8)
        self._write_armado_t = 0.0

    def _avanc(self, fn, *args):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        self.motor.enfileirar(fn, *args)

    def _avanc_write(self):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        agora = time.time()
        if agora - self._write_armado_t > 2.0:
            self._write_armado_t = agora
            self.b_write.definir_ativo(True)
            self.b_write.itemconfig(self.b_write.rotulo,
                                    text="Clique de novo (2 s)")
            return
        self._write_armado_t = 0.0
        self.b_write.definir_ativo(False)
        self.b_write.itemconfig(self.b_write.rotulo,
                                text="WRITE (salvar pattern)")
        self.motor.enfileirar(self.motor.util_write_pattern)

    # ── mixer & FX ──────────────────────────────────────────
    def _montar_mixer(self, pai):
        topo = tk.Frame(pai, bg=BG); topo.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(topo, text="instrumento", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        # os controles de LISTA por instrumento (destino do LFO, INST FX)
        # valem para este instrumento; os faders mostram os 11 de uma vez
        self.var_fx_inst = tk.StringVar(value=L.INSTRUMENTOS[0])
        ttk.Combobox(topo, textvariable=self.var_fx_inst, width=4,
                     state="readonly", values=L.INSTRUMENTOS
                     ).pack(side="left", padx=(4, 14))
        BotaoCanvas(topo, "Reler valores",
                    lambda: self.motor.enfileirar(self.motor.ler_fx)
                    if self.motor else self.log("(!) ligue o modo ON primeiro"),
                    largura=110, altura=30, cor_ativa=CARD,
                    fonte=("Helvetica", 11)).pack(side="left")

        self.quadro_fx = tk.Frame(pai, bg=BG)
        self.quadro_fx.pack(fill="both", expand=True, padx=8, pady=2)
        self.fx_vars, self.fx_rotulos, self.fx_combos = {}, {}, {}
        self._fx_montados = None
        self._fx_arrastando = False
        self._fx_remontar({})

        # ── mapear: a lista do catalogo com o gesto de cada um ──
        tk.Frame(pai, bg=LINHA, height=1).pack(fill="x", padx=8, pady=(6, 4))
        cap = tk.Frame(pai, bg=BG); cap.pack(fill="x", padx=8)
        tk.Label(cap, text="mapear parâmetro", bg=BG, fg=INK,
                 font=("Helvetica", 11, "bold")).pack(side="left")
        self.b_capturar = BotaoCanvas(cap, "Capturar", self._fx_capturar,
                                      largura=100, altura=30,
                                      cor_ativa=VERMELHO,
                                      fonte=("Helvetica", 11))
        self.b_capturar.pack(side="left", padx=8)
        tk.Label(cap, text="ou outro nome:", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).pack(side="left")
        self.var_fx_nome = tk.StringVar()
        tk.Entry(cap, textvariable=self.var_fx_nome, width=14, bg=CARD,
                 fg=INK, insertbackground=INK, highlightthickness=0,
                 font=("Menlo", 11)).pack(side="left", padx=4)

        corpo = tk.Frame(pai, bg=BG); corpo.pack(fill="x", padx=8, pady=2)
        self.lista_cat = tk.Listbox(corpo, bg=CARD, fg=INK, font=("Menlo", 10),
                                    bd=0, height=6, highlightthickness=0,
                                    selectbackground=LINHA,
                                    selectforeground=INK, width=34)
        self.lista_cat.pack(side="left")
        self.lista_cat.bind("<<ListboxSelect>>", lambda e: self._fx_dica())
        self.rotulo_fx = tk.Label(
            corpo, text="", bg=BG, fg=AMARELO, font=("Helvetica", 10),
            wraplength=420, justify="left", anchor="nw")
        self.rotulo_fx.pack(side="left", fill="both", expand=True, padx=8)

        # ── anotar opcao: e assim que os enums ganham nome ──
        op = tk.Frame(pai, bg=BG); op.pack(fill="x", padx=8, pady=(2, 6))
        tk.Label(op, text="anotar opção de lista:", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).pack(side="left")
        self.var_op_param = tk.StringVar()
        self.cb_op_param = ttk.Combobox(op, textvariable=self.var_op_param,
                                        width=14, state="readonly", values=[])
        self.cb_op_param.pack(side="left", padx=4)
        self.var_op_rotulo = tk.StringVar()
        self.cb_op_rotulo = ttk.Combobox(op, textvariable=self.var_op_rotulo,
                                         width=12, values=[])
        self.cb_op_rotulo.pack(side="left", padx=4)
        self.var_op_param.trace_add("write", lambda *a: self._fx_sugestoes())
        BotaoCanvas(op, "Anotar", self._fx_anotar, largura=80, altura=28,
                    cor_ativa=CARD, fonte=("Helvetica", 11)).pack(side="left")
        tk.Label(op, text="(ponha a opção no visor da TR-8S e clique)",
                 bg=BG, fg=MUTED, font=("Helvetica", 10)).pack(side="left",
                                                               padx=6)
        self._fx_povoar_catalogo({})

    def _fx_fader(self, pai, chave, faixa, ao_soltar, comprimento=72,
                  ent=None):
        """Fader vertical + valor em cima. Escreve so no soltar do mouse -
        arrastar nao inunda a porta CTRL."""
        cel = tk.Frame(pai, bg=BG)
        rot = tk.Label(cel, text="—", bg=BG, fg=MUTED, font=("Menlo", 9))
        rot.pack()
        v = tk.DoubleVar(value=faixa[0])
        esc = ttk.Scale(cel, variable=v, from_=faixa[1], to=faixa[0],
                        orient="vertical", length=comprimento)
        esc.pack()
        esc.bind("<ButtonPress-1>",
                 lambda ev: setattr(self, "_fx_arrastando", True))
        esc.bind("<ButtonRelease-1>",
                 lambda ev: (setattr(self, "_fx_arrastando", False),
                             ao_soltar(int(round(v.get())))))
        v.trace_add("write", lambda *a, vv=v, r=rot, en=ent:
                    r.config(text=(E.rotulo_valor(en, int(round(vv.get())))
                                   if en else str(int(round(vv.get()))))))
        self.fx_vars[chave] = v
        self.fx_rotulos[chave] = rot
        return cel

    def _fx_remontar(self, mapa):
        """Reconstroi o corpo do mixer: fileira PROB fixa + os parametros ja
        mapeados, agrupados (LFO, SENDS, INST...). Fader por instrumento vira
        11 faders; lista por instrumento vira um combo do instrumento
        selecionado; parametro de kit vira uma linha unica."""
        for w in self.quadro_fx.winfo_children():
            w.destroy()
        self.fx_vars.clear(); self.fx_rotulos.clear(); self.fx_combos.clear()
        self._fx_montados = dict(mapa)

        def fileira(rotulo, prefixo, faixa, ao_soltar, ent=None):
            bloco = tk.Frame(self.quadro_fx, bg=BG)
            bloco.pack(fill="x", pady=(1, 4), anchor="w")
            tk.Label(bloco, text=rotulo, bg=BG, fg=INK, width=14, anchor="w",
                     font=("Helvetica", 11, "bold")).pack(side="left")
            for i, nome_i in enumerate(L.INSTRUMENTOS):
                cel = self._fx_fader(bloco, (prefixo, i), faixa,
                                     lambda val, k=i: ao_soltar(k, val),
                                     comprimento=58, ent=ent)
                tk.Label(cel, text=nome_i, bg=BG, fg=MUTED,
                         font=("Menlo", 9)).pack()
                cel.pack(side="left", padx=2)

        def titulo(texto):
            tk.Label(self.quadro_fx, text=texto, bg=BG, fg=MUTED,
                     font=("Helvetica", 10, "bold")).pack(anchor="w",
                                                          pady=(6, 0))

        # PROB e nativa (byte 3 do step) e nao precisa de captura: fixa.
        titulo("PROBABILITY")
        fileira("PROB %", "prob", (10, 100),
                lambda i, val: self.motor.enfileirar(
                    self.motor.definir_prob_inst, i, val)
                if self.motor else self.log("(!) ligue o modo ON primeiro"))

        grupos = {}
        for nome, ent in mapa.items():
            grupos.setdefault(ent.get("grupo", "OUTROS"), []).append(nome)
        for grupo in sorted(grupos):
            titulo(grupo)
            for nome in sorted(grupos[grupo]):
                ent = mapa[nome]
                faixa = (ent.get("min", 0), ent.get("max", 127))
                if ent.get("forma") == "enum":
                    self._fx_linha_enum(nome, ent)
                elif ent["tipo"] == "inst":
                    fileira(nome, nome, faixa,
                            lambda i, val, n=nome: self.motor.enfileirar(
                                self.motor.definir_fx, n, val, i), ent=ent)
                else:
                    self._fx_linha_kit(nome, ent, faixa)

    def _fx_linha_kit(self, nome, ent, faixa):
        bloco = tk.Frame(self.quadro_fx, bg=BG)
        bloco.pack(fill="x", pady=1, anchor="w")
        tk.Label(bloco, text=nome, bg=BG, fg=INK, width=14, anchor="w",
                 font=("Helvetica", 11, "bold")).pack(side="left")
        rot = tk.Label(bloco, text="—", bg=BG, fg=MUTED, font=("Menlo", 10),
                       width=6)
        v = tk.DoubleVar(value=faixa[0])
        esc = ttk.Scale(bloco, variable=v, from_=faixa[0], to=faixa[1],
                        orient="horizontal", length=280)
        esc.pack(side="left", padx=4)
        rot.pack(side="left")
        esc.bind("<ButtonPress-1>",
                 lambda ev: setattr(self, "_fx_arrastando", True))
        esc.bind("<ButtonRelease-1>",
                 lambda ev, n=nome, vv=v: (
                     setattr(self, "_fx_arrastando", False),
                     self.motor.enfileirar(self.motor.definir_fx, n,
                                           int(round(vv.get())))
                     if self.motor else None))
        v.trace_add("write", lambda *a, vv=v, r=rot, en=ent:
                    r.config(text=E.rotulo_valor(en, int(round(vv.get())))))
        self.fx_vars[(nome, None)] = v
        self.fx_rotulos[(nome, None)] = rot

    def _fx_linha_enum(self, nome, ent):
        """Lista de opcoes: so mostra o que ja foi ANOTADO (codigo -> rotulo).
        Sem opcao anotada, a linha diz como anotar - nao inventa nome."""
        bloco = tk.Frame(self.quadro_fx, bg=BG)
        bloco.pack(fill="x", pady=1, anchor="w")
        sufixo = "" if ent["tipo"] == "kit" else "  (do inst. escolhido)"
        tk.Label(bloco, text=nome, bg=BG, fg=INK, width=14, anchor="w",
                 font=("Helvetica", 11, "bold")).pack(side="left")
        opcoes = ent.get("opcoes", {})
        var = tk.StringVar()
        cb = ttk.Combobox(bloco, textvariable=var, width=14, state="readonly",
                          values=[opcoes[k] for k in
                                  sorted(opcoes, key=lambda x: int(x))])
        cb.pack(side="left", padx=4)
        tk.Label(bloco, text=(f"{len(opcoes)} opções anotadas" if opcoes
                              else "nenhuma opção anotada ainda") + sufixo,
                 bg=BG, fg=MUTED, font=("Helvetica", 10)).pack(side="left",
                                                               padx=4)
        cb.bind("<<ComboboxSelected>>",
                lambda ev, n=nome, en=ent, vv=var: self._fx_enum_escolher(
                    n, en, vv.get()))
        self.fx_combos[nome] = (var, ent)

    def _fx_enum_escolher(self, nome, ent, rotulo):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        codigo = next((int(k) for k, v in ent.get("opcoes", {}).items()
                       if v == rotulo), None)
        if codigo is None:
            return
        inst = (None if ent["tipo"] == "kit"
                else L.INSTRUMENTOS.index(self.var_fx_inst.get()))
        self.motor.enfileirar(self.motor.definir_fx, nome, codigo, inst)

    def _fx_povoar_catalogo(self, mapa):
        """Lista dos parametros do catalogo que ainda faltam mapear."""
        self.lista_cat.delete(0, "end")
        self._cat_pendentes = E.pendentes(mapa)
        for p in self._cat_pendentes:
            self.lista_cat.insert("end", f"{p['grupo']:9} {p['nome']}")
        enums = [n for n, e in mapa.items() if e.get("forma") == "enum"]
        self.cb_op_param.config(values=sorted(enums))
        if self.var_op_param.get() not in enums:
            self.var_op_param.set(enums[0] if enums else "")

    def _fx_dica(self):
        sel = self.lista_cat.curselection()
        if not sel:
            return
        p = self._cat_pendentes[sel[0]]
        self.rotulo_fx.config(
            text=f"{p['nome']} — no painel: {p['dica']}\n"
                 + ("é uma LISTA: capture primeiro, depois anote cada opção "
                    "abaixo" if p["forma"] == "enum" else
                    ("2 bytes: gire de ponta a ponta para eu achar o par"
                     if p.get("bytes") == 2 else "1 byte")))

    def _fx_nome_alvo(self):
        digitado = self.var_fx_nome.get().strip()
        if digitado:
            return digitado
        sel = self.lista_cat.curselection()
        return self._cat_pendentes[sel[0]]["nome"] if sel else ""

    def _fx_capturar(self):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        if self.ultimo_estado.get("captura_fx"):
            self.motor.enfileirar(self.motor.cancelar_captura_fx)
            return
        nome = self._fx_nome_alvo()
        if not nome:
            self.log("(!) escolha um parâmetro na lista (ou digite um nome)")
            return
        self.motor.enfileirar(self.motor.iniciar_captura_fx, nome)

    def _fx_sugestoes(self):
        """Rotulos que o manual conhece para o enum escolhido."""
        nome = self.var_op_param.get()
        mapa = self._fx_montados or {}
        ent = mapa.get(nome, {})
        sug = list(ent.get("sugestoes") or
                   E.POR_NOME.get(nome, {}).get("opcoes", []))
        self.cb_op_rotulo.config(values=sug)
        if sug and self.var_op_rotulo.get() not in sug:
            self.var_op_rotulo.set(sug[0])

    def _fx_anotar(self):
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        nome = self.var_op_param.get()
        if not nome:
            self.log("(!) capture o parâmetro de lista primeiro"); return
        ent = (self._fx_montados or {}).get(nome, {})
        inst = (None if ent.get("tipo") == "kit"
                else L.INSTRUMENTOS.index(self.var_fx_inst.get()))
        self.motor.enfileirar(self.motor.anotar_opcao, nome,
                              self.var_op_rotulo.get(), inst)

    def _pintar_mixer(self, e):
        # captura em andamento vira botao "Cancelar" aceso
        cap = e.get("captura_fx")
        quer = f"Cancelar '{cap}'" if cap else "Capturar"
        if self.b_capturar.itemcget(self.b_capturar.rotulo, "text") != quer:
            self.b_capturar.itemconfig(self.b_capturar.rotulo, text=quer)
            self.b_capturar.definir_ativo(bool(cap))
        mapa = e.get("mapa_fx") or {}
        if mapa != self._fx_montados:
            self._fx_remontar(mapa)
            self._fx_povoar_catalogo(mapa)
            self._fx_sugestoes()
        if self._fx_arrastando:
            return                      # nao puxa o fader da mao do usuario
        fx = e.get("fx") or {}
        for i, p in enumerate(e.get("probs_inst") or []):
            var = self.fx_vars.get(("prob", i))
            if var is None:
                continue
            if p is None:
                self.fx_rotulos[("prob", i)].config(text="—")
            elif int(round(var.get())) != p:
                var.set(p)
        inst_sel = L.INSTRUMENTOS.index(self.var_fx_inst.get())
        for nome, ent in mapa.items():
            val = fx.get(nome)
            if nome in self.fx_combos:      # lista: mostra o rotulo anotado
                var, en = self.fx_combos[nome]
                v = val[inst_sel] if isinstance(val, list) else val
                # so mostra se o codigo atual ja tiver sido anotado; senao
                # deixa vazio - inventar nome aqui seria mentira
                rot = en.get("opcoes", {}).get(str(v), "") if v is not None else ""
                if var.get() != rot:
                    var.set(rot)
                continue
            if isinstance(val, list):
                for i, vi in enumerate(val):
                    var = self.fx_vars.get((nome, i))
                    if var is None or vi is None:
                        continue
                    if int(round(var.get())) != vi:
                        var.set(vi)
            elif val is not None:
                var = self.fx_vars.get((nome, None))
                if var is not None and int(round(var.get())) != val:
                    var.set(val)

    # ── acoes ───────────────────────────────────────────────
    def log(self, texto):
        self.fila_log.put(str(texto))

    def _garantir_motor(self):
        if self.motor:
            return True
        if not os.path.exists(L.LAYOUT_FILE):
            self.log("(!) Nenhum layout salvo. Aperte Recalibrar."); return False
        try:
            with open(L.LAYOUT_FILE) as f:
                cfg = json.load(f)
        except Exception as e:
            self.log(f"(!) layout ilegivel: {e}"); return False
        atual_in  = [n for _, n in L.listar_portas(True)]
        atual_out = [n for _, n in L.listar_portas(False)]
        if cfg.get("_portas_in") != atual_in or cfg.get("_portas_out") != atual_out:
            self.log("(!) As portas MIDI mudaram desde o 'learn' (replug?). "
                     "Aperte Recalibrar - escrever agora poderia cair no "
                     "aparelho errado.")
            return False
        try:
            L._programmer_mode(True)
            self.motor = L.Motor(cfg, log=self.log)
        except Exception as e:
            self.log(f"(!) nao consegui abrir os Launchpad: {e}"); return False
        self.rodando = True
        self.thread = threading.Thread(target=self._laco_motor, daemon=True)
        self.thread.start()
        return True

    def _laco_motor(self):
        while self.rodando:
            try:
                self.motor.tick()
            except Exception as e:
                self.log(f"(!) erro no motor: {e}")
                time.sleep(0.5)
            time.sleep(0.003)

    def trocar_modo(self, modo, estilo=None):
        if not self._garantir_motor():
            return
        # via fila: o primeiro ON faz recarregar() (2 s lendo a maquina), e
        # isso nao pode rodar na thread do Tk
        self.motor.enfileirar(self.motor.definir_modo, modo, estilo)

    def recalibrar(self):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "lp_tr8s.py")
        self.log("Abrindo o Terminal pro 'learn' (ele faz perguntas, e isso "
                 "ainda nao cabe nesta janela).")
        self._parar_motor()
        subprocess.Popen(["osascript", "-e",
                          f'tell app "Terminal" to do script '
                          f'"python3 \\"{script}\\" learn"',
                          "-e", 'tell app "Terminal" to activate'])

    def blackout(self):
        """Escuro de verdade e solta os aparelhos - diferente do modo off, que
        continua ouvindo os pads pra fazer ondinha."""
        self._parar_motor()
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "apagar_luzes.py")
        subprocess.Popen([sys.executable, script])
        self.log("LEDs apagados e pads soltos.")

    def _parar_motor(self):
        if not self.motor:
            return
        self.rodando = False
        if self.thread: self.thread.join(timeout=1.0)
        try: self.motor.fechar()
        except Exception: pass
        self.motor, self.thread, self.ultimo_estado = None, None, {}

    def sair(self):
        self._parar_motor()
        self.raiz.destroy()

    # ── aba Instrumento (o gesto INST do TR-EDITOR) ─────────
    # categoria natural de cada linha; o seletor deixa trocar (qualquer tone
    # entra em qualquer track na TR-8S). Aba fixa, nao Toplevel: o Tk 8.5.9
    # Aqua trava ao atualizar um Toplevel recem-criado.
    CAT_INST = {0: "BD", 1: "SD", 2: "TOM", 3: "TOM", 4: "TOM", 5: "RS",
                6: "HC", 7: "CH_OH", 8: "CH_OH", 9: "CC_RC", 10: "CC_RC"}

    def _montar_instrumento(self, pai):
        self._tone_inst = 0
        self._silencio_tone = False

        linha = tk.Frame(pai, bg=BG); linha.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(linha, text="instrumento", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        self.var_tone_inst = tk.StringVar(value=L.INSTRUMENTOS[0])
        ttk.Combobox(linha, textvariable=self.var_tone_inst, width=4,
                     state="readonly", values=L.INSTRUMENTOS
                     ).pack(side="left", padx=(4, 14))
        self.var_tone_inst.trace_add(
            "write", lambda *a: (not self._silencio_tone and self._abrir_tones(
                L.INSTRUMENTOS.index(self.var_tone_inst.get()), trocar_aba=False)))
        tk.Label(linha, text="categoria", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(side="left")
        self.var_tone_cat = tk.StringVar(value=self.CAT_INST[0])
        ttk.Combobox(linha, textvariable=self.var_tone_cat, width=10,
                     state="readonly", values=list(T.por_categoria())
                     ).pack(side="left", padx=(4, 14))
        self.var_tone_cat.trace_add("write", lambda *a: self._tone_povoar())
        BotaoCanvas(linha, "Reler kit",
                    lambda: self.motor.enfileirar(self.motor.ler_kit)
                    if self.motor else self.log("(!) ligue o modo ON primeiro"),
                    largura=90, altura=30, cor_ativa=CARD,
                    fonte=("Helvetica", 11)).pack(side="left")

        self.rotulo_tone_atual = tk.Label(pai, text="", bg=BG, fg=INK,
                                          font=("Menlo", 11), anchor="w",
                                          justify="left", wraplength=680)
        self.rotulo_tone_atual.pack(fill="x", padx=8, pady=2)

        quadro = tk.Frame(pai, bg=BG); quadro.pack(fill="both", expand=True,
                                                   padx=8, pady=4)
        barra = tk.Scrollbar(quadro)
        self.lista_tones = tk.Listbox(
            quadro, bg=CARD, fg=INK, font=("Menlo", 11), bd=0, height=14,
            highlightthickness=0, selectbackground=LINHA,
            selectforeground=INK, yscrollcommand=barra.set)
        barra.config(command=self.lista_tones.yview)
        barra.pack(side="right", fill="y")
        self.lista_tones.pack(side="left", fill="both", expand=True)
        self.lista_tones.bind("<Double-Button-1>",
                              lambda e: self._tone_aplicar())

        rodape = tk.Frame(pai, bg=BG); rodape.pack(fill="x", padx=8, pady=4)
        BotaoCanvas(rodape, "Aplicar (duplo clique também)",
                    self._tone_aplicar, largura=230, altura=36,
                    cor_ativa=VERDE, fonte=("Helvetica", 12)
                    ).pack(side="left")
        self.rotulo_tone_aviso = tk.Label(
            pai, text="", bg=BG, fg=AMARELO, font=("Helvetica", 10),
            wraplength=680, justify="left")
        self.rotulo_tone_aviso.pack(fill="x", padx=8, pady=(0, 8))
        self._abrir_tones(0, trocar_aba=False)

    def _abrir_tones(self, i, trocar_aba=True):
        self._tone_inst = i
        self._silencio_tone = True
        self.var_tone_inst.set(L.INSTRUMENTOS[i])
        self._silencio_tone = False
        self.var_tone_cat.set(self.CAT_INST[i])   # o trace repovoa a lista
        self.rotulo_tone_aviso.config(
            text="id → nome é HIPÓTESE (posição na Preset Tone List); a "
                 "escrita nunca foi testada — toque o pad e confira o som e "
                 "o visor. CTRL e INST FX ainda não foram decodificados: é a "
                 f"sessão `python3 lp_tr8s.py kit_watch {L.INSTRUMENTOS[i]}` "
                 "(mexa num knob por vez, com o .app fechado).")
        self._tone_atualizar_atual()
        if trocar_aba:
            self.abas.select(self.aba_inst)

    def _tone_povoar(self):
        self.lista_tones.delete(0, "end")
        self._tone_posicoes = []
        for pos, nome, tipo in T.por_categoria().get(self.var_tone_cat.get(),
                                                     []):
            self._tone_posicoes.append(pos)
            self.lista_tones.insert(
                "end", f"{T.tone_id(pos):4}  {nome}  ({tipo})")

    def _tone_atualizar_atual(self):
        i = self._tone_inst
        tid = (self.ultimo_estado.get("tone_ids") or
               [None] * len(L.INSTRUMENTOS))[i]
        kit = self.ultimo_estado.get("kit_nome") or "?"
        if tid is None:
            texto = f"kit '{kit}' · {L.INSTRUMENTOS[i]}: tone ainda nao lido"
        else:
            nome = T.nome_do_id(tid) or "fora da lista de presets (sample?)"
            texto = f"kit '{kit}' · {L.INSTRUMENTOS[i]}: id {tid} = {nome}"
        if self.rotulo_tone_atual.cget("text") != texto:
            self.rotulo_tone_atual.config(text=texto)

    def _tone_aplicar(self):
        sel = self.lista_tones.curselection()
        if not sel:
            self.log("(!) escolha um tone na lista"); return
        if not self.motor:
            self.log("(!) ligue o modo ON primeiro"); return
        pos = self._tone_posicoes[sel[0]]
        self.motor.enfileirar(self.motor.definir_tone, self._tone_inst,
                              T.tone_id(pos))

    # ── laco da UI ──────────────────────────────────────────
    def _atualizar_status(self):
        """Pinta os tres LEDs de porta.

        Com o motor vivo, quem responde e ele - ja tem as portas abertas.
        Sem motor, UMA enumeracao serve aos tres pontos. Enumerar porta cria e
        destroi um cliente CoreMIDI; a primeira versao disto fazia quatro
        enumeracoes a cada 2 s, e um app esquecido aberto passa o dia inteiro
        fazendo isso."""
        if self.motor:
            e = self.ultimo_estado
            ctrl, clock, lp = e.get("tem_tr8s"), e.get("tem_clock"), True
        else:
            nomes = [n.upper() for _, n in L.listar_portas(True)]
            ctrl = any(L.TR8S_MATCH.upper() in n for n in nomes)
            clock = any("TR-8S" in n and L.TR8S_MATCH.upper() not in n
                        for n in nomes)
            lp = sum(1 for n in nomes if L.LP_MATCH.upper() in n) >= 2
        for chave, bom in (("ctrl", ctrl), ("lp", lp), ("clock", clock)):
            self.pontos[chave].itemconfig(1, fill=VERDE if bom else VERMELHO)

    def _laco_ui(self):
        # log: tudo vai pro arquivo; o rodape mostra a ultima linha
        ultima = None
        while True:
            try:
                ultima = self.fila_log.get_nowait()
            except queue.Empty:
                break
            self.arquivo_log.escrever(ultima)
        if ultima is not None:
            self.rotulo_log.config(text=ultima)

        # LEDs de porta: a versao anterior so checava no __init__ - plugar o
        # launchpad depois deixava os pontos vermelhos pra sempre. 10 s e
        # bastante: e um LED de presenca, nao um medidor.
        if time.time() - self._t_status > 10.0:
            self._t_status = time.time()
            self._atualizar_status()

        if self.motor:
            # sem bloquear: se o motor estiver ocupado lendo a maquina, pula o
            # quadro em vez de congelar a janela
            try:
                e = self.motor.estado()
            except Exception:
                e = None
            if e:
                self.ultimo_estado = e
                self._pintar_ui(e)
        else:
            self._pintar_modos(None)

        self.raiz.after(50, self._laco_ui)

    def _pintar_modos(self, ativo, estilo=None):
        for chave, modo, est in (("on", L.MODO_ON, None),
                                 ("off", L.MODO_OFF, None),
                                 ("chuva", L.MODO_STANDBY, L.ESTILO_CHUVA),
                                 ("ambiente", L.MODO_STANDBY,
                                  L.ESTILO_AMBIENTE)):
            lig = modo == ativo and (est is None or est == estilo)
            self.b_modo[chave].definir_ativo(lig)

    def _pintar_ui(self, e):
        self._pintar_modos(e["modo_geral"], e.get("estilo_standby"))
        if e["modo_geral"] == L.MODO_ON:
            mudos = [n for n, m in zip(L.INSTRUMENTOS, e["mudo"]) if m]
            vt = e.get("variacao_tocando")
            fora = (vt is not None and vt != e["variacao"])
            self.rotulo_estado.config(
                text=(f"Variação {e['variacao_nome']}"
                      + (f" (tocando a {L.VARIACOES[vt-1]})" if fora else "")
                      + f" · vel {e['velocidade']} · "
                      f"{e['modo']} · {e['visiveis']}"
                      + (f"  ·  last {e['last_var']}" if e["last_var"] < 16
                         else "")
                      + (("  ·  mute " + " ".join(mudos)
                          + (" (fora do grid)" if e["esconder_mudos"] else ""))
                         if mudos else "")))
        elif e["modo_geral"] == L.MODO_STANDBY:
            self.rotulo_estado.config(
                text=f"standby · {e['estilo_standby']} — as ondas nascem "
                     "sozinhas; a TR-8S não é tocada")
        else:
            self.rotulo_estado.config(
                text="os pads só fazem ondinha — a TR-8S não é tocada")

        # so a aba visivel e repintada
        try:
            aba = self.abas.index(self.abas.select())
        except tk.TclError:
            aba = 0
        if aba == 0:
            self._pintar_mixer(e)
        elif aba == 1:
            self._tone_atualizar_atual()
        elif aba == 4:
            self._pintar_estocastica(e)
        elif aba == 3:
            ch = e.get("chain")
            if not ch:
                texto = "chain desarmado"
            else:
                pos, tot = ch["posicao"], ch["total"]
                nome = (self._chain_entradas[pos][0]
                        if pos < len(self._chain_entradas) else "?")
                texto = (("ATIVO" if ch["ativo"] else "parado")
                         + f" · {pos+1}/{tot}: {nome}"
                         + f" · faltam {ch['reps_restantes']} ciclos")
            if self.rotulo_chain.cget("text") != texto:
                self.rotulo_chain.config(text=texto)
        elif aba == 5:
            p, k = e.get("pattern_atual"), e.get("kit_atual")
            nome_p = (f"{'ABCDEFGH'[p // 16]}{p % 16 + 1}"
                      if p is not None and p < 128 else "?")
            texto = (f"pattern atual: {nome_p}  ·  kit atual: "
                     f"{k + 1 if k is not None else '?'}")
            if self.rotulo_avanc.cget("text") != texto:
                self.rotulo_avanc.config(text=texto)


def main():
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
