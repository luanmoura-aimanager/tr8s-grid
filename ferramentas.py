#!/usr/bin/env python3
"""
ferramentas.py - Chain de patterns e ferramenta estocastica (ideias do Stochas).

As duas classes NAO abrem porta nenhuma: recebem o Motor e usam os metodos
dele (escrever_step, escrever_pattern, tr_out), sempre chamadas de dentro do
tick() - ou porque o proprio tick chama (Chain) ou porque a janela enfileirou
(Estocastica). O lock ja esta com quem chama.

CHAIN - quatro variantes de troca, da mais provada para a menos:
    reescrita   reescreve o conteudo do pattern na virada do ciclo,
                perseguindo o playhead (so escreve step que ja passou).
                100%% protocolo provado - funciona HOJE.
    variacao    DT1 na mascara de variacao (offsets 63-66). Leitura provada;
                escrita depende da sessao C.
    pattern     DT1 de 1 byte em 01 00 00 02 (nextPattern, mapa oficial do
                ARIA). Depende da sessao B.
    pc          Program Change na porta comum. Plano B da sessao B.

ESTOCASTICA - o espirito do Stochas nos recursos NATIVOS da TR-8S:
    densidade       escala a probability (byte 3) dos steps ativos - o
                    "poly bias" do Stochas como knob de densidade
    humanize_vel    velocity +- aleatorio nos steps ativos
    retrig          sorteia sub steps (flam/1_2/1_3/1_4) - o retrigger
    gerar_ghosts    liga steps vazios com velocity fraca e probability baixa:
                    a MAQUINA decide a cada volta, que e a ideia do Stochas
    Seed visivel e reprodutivel (a "stable seed" do Stochas): a mesma seed
    sobre o mesmo pattern da o mesmo resultado.
"""
import random
import time

import lp_tr8s as L


class Chain:
    """Encadeia entradas [{...}, ...] e toca uma apos a outra.

    Desde a reforma 2 o despacho e POR ENTRADA (modo "misto"): cada entrada
    diz seu tipo, e grooves da biblioteca e patterns da maquina convivem na
    mesma fila.

    entrada groove:   {"tipo": "groove", "nome": str, "dados": expandir(),
                       "accent": int, "reps": int}
        -> perseguicao do playhead (escreve por tras dele; inaudivel).
        HONESTIDADE: escreve NA VARIACAO ABERTA do pattern corrente da
        maquina - vindo depois de uma entrada de pattern, altera aquele.
    entrada pattern:  {"tipo": "pattern", "alvo": 0-127, "nome": str,
                       "reps": int}
        -> nextPattern (01 00 00 02), PROVADO 15/08/2026: troca na virada.
    entrada variacao: {"tipo": "variacao", "var": 1-8, "reps": int}
        -> escrita na mascara de variacao (nao confirmada em hardware).

    Os modos antigos ("reescrita"/"variacao"/"pattern") continuam aceitos:
    viram o tipo de todas as entradas. O modo "pc" MORREU em 15/08/2026 -
    dependia de motor.comum_out, que nunca existiu.
    """

    def __init__(self, entradas, modo="misto", log=print):
        assert modo in ("misto", "reescrita", "variacao", "pattern")
        tipo_legado = {"reescrita": "groove", "variacao": "variacao",
                       "pattern": "pattern"}.get(modo)
        self.entradas = [dict(e, tipo=e.get("tipo") or tipo_legado or "groove")
                         for e in entradas]
        self.modo, self.log = modo, log
        self.idx = 0
        self.reps_restantes = self.entradas[0]["reps"] if entradas else 0
        self.ativo = False
        self._ciclo = None
        self._fila_escrita = None      # passos que faltam da perseguicao
        self._avisado_parado = False

    # ── controle ────────────────────────────────────────────
    def armar(self, motor):
        """Poe a primeira entrada no ar e comeca a contar ciclos.

        Groove e escrito ja (via escrever_pattern, que empilha o Desfazer);
        pattern/variacao sao pedidos ja."""
        if not self.entradas:
            self.log("(!) chain vazio"); return
        self.idx, self.reps_restantes = 0, self.entradas[0]["reps"]
        self._ciclo, self._fila_escrita = None, None
        ent = self.entradas[0]
        if ent["tipo"] == "groove":
            if not motor.escrever_pattern(ent["dados"], ent.get("accent", 0),
                                          nome=ent.get("nome", "chain")):
                return
        else:
            self._pedir_alvo(motor, ent)
        self.ativo = True
        self.log(f"chain armado: {len(self.entradas)} entradas, "
                 f"'{ent.get('nome', ent.get('alvo', ent.get('var', '?')))}' "
                 f"{self.reps_restantes}x")

    def parar(self):
        self.ativo = False
        self._fila_escrita = None
        self.log("chain parado")

    def resumo(self):
        return {"ativo": self.ativo, "modo": self.modo, "posicao": self.idx,
                "reps_restantes": self.reps_restantes,
                "total": len(self.entradas),
                # a fila visual da tela reconcilia com isto
                "entradas": [{"nome": e.get("nome",
                                            str(e.get("alvo",
                                                      e.get("var", "?")))),
                              "tipo": e["tipo"], "reps": e["reps"]}
                             for e in self.entradas]}

    # ── um tick do motor ────────────────────────────────────
    def tick(self, motor):
        if not self.ativo:
            return
        if not motor.tocando:
            if not self._avisado_parado:
                self._avisado_parado = True
                self.log("chain esperando a TR-8S tocar (de o play nela)")
            return
        self._avisado_parado = False
        lim = max(1, motor.last_var())
        ciclo = motor.passo_abs // lim
        if self._ciclo is None:
            self._ciclo = ciclo
            if self.reps_restantes == 1:
                self._preparar_troca(motor)
        # so conta VIRADA pra frente. Um ciclo menor que o anterior significa
        # que o passo_abs andou pra tras (correcao de fase), nao que uma
        # repeticao aconteceu - contar ali avancava o chain sem a musica ter
        # dado a volta. Ver lp_tr8s._ressincronizar, consertado em 16/08/2026
        if ciclo > self._ciclo:
            self._ciclo = ciclo
            self.reps_restantes -= 1
            if self.reps_restantes <= 0:
                self._avancar(motor)
            if self.reps_restantes == 1:
                self._preparar_troca(motor)
        elif ciclo < self._ciclo:
            self._ciclo = ciclo         # so reancora; nao conta repeticao
        if self._fila_escrita is not None:
            self._perseguir(motor)

    # ── troca ───────────────────────────────────────────────
    def _proxima(self):
        return self.entradas[(self.idx + 1) % len(self.entradas)]

    def _pedir_alvo(self, motor, ent):
        """Manda a troca de uma entrada que pede a maquina (pattern/variacao)."""
        if ent["tipo"] == "pattern":
            motor.tr_out.send(L.dt1(
                L.addr_soma(L.ADDR_PERF, L.OFF_PATTERN_PROX), [ent["alvo"]]))
            n = ent["alvo"]
            self.log(f"chain: nextPattern {L.nome_pattern(n)} "
                     "enviado (troca na virada - provado 15/08)")
        elif ent["tipo"] == "variacao":
            motor.tr_out.send(L.dt1(
                L.addr_soma(L.ADDR_PATTERN, L.OFF_VAR_TOCANDO),
                L.mascara_para_nibbles(1 << (ent["var"] - 1))))
            self.log(f"chain: variacao {L.VARIACOES[ent['var']-1]} pedida "
                     "(sessao C decide se obedece)")

    def _preparar_troca(self, motor):
        """Entrou no ULTIMO ciclo da entrada atual: encaminha a proxima.

        groove:  comeca a perseguir o playhead ja neste ciclo.
        pattern: manda o nextPattern agora - a maquina mesma troca na virada."""
        prox = self._proxima()
        if prox["tipo"] == "groove":
            self._fila_escrita = {"passo": 0, "dados": prox["dados"]}
        elif prox["tipo"] == "pattern":
            self._pedir_alvo(motor, prox)

    def _avancar(self, motor):
        self.idx = (self.idx + 1) % len(self.entradas)
        ent = self.entradas[self.idx]
        self.reps_restantes = ent["reps"]
        if ent["tipo"] == "groove":
            # o grosso foi na perseguicao do ciclo anterior; se nao houve
            # tempo (entrada de 1 ciclo), a fila nasce agora e vai em rajada
            if self._fila_escrita is None:
                self._fila_escrita = {"passo": 0, "dados": ent["dados"]}
            self._perseguir(motor, tudo=True)
            motor.acc = ent.get("accent", 0) & 0xFFFF
            # o accent vai por DT1 direto, entao consulta o guarda do espelho
            # aqui: o escrever_step do _perseguir ja se protege sozinho
            if not motor.escrita_bloqueada("chain: accent"):
                motor.tr_out.send(L.dt1(L.addr_accent_rd(motor.variacao),
                                        L.mascara_para_nibbles(motor.acc)))
            motor.pintar()
            self.log(f"chain: '{ent.get('nome', '?')}' no ar "
                     f"({self.reps_restantes}x)")
        elif ent["tipo"] == "variacao":
            self._pedir_alvo(motor, ent)
        # tipo pattern: a troca ja foi pedida no _preparar_troca; aqui so
        # conta - e se a entrada nova dura 1 ciclo, o tick chama o preparo

    def _perseguir(self, motor, tudo=False):
        """Escreve o proximo pattern por tras do playhead, 3 steps por tick.

        So escreve o step s depois que o playhead ja passou dele neste ciclo -
        o que ficou pra tras nao soa mais ate a virada, entao a troca e
        inaudivel. Com tudo=True descarrega o que faltou (a virada ja veio),
        inclusive os steps alem do last step."""
        fe = self._fila_escrita
        lim = max(1, motor.last_var())
        alvo = 16 if tudo else motor.passo_abs % lim
        escritos, s = 0, fe["passo"]
        while s < alvo and (escritos < 3 or tudo):
            for i in range(len(L.INSTRUMENTOS)):
                vel, sub, prob, alt = fe["dados"].get(
                    i, [(0, 0, 100, False)] * 16)[s]
                motor.escrever_step(i, s, vel, sub, alt,
                                    prob=prob if vel else None)
                if tudo:
                    time.sleep(0.002)
            s += 1
            escritos += 1
        fe["passo"] = s
        if s >= 16:
            self._fila_escrita = None


class Estocastica:
    """Operacoes estocasticas sobre a variacao aberta, com seed reprodutivel.

    Toda operacao EMPILHA um snapshot rotulado antes de mexer (reforma 2) -
    e assim que o "Reverter" ao lado de cada Aplicar sabe desfazer SO aquela
    edicao. insts=None opera em todos; lista de indices 0-10 restringe."""

    def __init__(self, seed=None):
        self.seed = seed
        self.rng = random.Random(seed)

    def definir_seed(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)

    @staticmethod
    def rotulo(op, insts):
        """O formato e CONTRATO com a tela: o Reverter-por-edicao compara o
        topo de desfazer_pilha com o rotulo que ele espera."""
        if not insts:
            return f"{op} todos"
        return op + " " + "+".join(L.INSTRUMENTOS[i] for i in insts)

    def _ativos(self, motor, insts=None):
        for i in range(len(L.INSTRUMENTOS)):
            if insts is not None and i not in insts:
                continue
            lim = motor.ultimo_efetivo(i)
            for s in range(16):
                if s < lim and motor.ler_vel(i, s):
                    yield i, s

    def _pronto(self, motor, op, insts):
        if motor.modo_geral != L.MODO_ON or not motor.carregado:
            motor.log("(!) estocastica so no modo ON")
            return False
        motor.snapshot_escrita(self.rotulo(op, insts))
        return True

    # ── operacoes ───────────────────────────────────────────
    def densidade(self, motor, fator, insts=None):
        """Escala a probability dos steps ativos (o poly bias do Stochas).

        fator 1.0 nao mexe; 0.5 rareia; 2.0 adensa (teto 100). A velocity
        fica intacta - so o byte 3 anda."""
        if not self._pronto(motor, "densidade", insts):
            return
        mexidos = 0
        for i, s in self._ativos(motor, insts):
            p = motor.ler_prob(i, s)
            novo = max(10, min(100, int(round(p * fator / 10.0)) * 10))
            if novo != p:
                motor.escrever_step(i, s, motor.ler_vel(i, s),
                                    motor.ler_sub(i, s), motor.ler_alt(i, s),
                                    prob=novo)
                time.sleep(0.002)
                mexidos += 1
        motor.pintar()
        motor.log(f"densidade x{fator:.2f}: {mexidos} steps "
                  "(probability nativa da maquina)")

    def humanize_vel(self, motor, alcance, insts=None):
        """Velocity +- alcance, sorteado por step ativo. Nunca desliga (>=1)."""
        if not self._pronto(motor, "humanize", insts):
            return
        for i, s in self._ativos(motor, insts):
            v = motor.ler_vel(i, s)
            novo = max(1, min(127, v + self.rng.randint(-alcance, alcance)))
            if novo != v:
                motor.escrever_step(i, s, novo, motor.ler_sub(i, s),
                                    motor.ler_alt(i, s))
                time.sleep(0.002)
        motor.pintar()
        motor.log(f"humanize +-{alcance} aplicado (seed {self.seed})")

    def retrig(self, motor, chance, tipos=(1, 2, 3, 4), insts=None):
        """Sorteia sub steps nos steps ativos - rufos/flams aleatorios.

        chance em % por step; tipos sao os codigos do byte 5 (1 flam,
        2/3/4 = sub 1/2, 1/3, 1/4)."""
        if not self._pronto(motor, "retrig", insts):
            return
        for i, s in self._ativos(motor, insts):
            if self.rng.random() * 100 < chance:
                motor.escrever_step(i, s, motor.ler_vel(i, s),
                                    self.rng.choice(list(tipos)),
                                    motor.ler_alt(i, s))
                time.sleep(0.002)
        motor.pintar()
        motor.log(f"retrig {chance}% aplicado (seed {self.seed})")

    def gerar_ghosts(self, motor, chance, insts=None):
        """Liga steps VAZIOS com velocity fraca e probability baixa.

        E a assinatura do Stochas traduzida: o pattern ganha notas que a
        propria maquina decide tocar ou nao a cada volta. So mexe em linhas
        que ja tem alguma nota - linha vazia e escolha, nao esquecimento."""
        if not self._pronto(motor, "ghosts", insts):
            return
        criados = 0
        for i in range(len(L.INSTRUMENTOS)):
            if insts is not None and i not in insts:
                continue
            lim = motor.ultimo_efetivo(i)
            if not any(motor.ler_vel(i, s) for s in range(lim)):
                continue
            for s in range(lim):
                if motor.ler_vel(i, s) == 0 and self.rng.random() * 100 < chance:
                    motor.escrever_step(i, s, L.VEL_FRACA, 0,
                                        prob=self.rng.choice((20, 30, 40)))
                    time.sleep(0.002)
                    criados += 1
        motor.pintar()
        motor.log(f"{criados} ghost notes criadas (chance {chance}%, "
                  f"seed {self.seed}) - a maquina sorteia a cada volta")

    def reverter(self, motor):
        motor.desfazer_escrita()
