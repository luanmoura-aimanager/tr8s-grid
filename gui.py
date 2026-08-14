#!/usr/bin/env python3
"""
gui.py - janela do TR-8S Grid.

Abre compacta: status das portas, o ON/OFF, e quatro secoes fechadas que voce
abre quando precisa. Rode o criar_app.py pra ter um icone no Desktop em vez de
digitar isto.

Dois modos, exclusivos entre si:
    ON    o grid escreve na TR-8S (precisa da porta CTRL)
    off   LEDs apagados; os pads so fazem ondinha

O modo off NAO precisa da TR-8S ligada.

O motor roda numa thread propria e a janela le o estado dele a 20 fps. Isso e
necessario, nao enfeite: trocar de variacao bloqueia ate 2 s lendo a maquina, e
na thread do Tk isso congelaria a janela inteira.
"""
import os, sys, time, json, threading, queue, subprocess
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_tr8s as L

BG, CARD, INK, MUTED, LINHA = "#141210", "#1e1b18", "#ece8e2", "#9a938a", "#33302c"
VERDE, VERMELHO, AMARELO = "#4ade80", "#f87171", "#fbbf24"

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


class Secao(ttk.Frame):
    """Bloco que abre e fecha. Comeca fechado."""

    def __init__(self, pai, titulo, construir):
        super().__init__(pai)
        self.aberto = False
        self.botao = tk.Button(self, text=f"▸  {titulo}", anchor="w", bd=0,
                               bg=CARD, fg=INK, activebackground=LINHA,
                               activeforeground=INK, highlightthickness=0,
                               font=("Helvetica", 12), padx=10, pady=6,
                               command=self.alternar)
        self.botao.pack(fill="x")
        self.corpo = tk.Frame(self, bg=BG)
        self.titulo = titulo
        construir(self.corpo)

    def alternar(self):
        self.aberto = not self.aberto
        self.botao.config(text=f"{'▾' if self.aberto else '▸'}  {self.titulo}")
        if self.aberto:
            self.corpo.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        else:
            self.corpo.forget()
        self.winfo_toplevel().geometry("")     # deixa a janela voltar a encolher


class App:
    def __init__(self, raiz):
        self.raiz = raiz
        raiz.title("TR-8S Grid")
        raiz.configure(bg=BG)

        self.motor = None
        self.thread = None
        self.rodando = False
        self.fila_log = queue.Queue()
        self.ultimo_estado = {}

        estilo = ttk.Style()
        try: estilo.theme_use("clam")
        except tk.TclError: pass
        estilo.configure("TFrame", background=BG)
        estilo.configure("TLabel", background=BG, foreground=INK)

        self._montar()
        self._atualizar_status()
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
        self.b_on = tk.Button(botoes, text="ON", width=9, bd=0, pady=12,
                              font=("Helvetica", 15, "bold"),
                              command=lambda: self.trocar_modo(L.MODO_ON))
        self.b_off = tk.Button(botoes, text="off", width=9, bd=0, pady=12,
                               font=("Helvetica", 15),
                               command=lambda: self.trocar_modo(L.MODO_OFF))
        for b in (self.b_on, self.b_off):
            b.pack(side="left", padx=(0, 8))
            b.config(highlightthickness=0, activeforeground=INK)

        self.rotulo_estado = tk.Label(self.raiz, text="—", bg=BG, fg=MUTED,
                                      font=("Helvetica", 11), anchor="w")
        self.rotulo_estado.pack(fill="x", padx=12, pady=(2, 6))

        aux = tk.Frame(self.raiz, bg=BG); aux.pack(fill="x", padx=12, pady=(0, 8))
        for texto, cmd in (("Recalibrar", self.recalibrar),
                           ("Apagar e soltar os pads", self.blackout)):
            tk.Button(aux, text=texto, bd=0, bg=CARD, fg=MUTED, padx=10, pady=5,
                      highlightthickness=0, activebackground=LINHA,
                      activeforeground=INK, font=("Helvetica", 11),
                      command=cmd).pack(side="left", padx=(0, 8))

        for titulo, construtor in (("Grid 16×8", self._sec_grid),
                                   ("Pattern da TR-8S", self._sec_pattern),
                                   ("Last steps e linhas", self._sec_last),
                                   ("Log", self._sec_log)):
            Secao(self.raiz, titulo, construtor).pack(fill="x", padx=8, pady=1)

    def _sec_grid(self, pai):
        self.cv_grid = tk.Canvas(pai, width=16*22, height=8*22, bg=BG,
                                 highlightthickness=0)
        self.cv_grid.pack()
        self.cel_grid = [[self.cv_grid.create_rectangle(
            c*22+1, l*22+1, c*22+20, l*22+20, fill="#1a1a1a", outline="")
            for c in range(16)] for l in range(8)]

    def _sec_pattern(self, pai):
        tk.Label(pai, text="a maquina inteira, inclusive as linhas fora do grid",
                 bg=BG, fg=MUTED, font=("Helvetica", 10)).pack(anchor="w",
                                                               pady=(0, 4))
        n = len(L.INSTRUMENTOS) + 1                    # + ACCENT
        self.cv_ptn = tk.Canvas(pai, width=34 + 16*16, height=n*16 + 4, bg=BG,
                                highlightthickness=0)
        self.cv_ptn.pack()
        self.cel_ptn = []
        for r in range(n):
            nome = L.INSTRUMENTOS[r] if r < len(L.INSTRUMENTOS) else "ACC"
            self.cv_ptn.create_text(2, r*16 + 8, text=nome, anchor="w",
                                    fill=MUTED, font=("Menlo", 9))
            self.cel_ptn.append([self.cv_ptn.create_rectangle(
                34 + c*16, r*16 + 2, 34 + c*16 + 13, r*16 + 13,
                fill="#1a1a1a", outline="") for c in range(16)])
        self.regua_ptn = self.cv_ptn.create_line(0, 0, 0, 0, fill=AMARELO)

    def _sec_last(self, pai):
        tk.Label(pai, text="lido da maquina de verdade; mexer aqui escreve nela "
                 "(os Fill In ainda nao, ver REFERENCIA 2.3.1)", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).grid(row=0, column=0, columnspan=6,
                                              sticky="w", pady=(0, 6))
        tk.Label(pai, text="mute = o mute da própria TR-8S, lido e escrito. "
                 "No launchpad, o botão da borda esquerda esconde as linhas "
                 "mutadas", bg=BG, fg=MUTED,
                 font=("Helvetica", 10)).grid(row=1, column=0, columnspan=6,
                                              sticky="w", pady=(0, 6))
        tk.Label(pai, text="variação", bg=BG, fg=INK,
                 font=("Helvetica", 11)).grid(row=2, column=0, sticky="w")
        self.var_last = tk.StringVar(value="16")
        ttk.Combobox(pai, textvariable=self.var_last, width=4, state="readonly",
                     values=[str(i) for i in range(1, 17)]).grid(row=2, column=1,
                                                                 sticky="w", padx=6)
        self.var_last.trace_add("write", lambda *a: self._aplicar_last_var())

        self.var_track, self.var_mudo = [], []
        for i, nome in enumerate(L.INSTRUMENTOS):
            lin, col = 3 + i % 6, (i // 6) * 3
            tk.Label(pai, text=nome, bg=BG, fg=INK, width=3,
                     font=("Menlo", 11)).grid(row=lin, column=col, sticky="w",
                                              pady=1)
            v = tk.StringVar(value="—")
            ttk.Combobox(pai, textvariable=v, width=4, state="readonly",
                         values=["—"] + [str(k) for k in range(1, 17)]
                         ).grid(row=lin, column=col+1, padx=(0, 4))
            v.trace_add("write", lambda *a, k=i: self._aplicar_last_track(k))
            self.var_track.append(v)
            # mute: espelho do que a TR-8S diz, e clicavel - a escrita foi testada
            # em hardware e silencia de verdade. No launchpad mutar continua sendo
            # no painel, mas aqui a caixa ja existia e tirar seria regressao.
            mv = tk.BooleanVar(value=False)
            tk.Checkbutton(pai, variable=mv, bg=BG, fg=MUTED,
                           selectcolor=CARD, activebackground=BG,
                           activeforeground=INK, highlightthickness=0, bd=0,
                           text="mute", font=("Helvetica", 10),
                           command=lambda k=i: self._aplicar_mudo(k)
                           ).grid(row=lin, column=col+2, sticky="w", padx=(0, 14))
            self.var_mudo.append(mv)
        self._silencio_ui = False

    def _sec_log(self, pai):
        self.txt = tk.Text(pai, height=10, width=52, bg="#0f0d0c", fg=INK, bd=0,
                           font=("Menlo", 10), highlightthickness=0, wrap="none")
        self.txt.pack(fill="both", expand=True)
        self.txt.config(state="disabled")

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

    def trocar_modo(self, modo):
        if not self._garantir_motor():
            return
        self.motor.definir_modo(modo)

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

    def _aplicar_last_var(self):
        if self.motor and not getattr(self, "_silencio_ui", False):
            self.motor.definir_last_var(int(self.var_last.get()))

    def _aplicar_last_track(self, i):
        if self.motor and not getattr(self, "_silencio_ui", False):
            v = self.var_track[i].get()
            self.motor.definir_last_track(i, None if v == "—" else int(v))

    def _aplicar_mudo(self, i):
        if not self.motor or not self.motor.tr_out:
            self.var_mudo[i].set(not self.var_mudo[i].get()); return
        if self.var_mudo[i].get() == self.motor.mudo[i]:
            return
        m = sum(1 << k for k in range(len(L.INSTRUMENTOS))
                if (self.var_mudo[k].get() if k == i else self.motor.mudo[k]))
        self.motor.definir_mudos(m)

    # ── laco da UI ──────────────────────────────────────────
    def _atualizar_status(self):
        ctrl = L.achar_portas(L.TR8S_MATCH)
        lps  = L.achar_portas(L.LP_MATCH)
        clk  = L._porta_clock()
        for chave, bom in (("ctrl", bool(ctrl)), ("lp", len(lps) >= 4),
                           ("clock", bool(clk))):
            self.pontos[chave].itemconfig(1, fill=VERDE if bom else VERMELHO)

    def _laco_ui(self):
        while True:
            try: linha = self.fila_log.get_nowait()
            except queue.Empty: break
            if hasattr(self, "txt"):
                self.txt.config(state="normal")
                self.txt.insert("end", linha + "\n")
                self.txt.see("end")
                if float(self.txt.index("end")) > 500:
                    self.txt.delete("1.0", "200.0")
                self.txt.config(state="disabled")

        if self.motor:
            # sem bloquear: se o motor estiver ocupado lendo a maquina, pula o
            # quadro em vez de congelar a janela
            try: e = self.motor.estado()
            except Exception: e = None
            if e:
                self.ultimo_estado = e
                self._pintar_ui(e)
        else:
            self._pintar_modos(None)

        self.raiz.after(50, self._laco_ui)

    def _pintar_modos(self, ativo):
        for modo, b in ((L.MODO_ON, self.b_on), (L.MODO_OFF, self.b_off)):
            lig = modo == ativo
            b.config(bg=(VERDE if modo == L.MODO_ON else "#6b7280")
                     if lig else CARD,
                     fg="#0b0b0b" if lig else MUTED,
                     activebackground=LINHA)

    def _pintar_ui(self, e):
        self._pintar_modos(e["modo_geral"])
        if e["modo_geral"] == L.MODO_ON:
            mudos = [n for n, m in zip(L.INSTRUMENTOS, e["mudo"]) if m]
            vt = e.get("variacao_tocando")
            fora = (vt is not None and vt != e["variacao"])
            self.rotulo_estado.config(
                text=(f"Variação {e['variacao_nome']}"
                      + (f" (tocando a {L.VARIACOES[vt-1]})" if fora else "")
                      + f" · vel {e['velocidade']} · "
                     f"{e['modo']} · {e['visiveis']}"
                     + (f"  ·  last {e['last_var']}" if e["last_var"] < 16 else "")
                     + (("  ·  mute " + " ".join(mudos)
                         + (" (fora do grid)" if e["esconder_mudos"] else ""))
                        if mudos else "")))
        else:
            self.rotulo_estado.config(
                text="os pads só fazem ondinha — a TR-8S não é tocada")

        # espelho dos controles, sem disparar os callbacks de volta
        self._silencio_ui = True
        if hasattr(self, "var_last"):
            if self.var_last.get() != str(e["last_var"]):
                self.var_last.set(str(e["last_var"]))
            for i, v in enumerate(e["last_track"]):
                alvo = "—" if v is None else str(v)
                if self.var_track[i].get() != alvo:
                    self.var_track[i].set(alvo)
            for i, v in enumerate(e["mudo"]):
                if self.var_mudo[i].get() != v:
                    self.var_mudo[i].set(v)
        self._silencio_ui = False

        if hasattr(self, "cv_grid"):
            pads = e.get("pads")
            for l in range(8):
                for c in range(16):
                    cor = "#1a1a1a" if pads is None else cor_hex(pads[l][c])
                    self.cv_grid.itemconfig(self.cel_grid[l][c], fill=cor)

        if hasattr(self, "cv_ptn"):
            ptn, subs = e.get("pattern", {}), e.get("subs", {})
            alts = e.get("alts", {})
            for i in range(len(L.INSTRUMENTOS)):
                lim = min(e["last_var"], e["last_track"][i] or 16)
                for s in range(16):
                    v = ptn.get(i, [0]*16)[s]
                    sub = subs.get(i, [0]*16)[s]
                    alt = alts.get(i, [0]*16)[s]
                    # mesma paleta do launchpad, que espelha o painel da TR-8S:
                    # nota vermelha, flam lilas, sub amarelo, ALT rosa, linha
                    # mutada em cinza-azulado (ver o bloco de cores do lp_tr8s.py)
                    if s >= lim:                     cor = "#101010"
                    elif v == 0:                     cor = "#232323"
                    elif e["mudo"][i]:               cor = "#38445c"
                    elif alt:                        cor = "#ff3450"
                    elif sub == L.SUB_FLAM:          cor = "#c47cff"
                    elif sub:                        cor = "#ffe000"
                    else:                            cor = "#ff3b30"
                    self.cv_ptn.itemconfig(self.cel_ptn[i][s], fill=cor)
            r = len(L.INSTRUMENTOS)
            for s in range(16):
                lig = e["acc"] & (1 << s)
                self.cv_ptn.itemconfig(
                    self.cel_ptn[r][s],
                    fill="#ffe600" if lig else ("#101010" if s >= e["last_var"]
                                                else "#232323"))
            x = 34 + e["last_var"] * 16 - 2
            self.cv_ptn.coords(self.regua_ptn, x, 0, x,
                               (len(L.INSTRUMENTOS) + 1) * 16)


def main():
    raiz = tk.Tk()
    App(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
