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

    entrada de reescrita: {"nome": str, "dados": expandir(), "accent": int,
                           "reps": int}
    entrada de variacao:  {"var": 1-8, "reps": int}
    entrada de pattern:   {"alvo": 0-127, "reps": int}   (pattern e pc)
    """

    def __init__(self, entradas, modo="reescrita", log=print):
        assert modo in ("reescrita", "variacao", "pattern", "pc")
        self.entradas, self.modo, self.log = list(entradas), modo, log
        self.idx = 0
        self.reps_restantes = self.entradas[0]["reps"] if entradas else 0
        self.ativo = False
        self._ciclo = None
        self._fila_escrita = None      # passos que faltam da perseguicao
        self._avisado_parado = False

    # ── controle ────────────────────────────────────────────
    def armar(self, motor):
        """Poe a primeira entrada no ar e comeca a contar ciclos.

        No modo reescrita a entrada 0 e escrita ja (via escrever_pattern, que
        tira o snapshot do Desfazer); nos outros modos o alvo 0 e pedido ja."""
        if not self.entradas:
            self.log("(!) chain vazio"); return
        self.idx, self.reps_restantes = 0, self.entradas[0]["reps"]
        self._ciclo, self._fila_escrita = None, None
        ent = self.entradas[0]
        if self.modo == "reescrita":
            if not motor.escrever_pattern(ent["dados"], ent.get("accent", 0),
                                          nome=ent.get("nome", "chain")):
                return
        else:
            self._pedir_alvo(motor, ent)
        self.ativo = True
        self.log(f"chain armado: {len(self.entradas)} entradas ({self.modo}), "
                 f"'{ent.get('nome', ent.get('alvo', ent.get('var', '?')))}' "
                 f"{self.reps_restantes}x")

    def parar(self):
        self.ativo = False
        self._fila_escrita = None
        self.log("chain parado")

    def resumo(self):
        return {"ativo": self.ativo, "modo": self.modo, "posicao": self.idx,
                "reps_restantes": self.reps_restantes,
                "total": len(self.entradas)}

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
        if ciclo != self._ciclo:
            self._ciclo = ciclo
            self.reps_restantes -= 1
            if self.reps_restantes <= 0:
                self._avancar(motor)
            if self.reps_restantes == 1:
                self._preparar_troca(motor)
        if self._fila_escrita is not None:
            self._perseguir(motor)

    # ── troca ───────────────────────────────────────────────
    def _proxima(self):
        return self.entradas[(self.idx + 1) % len(self.entradas)]

    def _pedir_alvo(self, motor, ent):
        """Manda a troca de uma entrada nos modos que pedem a maquina."""
        if self.modo == "pattern":
            motor.tr_out.send(L.dt1(
                L.addr_soma(L.ADDR_PERF, L.OFF_PATTERN_PROX), [ent["alvo"]]))
            self.log(f"chain: nextPattern {ent['alvo']} enviado "
                     "(troca na virada, se a sessao B confirmar)")
        elif self.modo == "variacao":
            motor.tr_out.send(L.dt1(
                L.addr_soma(L.ADDR_PATTERN, L.OFF_VAR_TOCANDO),
                L.mascara_para_nibbles(1 << (ent["var"] - 1))))
            self.log(f"chain: variacao {L.VARIACOES[ent['var']-1]} pedida "
                     "(sessao C decide se obedece)")
        elif self.modo == "pc":
            if getattr(motor, "comum_out", None):
                motor.comum_out.send(L.mido.Message(
                    'program_change', channel=L.CANAL_TR8S,
                    program=ent["alvo"]))
                self.log(f"chain: PC {ent['alvo']} enviado")
            else:
                self.log("(!) chain pc: porta comum de saida nao aberta")

    def _preparar_troca(self, motor):
        """Entrou no ULTIMO ciclo da entrada atual: encaminha a proxima.

        reescrita: comeca a perseguir o playhead ja neste ciclo.
        pattern:   manda o nextPattern agora - se a maquina enfileira como no
                   painel, ela mesma troca na virada."""
        prox = self._proxima()
        if self.modo == "reescrita":
            self._fila_escrita = {"passo": 0, "dados": prox["dados"]}
        elif self.modo == "pattern":
            self._pedir_alvo(motor, prox)

    def _avancar(self, motor):
        self.idx = (self.idx + 1) % len(self.entradas)
        ent = self.entradas[self.idx]
        self.reps_restantes = ent["reps"]
        if self.modo == "reescrita":
            # o grosso foi na perseguicao do ciclo anterior; se nao houve
            # tempo (entrada de 1 ciclo), a fila nasce agora e vai em rajada
            if self._fila_escrita is None:
                self._fila_escrita = {"passo": 0, "dados": ent["dados"]}
            self._perseguir(motor, tudo=True)
            motor.acc = ent.get("accent", 0) & 0xFFFF
            motor.tr_out.send(L.dt1(L.addr_accent(motor.variacao),
                                    L.mascara_para_nibbles(motor.acc)))
            motor.pintar()
            self.log(f"chain: '{ent.get('nome', '?')}' no ar "
                     f"({self.reps_restantes}x)")
        elif self.modo == "variacao":
            self._pedir_alvo(motor, ent)
        elif self.modo == "pc":
            self._pedir_alvo(motor, ent)
        # no modo pattern a troca ja foi pedida no _preparar_troca; aqui so
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

    Toda operacao garante um snapshot (o mesmo buffer do desfazer da
    biblioteca) antes de mexer - Reverter e sempre um clique. Trocar de
    variacao invalida o snapshot e o proximo uso tira outro."""

    def __init__(self, seed=None):
        self.seed = seed
        self.rng = random.Random(seed)

    def definir_seed(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)

    def _garantir_snapshot(self, motor):
        d = getattr(motor, "desfazer", None)
        if d is None or d[1] != motor.variacao:
            motor.desfazer = (L.VARIACOES[motor.variacao-1], motor.variacao,
                              {i: list(dd) for i, dd in motor.cache.items()},
                              motor.acc)

    def _ativos(self, motor):
        for i in range(len(L.INSTRUMENTOS)):
            lim = motor.ultimo_efetivo(i)
            for s in range(16):
                if s < lim and motor.ler_vel(i, s):
                    yield i, s

    def _pronto(self, motor):
        if motor.modo_geral != L.MODO_ON or not motor.carregado:
            motor.log("(!) estocastica so no modo ON")
            return False
        self._garantir_snapshot(motor)
        return True

    # ── operacoes ───────────────────────────────────────────
    def densidade(self, motor, fator):
        """Escala a probability dos steps ativos (o poly bias do Stochas).

        fator 1.0 nao mexe; 0.5 rareia; 2.0 adensa (teto 100). A velocity
        fica intacta - so o byte 3 anda."""
        if not self._pronto(motor):
            return
        mexidos = 0
        for i, s in self._ativos(motor):
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
                  "(probability nativa - confira de ouvido, nao testada)")

    def humanize_vel(self, motor, alcance):
        """Velocity +- alcance, sorteado por step ativo. Nunca desliga (>=1)."""
        if not self._pronto(motor):
            return
        for i, s in self._ativos(motor):
            v = motor.ler_vel(i, s)
            novo = max(1, min(127, v + self.rng.randint(-alcance, alcance)))
            if novo != v:
                motor.escrever_step(i, s, novo, motor.ler_sub(i, s),
                                    motor.ler_alt(i, s))
                time.sleep(0.002)
        motor.pintar()
        motor.log(f"humanize +-{alcance} aplicado (seed {self.seed})")

    def retrig(self, motor, chance, tipos=(1, 2, 3, 4)):
        """Sorteia sub steps nos steps ativos - rufos/flams aleatorios.

        chance em % por step; tipos sao os codigos do byte 5 (1 flam,
        2/3/4 = sub 1/2, 1/3, 1/4)."""
        if not self._pronto(motor):
            return
        for i, s in self._ativos(motor):
            if self.rng.random() * 100 < chance:
                motor.escrever_step(i, s, motor.ler_vel(i, s),
                                    self.rng.choice(list(tipos)),
                                    motor.ler_alt(i, s))
                time.sleep(0.002)
        motor.pintar()
        motor.log(f"retrig {chance}% aplicado (seed {self.seed})")

    def gerar_ghosts(self, motor, chance):
        """Liga steps VAZIOS com velocity fraca e probability baixa.

        E a assinatura do Stochas traduzida: o pattern ganha notas que a
        propria maquina decide tocar ou nao a cada volta. So mexe em linhas
        que ja tem alguma nota - linha vazia e escolha, nao esquecimento."""
        if not self._pronto(motor):
            return
        criados = 0
        for i in range(len(L.INSTRUMENTOS)):
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
