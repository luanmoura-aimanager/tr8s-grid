#!/usr/bin/env python3
"""Testes de mesa - nenhuma porta MIDI, nenhuma TR-8S, nenhum Launchpad.

    export PYTHONPATH=~/Library/Python/3.9/lib/python/site-packages
    python3 testes.py

Existem porque neste projeto "compila" e "roda sem excecao" nunca foram
"funciona" (CLAUDE.md), e porque os dois bugs de 16/08/2026 - a variacao que
congela e a guarda de portas que recusa por causa de uma interface de audio -
sao AMBOS provaveis sem hardware. Antes deles o projeto nao tinha nenhum teste,
e cada regressao so aparecia com o Luan na frente da maquina.

O que NAO da pra testar aqui, e continua sendo trabalho de bancada: se a TR-8S
obedece a escrita da mascara de variacao, se o ordinal de porta e fisicamente o
aparelho da esquerda, e o bug aberto do buffer de edicao (REFERENCIA 7).
"""

import os
import re
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lp_tr8s as L


# ─────────────────────────────────────────────────────────────
# O ciclo de variacoes
# ─────────────────────────────────────────────────────────────
class TesteCicloVars(unittest.TestCase):
    """A variacao que toca, derivada da contagem de passos."""

    def setUp(self):
        self.dur = {1: 16, 2: 16, 3: 16}          # A, B e C com 16 steps
        self.c = L.CicloVars()
        self.c.ancorar(0, [1, 2, 3], self.dur, 1)

    def test_sem_ancora_e_incerto(self):
        """Sem ancora a resposta e None ("?"), nunca um palpite."""
        c = L.CicloVars()
        self.assertIsNone(c.variacao_em(0))
        self.assertIsNone(c.variacao_em(999))

    def test_cicla_em_ordem_ascendente(self):
        vistos = [self.c.variacao_em(p * 16) for p in range(9)]
        self.assertEqual(vistos, [1, 2, 3, 1, 2, 3, 1, 2, 3])

    def test_e_funcao_pura_da_posicao(self):
        """Perguntar fora de ordem da a mesma resposta - e o que impede o
        congelamento: nao ha estado acumulado que possa ficar preso."""
        self.assertEqual(self.c.variacao_em(20), 2)
        self.assertEqual(self.c.variacao_em(5), 1)      # voltar no tempo
        self.assertEqual(self.c.variacao_em(20), 2)     # e ainda acertar

    def test_last_steps_diferentes(self):
        """Cada variacao dura o SEU last step, nao 16 fixo."""
        c = L.CicloVars()
        c.ancorar(0, [1, 2], {1: 4, 2: 12}, 1)
        self.assertEqual([c.variacao_em(p) for p in (0, 3, 4, 15, 16)],
                         [1, 1, 2, 2, 1])

    def test_ancorar_no_meio_de_uma_variacao(self):
        """'a B esta tocando ha 5 steps' tem que cair certo pra tras e pra frente."""
        c = L.CicloVars()
        c.ancorar(100, [1, 2, 3], self.dur, 2, dentro=5)
        self.assertEqual(c.variacao_em(100), 2)
        self.assertEqual(c.variacao_em(100 - 5), 2)     # comeco da B
        self.assertEqual(c.variacao_em(100 - 6), 1)     # um step antes: A
        self.assertEqual(c.variacao_em(100 + 11), 3)    # B acaba, entra C

    def test_deslocar_move_o_ciclo_junto(self):
        self.assertEqual(self.c.variacao_em(16), 2)
        self.c.deslocar(4)
        self.assertEqual(self.c.variacao_em(16), 1)     # a fronteira andou
        self.assertEqual(self.c.variacao_em(20), 2)


# ─────────────────────────────────────────────────────────────
# A REGRESSAO de 16/08/2026: o resync congelava a variacao
# ─────────────────────────────────────────────────────────────
def motor_cru(last=12, vars_hab=(1, 2, 3)):
    """Um Motor SEM __init__: nenhuma porta MIDI aberta, nenhum Launchpad.

    Existe para os testes chamarem os metodos DE VERDADE. A primeira versao
    destes testes reimplementava o algoritmo do resync inline, e por isso nao
    guardava nada: dava para reintroduzir 'self.passo_abs = alvo' dentro do
    _ressincronizar que os 17 testes continuavam verdes, porque nenhum deles
    executava uma linha daquele metodo. Apontado no review de 16/08."""
    m = object.__new__(L.Motor)
    m.log = lambda *a, **k: None
    m.lock = threading.RLock()
    m.tocando = True
    m.pulsos = 0
    m.passo_abs = 0
    m.passo = -1
    m.passo_maquina = None
    m.passo_maquina_t = 0.0
    m.variacao = vars_hab[0]
    m.vars_habilitadas = list(vars_hab)
    m.ultimo_var = {v: last for v in range(1, 9)}
    m.ultimo_track = [None] * len(L.INSTRUMENTOS)
    m.variacao_tocando = vars_hab[0]
    m.var_presumida = False
    m.espelho_suspeito = False
    m._saltos = []
    m._erros_seguidos = []
    m._t_log_bloqueio = 0.0
    m.ciclo = L.CicloVars()
    m.ciclo.ancorar(0, list(vars_hab), m.ultimo_var, vars_hab[0])
    m.mover_playhead = lambda p: setattr(m, "passo", p)   # sem LED nenhum
    return m


class TesteResyncReal(unittest.TestCase):
    """Exercita Motor._ressincronizar DE VERDADE (ver motor_cru)."""

    def test_nunca_reatribui_passo_abs_com_valor_modular(self):
        """A REGRESSAO de 16/08: passo_abs e ABSOLUTO, o step da maquina e
        MODULAR (0..11). Reatribuir um pelo outro congelava a variacao."""
        m = motor_cru()
        m.pulsos = 5000 * L.PULSOS_P_STEP
        m.passo_abs = 5000
        m.passo_maquina = 3                      # a maquina esta no step 4
        # tres leituras do mesmo sentido, frescas: e o que autoriza corrigir
        for _ in range(L.ERROS_P_CORRIGIR):
            m.passo_maquina_t = time.time()
            m._ressincronizar()
        self.assertGreater(m.passo_abs, 4000,
                           "passo_abs despencou para o modulo da maquina - "
                           "o bug de 16/08 voltou")

    def test_ruido_alternado_nao_corrige(self):
        """Erro que troca de sinal e ruido de medicao (medido: distribuicao
        uniforme de -5 a +6). Corrigir por ele fazia o playhead saltar."""
        m = motor_cru()
        m.pulsos = 600 * L.PULSOS_P_STEP
        m.passo_abs = 600
        antes = m.passo_abs
        for alvo in (10, 2, 9, 1, 8):            # sinais misturados
            m.passo_maquina = alvo
            m.passo_maquina_t = time.time()
            m._ressincronizar()
        self.assertEqual(m.passo_abs, antes,
                         "corrigiu por ruido: o playhead vai saltar")

    def test_alvo_velho_e_descartado(self):
        m = motor_cru()
        m.pulsos = 600 * L.PULSOS_P_STEP
        m.passo_abs = 600
        m.passo_maquina = 3
        m.passo_maquina_t = time.time() - (L.VALIDADE_PASSO + 0.5)
        for _ in range(L.ERROS_P_CORRIGIR + 2):
            m._ressincronizar()
        self.assertEqual(m.passo_abs, 600, "corrigiu por um alvo vencido")

    def test_escrita_bloqueada_quando_o_espelho_diverge(self):
        """O guarda tem que valer para TODO caminho de escrita, nao so o
        escrever_step - colar, limpar e o chain mandam DT1 direto."""
        m = motor_cru()
        self.assertFalse(m.escrita_bloqueada())
        m.espelho_suspeito = True
        self.assertTrue(m.escrita_bloqueada("teste"))


class TesteResyncNaoCongela(unittest.TestCase):
    """O mesmo bug, agora no laco completo: pulsos de clock, perda de pulsos
    (a fila do rtmidi estourava - 657 vezes no log de 15/08) e o resync a cada
    ~1,5 s. Este modela o algoritmo; quem guarda o codigo enviado e a classe
    TesteResyncReal acima."""

    DUR = {1: 16, 2: 16, 3: 16}
    VS = [1, 2, 3]
    LIM = 16

    def _rodar(self, corrigido, compassos=12, perde_a_cada=37):
        ciclo = L.CicloVars()
        ciclo.ancorar(0, self.VS, self.DUR, 1)
        pulsos = passo_abs = 0
        limite_velho = self.DUR[self.VS[0]]      # o estado da versao com bug
        idx_velho, var_velha = 0, self.VS[0]
        por_compasso = []
        maior_queda = 0                          # o defeito e a NAO-monotonia

        for p in range(1, self.LIM * L.PULSOS_P_STEP * compassos + 1):
            maquina = (p // L.PULSOS_P_STEP) % self.LIM   # a maquina nunca erra
            if p % perde_a_cada:                          # fila estourou: descarta
                pulsos += 1
                passo_abs = pulsos // L.PULSOS_P_STEP
                while passo_abs >= limite_velho:          # _avancar_ciclo_vars antigo
                    idx_velho = (idx_velho + 1) % len(self.VS)
                    var_velha = self.VS[idx_velho]
                    limite_velho += self.DUR.get(var_velha, 16)

            if p % 13 == 0:                               # o tick ressincroniza
                atual = passo_abs % self.LIM
                erro = (maquina - atual) % self.LIM
                if min(erro, self.LIM - erro) > L.TOLERANCIA_SYNC:
                    delta = erro if erro <= self.LIM - erro else erro - self.LIM
                    antes = passo_abs
                    if corrigido:
                        pulsos += delta * L.PULSOS_P_STEP
                        passo_abs = pulsos // L.PULSOS_P_STEP
                        ciclo.deslocar(delta)
                    else:
                        pulsos = maquina * L.PULSOS_P_STEP   # <- o bug
                        passo_abs = maquina
                    maior_queda = max(maior_queda, antes - passo_abs)

            if p % (self.LIM * L.PULSOS_P_STEP) == 0:
                por_compasso.append(ciclo.variacao_em(passo_abs) if corrigido
                                    else var_velha)
        return por_compasso, maior_queda

    def test_a_versao_antiga_congela(self):
        """Guarda do bug: se algum dia isto voltar a passar, o bug voltou."""
        vistos, maior_queda = self._rodar(corrigido=False)
        self.assertEqual(len(set(vistos[4:])), 1,
                         "a versao com bug deveria congelar numa variacao so")
        self.assertGreater(maior_queda, self.LIM,
                           "o bug era passo_abs DESPENCAR de absoluto para 0..15")

    def test_a_versao_corrigida_cicla(self):
        vistos, maior_queda = self._rodar(corrigido=True)
        esperado = [self.VS[c % len(self.VS)] for c in range(len(vistos))]
        self.assertEqual(vistos, esperado)
        self.assertLessEqual(maior_queda, L.TOLERANCIA_SYNC + 1,
                             "passo_abs tem que continuar praticamente monotonico")

    def test_passo_abs_nunca_despenca(self):
        """O Chain (ferramentas.py) faz 'ciclo = passo_abs // lim' pra achar a
        virada. Se passo_abs cair, ele conta uma repeticao que nunca tocou."""
        ciclo = L.CicloVars()
        ciclo.ancorar(0, self.VS, self.DUR, 1)
        pulsos = passo_abs = 0
        minimo_visto = 0
        for p in range(1, self.LIM * L.PULSOS_P_STEP * 8 + 1):
            maquina = (p // L.PULSOS_P_STEP) % self.LIM
            if p % 37:
                pulsos += 1
            passo_abs = pulsos // L.PULSOS_P_STEP
            if p % 13 == 0:
                atual = passo_abs % self.LIM
                erro = (maquina - atual) % self.LIM
                if min(erro, self.LIM - erro) > L.TOLERANCIA_SYNC:
                    delta = erro if erro <= self.LIM - erro else erro - self.LIM
                    pulsos += delta * L.PULSOS_P_STEP
                    novo = pulsos // L.PULSOS_P_STEP
                    self.assertGreaterEqual(
                        novo, passo_abs - L.TOLERANCIA_SYNC * 2 - 1,
                        "o resync andou pra tras demais - o Chain contaria errado")
                    passo_abs = novo
            minimo_visto = min(minimo_visto, passo_abs)
        self.assertGreaterEqual(minimo_visto, 0)


# ─────────────────────────────────────────────────────────────
# A janela de instrumentos (INST UP/DOWN) - trava sem hardware
# ─────────────────────────────────────────────────────────────
class TesteJanelaDeInstrumentos(unittest.TestCase):
    """Motor.executar('rolar', ...) e base_max(), sem porta MIDI nenhuma."""

    def _motor(self, esconder_mudos=False, mostrar_acc=False, passo=None):
        m = motor_cru()
        m.mudo = [False] * len(L.INSTRUMENTOS)
        m.esconder_mudos = esconder_mudos
        m.mostrar_acc = mostrar_acc
        m.passo_inst = passo if passo is not None else L.PASSO_INST_PADRAO
        m.base_inst = 0
        m.pintar = lambda: None
        m.pintar_botoes = lambda: None
        m._persistir = lambda: None    # nao mexe no ~/.lp_tr8s_estado.json real
        return m

    def test_lista_cabe_inteira_nao_tem_scroll(self):
        """HIDE MUTED deixando exatamente 8: REFERENCIA 1063, scroll some."""
        m = self._motor(esconder_mudos=True)
        m.mudo[2] = m.mudo[3] = m.mudo[4] = True   # LT, MT, HT mutados
        self.assertEqual(m.base_max(), 0)

    def test_inst_down_pula_8_e_trava(self):
        m = self._motor()
        m.executar("rolar", 1)
        self.assertEqual(m.base_inst, 8, "passo padrao deveria pular pro fundo")
        antes = m.base_inst
        m.executar("rolar", 1)             # segundo toque, sem soltar
        self.assertEqual(m.base_inst, antes, "ja deveria estar travado")

    def test_inst_up_volta_direto_ao_topo(self):
        m = self._motor()
        m.base_inst = 8
        m.executar("rolar", -1)
        self.assertEqual(m.base_inst, 0)

    def test_passo_pequeno_continua_pagina_cheia(self):
        """Sem regressao: quem escolher passo 3 ve o comportamento de sempre."""
        m = self._motor(passo=3)
        self.assertEqual(m.base_max(), 3)

    def test_diminuir_passo_reclampa_base_inst(self):
        """ACHADO DO CODE REVIEW: base_max() passou a depender de passo_inst,
        e definir_passo_inst e o unico mutador dele que nao reclampava
        base_inst - igual aplicar_mudos/oculto/acc ja faziam para os OUTROS
        jeitos de base_max() encolher."""
        m = self._motor()
        m.base_inst = 8                    # travado no fundo, passo 8
        m.definir_passo_inst(3)
        self.assertEqual(m.base_inst, 3, "ficou fora de faixa depois do passo encolher")


# ─────────────────────────────────────────────────────────────
# A guarda de portas
# ─────────────────────────────────────────────────────────────
LPD = "Launchpad Mini MK3 LPMiniMK3 DAW Out"
LPM = "Launchpad Mini MK3 LPMiniMK3 MIDI Out"
LPD_I = "Launchpad Mini MK3 LPMiniMK3 DAW In"
LPM_I = "Launchpad Mini MK3 LPMiniMK3 MIDI In"

# o snapshot real gravado pelo learn em 13/08/2026, com a Scarlett ligada
SNAP_IN = ["Scarlett 18i8 USB", "TR-8S", "TR-8S CTRL", LPD, LPM, LPD, LPM]
SNAP_OUT = ["Scarlett 18i8 USB", "TR-8S", "TR-8S CTRL", LPD_I, LPM_I,
            LPD_I, LPM_I]


def _cfg_antigo():
    """Layout no formato de 13/08: so indices, sem ordinal."""
    return {
        "esquerdo": {"in_idx": 6, "in_nome": LPM, "out_idx": 6,
                     "out_nome": LPM_I, "origem": 88,
                     "passo_col": -10, "passo_lin": -1},
        "direito": {"in_idx": 4, "in_nome": LPM, "out_idx": 4,
                    "out_nome": LPM_I, "origem": 81,
                    "passo_col": 1, "passo_lin": -10},
        "_portas_in": list(SNAP_IN), "_portas_out": list(SNAP_OUT),
    }


class TesteGuardaDePortas(unittest.TestCase):
    """A guarda comparava a lista INTEIRA de portas por igualdade, entao
    desligar a interface de audio (que nem e do projeto) derrubava o app com
    'Aperte Recalibrar' - e recalibrar era exatamente a acao errada."""

    def test_o_bug_de_16_08_a_scarlett_desligada(self):
        """O caso real: sem a Scarlett, tudo anda -1 e os indices salvos (6 e
        4) nem existem. Tem que reresolver sozinho para 5 e 3."""
        atual_in = ["TR-8S", "TR-8S CTRL", LPD, LPM, LPD, LPM]
        atual_out = ["TR-8S", "TR-8S CTRL", LPD_I, LPM_I, LPD_I, LPM_I]
        cfg, msgs = L.resolver_layout(_cfg_antigo(), atual_in, atual_out)
        self.assertIsNotNone(cfg, f"deveria ter resolvido; disse: {msgs}")
        self.assertEqual(cfg["esquerdo"]["in_idx"], 5)
        self.assertEqual(cfg["direito"]["in_idx"], 3)
        self.assertEqual(cfg["esquerdo"]["out_idx"], 5)
        self.assertEqual(cfg["direito"]["out_idx"], 3)

    def test_enumeracao_identica_nao_mexe_em_nada(self):
        cfg, _ = L.resolver_layout(_cfg_antigo(), SNAP_IN, SNAP_OUT)
        self.assertEqual(cfg["esquerdo"]["in_idx"], 6)
        self.assertEqual(cfg["direito"]["in_idx"], 4)

    def test_aparelho_a_mais_que_nao_e_launchpad(self):
        """Ligar o IAC Driver nao pode invalidar a calibracao."""
        cfg, _ = L.resolver_layout(
            _cfg_antigo(),
            ["IAC Driver Bus 1"] + SNAP_IN, ["IAC Driver Bus 1"] + SNAP_OUT)
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["esquerdo"]["in_idx"], 7)

    def test_recusa_com_um_launchpad_so(self):
        """Aqui recusar e o certo: escrever cairia no aparelho errado."""
        cfg, msgs = L.resolver_layout(
            _cfg_antigo(),
            ["Scarlett 18i8 USB", "TR-8S", "TR-8S CTRL", LPD, LPM],
            ["Scarlett 18i8 USB", "TR-8S", "TR-8S CTRL", LPD_I, LPM_I])
        self.assertIsNone(cfg)
        self.assertTrue(any("Launchpad" in m for m in msgs), msgs)

    def test_recusa_com_a_ordem_do_grupo_trocada(self):
        cfg, msgs = L.resolver_layout(
            _cfg_antigo(),
            ["TR-8S", "TR-8S CTRL", LPM, LPD, LPM, LPD],
            ["TR-8S", "TR-8S CTRL", LPM_I, LPD_I, LPM_I, LPD_I])
        self.assertIsNone(cfg)
        self.assertTrue(any("ordem" in m.lower() for m in msgs), msgs)

    def test_recusa_atomica(self):
        """Se um lado nao resolve, os DOIS sao recusados - meio grid escrevendo
        no aparelho errado e pior que grid nenhum."""
        cfg, _ = L.resolver_layout(
            _cfg_antigo(),
            ["TR-8S", LPD, LPM], ["TR-8S", LPD_I, LPM_I])
        self.assertIsNone(cfg)

    def test_layout_novo_usa_o_ordinal_gravado(self):
        """Depois de um learn novo o ordinal vem no arquivo, sem precisar
        deduzir do snapshot."""
        cfg_novo = _cfg_antigo()
        cfg_novo["esquerdo"]["in_ord"] = 3
        cfg_novo["esquerdo"]["out_ord"] = 3
        cfg_novo["direito"]["in_ord"] = 1
        cfg_novo["direito"]["out_ord"] = 1
        del cfg_novo["_portas_in"], cfg_novo["_portas_out"]
        cfg, msgs = L.resolver_layout(
            cfg_novo, ["TR-8S", LPD, LPM, LPD, LPM],
            ["TR-8S", LPD_I, LPM_I, LPD_I, LPM_I])
        self.assertIsNotNone(cfg, msgs)
        self.assertEqual(cfg["esquerdo"]["in_idx"], 4)
        self.assertEqual(cfg["direito"]["in_idx"], 2)

    def test_layout_sem_ordinal_e_sem_snapshot_recusa(self):
        """Nao da pra adivinhar: e o unico caso que ainda exige Recalibrar."""
        cfg = _cfg_antigo()
        del cfg["_portas_in"], cfg["_portas_out"]
        resolvido, msgs = L.resolver_layout(cfg, SNAP_IN, SNAP_OUT)
        self.assertIsNone(resolvido)
        self.assertTrue(msgs)


class TesteEnderecoDePattern(unittest.TestCase):
    """O `24 5x` era uma FOTOGRAFIA do pattern 3-06, o que estava carregado
    durante o sniff. A regra geral e `pattern*16 + variacao` no segundo byte,
    com carry de 7 bits para o primeiro."""

    def test_reproduz_o_sniff_do_tr_editor(self):
        """3-06 e o indice 37: 37*16+1 = 593 = 4*128+81, ou seja 24 51.

        Se esta conta parar de bater com o que o editor pediu na captura, a
        formula regrediu - e o sniff e a unica fonte que temos."""
        self.assertEqual(L.addr_variacao(37, 0), (0x24, 0x50, 0x00, 0x00))
        self.assertEqual(L.addr_variacao(37, 1), (0x24, 0x51, 0x00, 0x00))
        self.assertEqual(L.addr_bloco_rd(0, 1, 37), (0x24, 0x51, 0x00, 0x08))
        # e o DT1 de escrita visto no segundo sniff (step 2 do BD)
        self.assertEqual(L.addr_step_rd(0, 1, 1, 37), (0x24, 0x51, 0x00, 0x10))

    def test_confere_com_a_maquina_de_16_08(self):
        """Os quatro patterns lidos na TR-8S, incluindo os que transbordam o
        carry de 7 bits para o byte 0."""
        for pattern, esperado in ((0,   (0x20, 0x01, 0x00, 0x08)),
                                  (4,   (0x20, 0x41, 0x00, 0x08)),
                                  (43,  (0x25, 0x31, 0x00, 0x08)),
                                  (127, (0x2F, 0x71, 0x00, 0x08))):
            with self.subTest(pattern=pattern):
                self.assertEqual(L.addr_bloco_rd(0, 1, pattern), esperado)

    def test_o_pattern_e_obrigatorio(self):
        """Um default silencioso E o bug: ele nao some, so muda de pattern.

        Guarda de projeto - se alguem puser `pattern=0` de volta para 'facilitar',
        este teste cai."""
        for fn, args in ((L.addr_bloco_rd, (0, 1)),
                         (L.addr_accent_rd, (1,)),
                         (L.addr_no_pattern, ()),
                         (L.addr_last_var, (1,)),
                         (L.addr_last_track, (0,))):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(TypeError):
                    fn(*args)

    def test_todo_pattern_tem_endereco_proprio(self):
        """Nenhum par (pattern, variacao) pode colidir com outro - foi
        exatamente a colisao (tudo caindo no pattern 0) que causou o bug."""
        vistos = {}
        for p in range(128):
            for v in range(11):
                a = L.addr_variacao(p, v)
                self.assertNotIn(a, vistos,
                                 f"{a} serve {(p, v)} e {vistos.get(a)}")
                vistos[a] = (p, v)
                self.assertTrue(all(0 <= b <= 0x7F for b in a),
                                f"{a} estourou os 7 bits")


# ─────────────────────────────────────────────────────────────
# A biblioteca de patterns
# ─────────────────────────────────────────────────────────────
class TesteBiblioteca(unittest.TestCase):
    """biblioteca.validar() existia mas nada a rodava: um pattern quebrado
    passava calado ate a UI (linha torta no preview, escrita errada na
    maquina). Entrou na expansao 3, junto com os 20 patterns novos."""

    def test_todos_validam(self):
        import biblioteca as B
        for p in B.PATTERNS:
            with self.subTest(id=p.get("id", "?")):
                B.validar(p)

    def test_ids_unicos(self):
        import biblioteca as B
        ids = [p["id"] for p in B.PATTERNS]
        self.assertEqual(len(ids), len(set(ids)),
                         "id duplicado na biblioteca")

    def test_expandir_da_11_por_16(self):
        """expandir() e o contrato que escrever_pattern consome: sempre 11
        instrumentos, cada um com 16 tuplas (vel, sub, prob, alt)."""
        import biblioteca as B
        for p in B.PATTERNS:
            with self.subTest(id=p["id"]):
                grade = B.expandir(p)
                self.assertEqual(sorted(grade), list(range(11)))
                for linha in grade.values():
                    self.assertEqual(len(linha), 16)
                    for tupla in linha:
                        self.assertEqual(len(tupla), 4)


class TesteScale(unittest.TestCase):
    """A SCALE do pattern (lp_tr8s.OFF_SCALE), provada em 17/08/2026 por
    snapdiff com ida e volta: 32nd->16th mudou o byte 0x16 do no do pattern de
    03 para 02, e a volta o devolveu. Antes disso o motor assumia semicolcheia
    sempre, e num pattern em 32nd o playhead andava em METADE da velocidade da
    maquina - foi assim que o bug apareceu."""

    def motor(self, scale):
        m = L.Motor.__new__(L.Motor)     # sem __init__: nao precisa de MIDI
        m.scale = scale
        return m

    def test_pulsos_de_cada_scale(self):
        # 24 pulsos por seminima: semicolcheia = 6, fusa = 3, tercinas 8 e 4
        for cod, esperado in ((0, 8), (1, 4), (2, 6), (3, 3)):
            with self.subTest(scale=cod):
                self.assertEqual(self.motor(cod).pulsos_p_step(), esperado)

    def test_scale_nao_lida_vale_semicolcheia(self):
        """Enquanto o no do pattern nao foi lido, o comportamento e o antigo."""
        self.assertEqual(self.motor(None).pulsos_p_step(), L.PULSOS_P_STEP)

    def test_codigo_desconhecido_nao_quebra(self):
        """Codigo fora dos quatro conhecidos nao pode zerar nem explodir: a
        conta do playhead divide por este numero."""
        self.assertEqual(self.motor(0x7F).pulsos_p_step(), L.PULSOS_P_STEP)


# ─────────────────────────────────────────────────────────────
# CONTRATOS ENTRE AS CAMADAS
#
# Tudo aqui nasceu de 17/08/2026, quando uma reforma grande passou nos 31 testes
# e mesmo assim quebrou: a acao "reler" existia no servidor sem NENHUM botao (e
# quando uma leitura falhava a escrita ficava bloqueada sem saida pela pagina),
# a captura de FX ficou sem cancelamento quando a aba Avancado saiu, e um
# `fileira2` que nao existia foi parar no fx.mjs. Nenhum desses e pegavel
# testando Python: os dois lados do contrato estao em linguagens diferentes.
#
# A tecnica: ler os .mjs como TEXTO. E o que dispensa runner JS num projeto cuja
# decisao explicita e "modulos ES nativos, zero build, zero dependencia".
# ─────────────────────────────────────────────────────────────
WEB_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "js")


def _mjs():
    """[(caminho relativo, texto)] de todos os modulos da pagina."""
    saida = []
    for raiz, _dirs, arqs in os.walk(WEB_JS):
        for a in sorted(arqs):
            if a.endswith(".mjs"):
                caminho = os.path.join(raiz, a)
                with open(caminho, encoding="utf-8") as f:
                    saida.append((os.path.relpath(caminho, WEB_JS), f.read()))
    return saida


def _todo_o_js():
    return "\n".join(t for _, t in _mjs())


def _chamadas_agir():
    """[(arquivo, {chave: valor literal})] de cada `agir({...})` da pagina.

    Ler a CHAMADA INTEIRA, e nao cada `tipo:`/`op:`/`nome:` solto pelo arquivo,
    e o que faz o teste enxergar o que ele promete. A primeira versao usava
    regex avulsa e colhia o `tipo: "ok"` do toast, o `tipo: "knob"` do fx e o
    `nome:` de qualquer objeto - ruido que obrigava a comparar so a intersecao,
    e comparar intersecao com o conjunto e tautologia: o teste nunca falhava.
    Apontado na revisao de 17/08/2026, provado por mutacao.

    A chamada aninhada do chain_armar (que tem `{tipo:"groove"}` dentro) sai
    inteira num pedaco so, e as chaves de dentro ficam no lugar certo: sao do
    chain_armar, nao do exec."""
    saida = []
    for arq, texto_js in _mjs():
        for corpo in re.findall(r'agir\(\s*\{(.*?)\}\s*\)', texto_js, re.S):
            pares = dict(re.findall(r'(\w+):\s*"([^"]*)"', corpo))
            if pares:
                saida.append((arq, pares))
    return saida


class TesteContratos(unittest.TestCase):
    """O que a pagina PEDE x o que o servidor OFERECE.

    Quatro divergencias reais motivaram cada teste daqui, todas de 17/08/2026 e
    todas silenciosas: acao sem botao, botao sem acao, aba removida deixando
    referencia solta, e chave de estado lida sem existir."""

    # Acoes que existem no servidor e NINGUEM chama na pagina. Cada uma precisa
    # de motivo escrito: orfa nova quebra o teste, orfa antiga fica documentada.
    ORFAS_CONHECIDAS = {
        # a aba Avancado saiu em 17/08/2026 ("o programa tem que ficar mais
        # simples") e levou junto a ferramenta de captura guiada. As acoes
        # ficaram porque o catalogo pode voltar a ter buraco - e ai a captura
        # volta do git sem precisar reescrever o servidor
        "capturar": "captura guiada, sem UI desde 17/08/2026",
        "cancelar_captura": "idem",
        "anotar_opcao": "idem",
        "esquecer_fx": "idem",
    }
    EXEC_ORFAOS = {"oculto": "esconder linha muda saiu da barra de ferramentas"}
    UTIL_ORFAOS = {"visor": "botoes de utility sairam com a aba Avancado",
                   "playing": "idem", "versao": "idem"}

    def acoes_da_pagina(self):
        return {p["acao"] for _arq, p in _chamadas_agir() if "acao" in p}

    def test_toda_acao_da_pagina_existe_no_servidor(self):
        """Botao que chama acao inexistente responde 400 e nao faz nada."""
        import servidor
        for acao in sorted(self.acoes_da_pagina()):
            with self.subTest(acao=acao):
                self.assertIn(acao, servidor.ACOES,
                              f"a pagina chama '{acao}' e o servidor nao tem")

    def test_toda_acao_do_servidor_tem_chamador(self):
        """A acao 'reler' viveu sem botao ate 17/08/2026: quando uma leitura
        falhava, a escrita ficava bloqueada e a pagina nao tinha como sair."""
        import servidor
        orfas = set(servidor.ACOES) - self.acoes_da_pagina()
        novas = orfas - set(self.ORFAS_CONHECIDAS)
        self.assertFalse(novas,
                         f"acoes sem chamador na pagina: {sorted(novas)}. Se "
                         "for de proposito, acrescente em ORFAS_CONHECIDAS com "
                         "o motivo; se nao, esta faltando o botao")
        sumidas = set(self.ORFAS_CONHECIDAS) - set(servidor.ACOES)
        self.assertFalse(sumidas,
                         f"ORFAS_CONHECIDAS cita acao que nao existe mais: "
                         f"{sorted(sumidas)} - limpe a lista")

    def _argumentos_de(self, acao, chave):
        """Os valores de `chave` nas chamadas de UMA acao. Escopado: sem isso o
        `tipo:` do toast e o `op:` do externa entram na conta."""
        return {p[chave] for _arq, p in _chamadas_agir()
                if p.get("acao") == acao and chave in p}

    def test_exec_nos_dois_sentidos(self):
        """`exec` e uma segunda lista fechada (EXEC_OK), um nivel abaixo das
        acoes: tipo que nao esta nela levanta ValueError e vira 500 - o botao
        nao faz nada e ninguem descobre por que."""
        import servidor
        usados = self._argumentos_de("exec", "tipo")
        self.assertTrue(usados, "nenhum exec extraido - o extrator quebrou")
        for t in sorted(usados):
            with self.subTest(tipo=t):
                self.assertIn(t, servidor.EXEC_OK,
                              f"a pagina manda exec '{t}', que o servidor "
                              "recusa")
        orfaos = servidor.EXEC_OK - usados - set(self.EXEC_ORFAOS)
        self.assertFalse(orfaos, f"exec sem chamador: {sorted(orfaos)}")

    def test_util_nos_dois_sentidos(self):
        """O `util` e pior que o exec: op desconhecida cai fora dos dois ramos
        do _acao_util e retorna EM SILENCIO - sem log, sem erro, sem 500."""
        import inspect
        import servidor
        fonte = inspect.getsource(servidor._acao_util)
        # a lista sai do FONTE do servidor, nao copiada a mao: op nova la
        # entra no teste sozinha
        ops = set(re.findall(r'"(\w+)":', fonte)) | set(
            re.findall(r'a\["op"\] == "(\w+)"', fonte))
        usados = self._argumentos_de("util", "op")
        self.assertTrue(usados, "nenhum util extraido - o extrator quebrou")
        for o in sorted(usados):
            with self.subTest(op=o):
                self.assertIn(o, ops, f"a pagina manda util '{o}', que o "
                                      "servidor ignora calado")
        orfaos = ops - usados - set(self.UTIL_ORFAOS)
        self.assertFalse(orfaos, f"util sem chamador: {sorted(orfaos)}")

    # ── estado ──
    # nomes que a pagina le num objeto chamado `e` que NAO sao estado: sao
    # propriedades de evento do DOM. A colisao e real - `e.alt` e chave de
    # estado e `e.altKey` e do teclado, no mesmo repositorio
    EVENTO_DOM = {"altKey", "button", "clientX", "clientY", "ctrlKey", "deltaY",
                  "detail", "key", "message", "metaKey", "name", "pointerId",
                  "preventDefault", "shiftKey", "stopPropagation", "target",
                  "currentTarget", "dataset", "type", "value", "stack"}

    def chaves_do_estado(self):
        """As chaves que o motor e o servidor produzem, tiradas do FONTE.

        Do fonte, e nao de uma chamada real, porque estado() precisa de um Motor
        inteiro - e a graca destes testes e nao precisar de hardware."""
        import inspect
        import servidor
        do_motor = set(re.findall(r'"(\w+)":', inspect.getsource(L.Motor.estado)))
        fonte_host = inspect.getsource(servidor.Host.estado)
        do_host = set(re.findall(r'e\["(\w+)"\]', fonte_host))
        return do_motor | do_host

    def test_toda_chave_lida_pela_pagina_existe(self):
        """Chave que a pagina le e ninguem produz vira `undefined` calado - a
        tela mostra "—" para sempre e parece um problema de hardware."""
        produzidas = self.chaves_do_estado()
        lidas = set()
        for arq, texto_js in _mjs():
            lidas |= set(re.findall(r'\be\.([a-z_][a-zA-Z0-9_]*)', texto_js))
            # a aba Grooves guarda o ultimo quadro num alias chamado `ultimo` e
            # le o estado por ele. So ali: no comp/toast.mjs existe outro
            # `ultimo`, que e o de-duplicador de toasts e nao tem nada a ver
            if arq == os.path.join("abas", "grooves.mjs"):
                lidas |= set(re.findall(r'\bultimo\.([a-z_][a-zA-Z0-9_]*)',
                                        texto_js))
        faltando = lidas - produzidas - self.EVENTO_DOM
        self.assertFalse(faltando,
                         f"a pagina le chaves que o estado nao tem: "
                         f"{sorted(faltando)}. Se for propriedade de evento do "
                         "DOM, acrescente em EVENTO_DOM")

    # chaves que o estado produz de proposito sem ninguem ler. Cada uma precisa
    # de motivo escrito - o `pads` viveu aqui sem motivo nenhum, custando ~1.070
    # cor_do_step por segundo DENTRO do lock do motor, para nenhum leitor
    ESTADO_SEM_LEITOR = {
        "mudo_bits_altos": "sonda de pesquisa: os bits 11-15 do mute",
        "passo_maquina": "conferencia da nossa contagem de clock contra a dela",
        "auto_fill": "intervalo do AUTO FILL IN, decifrado e ainda sem tela",
        "velocidade": "a tela usa vel_idx + D.velocidades",
        "modo": "a tela usa modo_idx + D.modos_step",
        "esconder_mudos": "estado do grid fisico, nao da pagina",
        "var_presumida": "distincao ancorado x presumido, ainda sem tela",
        "lista_visivel": "a tela usa janela",
        "desfazer_disponivel": "a tela usa desfazer_pilha",
        "captura_fx": "a captura guiada saiu da tela em 17/08/2026",
    }

    def test_chave_produzida_sem_leitor(self):
        """O par do teste acima, e ele faltava. Chave que ninguem le nao quebra
        nada - so custa. O `pads` era 128 cor_do_step por quadro, ~8 quadros por
        segundo, dentro do lock, para leitor nenhum: ficou meses assim porque
        nada olhava para este lado do contrato."""
        produzidas = self.chaves_do_estado()
        lidas = set()
        for arq, texto_js in _mjs():
            lidas |= set(re.findall(r'\be\.([a-z_][a-zA-Z0-9_]*)', texto_js))
            if arq == os.path.join("abas", "grooves.mjs"):
                lidas |= set(re.findall(r'\bultimo\.([a-z_][a-zA-Z0-9_]*)',
                                        texto_js))
        sobrando = produzidas - lidas - set(self.ESTADO_SEM_LEITOR)
        self.assertFalse(sobrando,
                         f"o estado produz sem ninguem ler: {sorted(sobrando)}. "
                         "Se for de proposito, acrescente em ESTADO_SEM_LEITOR "
                         "com o motivo; se nao, e trabalho jogado fora a cada "
                         "quadro")
        limpas = set(self.ESTADO_SEM_LEITOR) - produzidas
        self.assertFalse(limpas,
                         f"ESTADO_SEM_LEITOR cita chave que nao existe mais: "
                         f"{sorted(limpas)} - limpe a lista")

    # ── contrato de aba ──
    def test_toda_aba_cumpre_o_contrato(self):
        """app.mjs espera {id, rotulo, montar, atualizar} em cada aba."""
        for arq, texto_js in _mjs():
            if not arq.startswith("abas" + os.sep):
                continue
            with self.subTest(aba=arq):
                for campo in ('id:', 'rotulo:', 'montar(', 'atualizar('):
                    self.assertIn(campo, texto_js,
                                  f"{arq} nao tem '{campo}'")

    def test_ids_das_abas_batem_com_o_app(self):
        """Remover uma aba e esquecer a referencia no app.mjs quebra o boot
        inteiro - foi o risco real quando a Avancado saiu, em 17/08/2026."""
        app = dict(_mjs())["app.mjs"]
        importadas = set(re.findall(r'import (\w+) from "\./abas/(\w+)\.mjs"',
                                    app) and
                         [m[1] for m in re.findall(
                             r'import (\w+) from "\./abas/(\w+)\.mjs"', app)])
        arquivos = {arq.split(os.sep)[1][:-4] for arq, _ in _mjs()
                    if arq.startswith("abas" + os.sep)}
        self.assertEqual(importadas, arquivos,
                         "ha aba em web/js/abas/ que o app.mjs nao importa, ou "
                         "import de aba que nao existe mais")

    # ── o contrato escrito duas vezes ──
    def test_rotulo_da_estocastica_bate_nos_dois_lados(self):
        """Estocastica.rotulo diz na propria docstring que o formato e CONTRATO
        com a tela, e o estocastica.mjs o reimplementa a mao em rotuloEsperado.
        Se divergirem, os botoes Reverter ficam desabilitados PARA SEMPRE, sem
        erro nenhum - o unico sintoma e uma coisa que nunca acende."""
        import ferramentas
        self.assertEqual(ferramentas.Estocastica.rotulo("densidade", None),
                         "densidade todos")
        self.assertEqual(ferramentas.Estocastica.rotulo("humanize", [0, 7]),
                         "humanize BD+CH")
        js = " ".join(dict(_mjs())[os.path.join("abas", "estocastica.mjs")]
                      .split())
        self.assertIn("`${op} todos`", js,
                      "o lado JS mudou o formato de 'op todos'")
        self.assertIn('op + " " +', js,
                      "o lado JS mudou o separador entre op e instrumentos")
        self.assertIn('.join("+")', js,
                      "o lado JS mudou o separador entre instrumentos")

    # ── nomes de parametro que a tela escreve a mao ──
    def test_nomes_de_fx_usados_pela_tela_existem_no_mapa(self):
        """A mesa chama "inst gain", "kit level", "inst ctrl select"... por
        nome. Renomear um no efeitos.py deixa o controle MUDO: o motor loga
        "parametro nao mapeado" e a tela nao mostra nada. Sao tambem chave
        permanente do ~/.lp_tr8s_fx.json (CLAUDE.md)."""
        import efeitos
        mapa = efeitos.carregar()
        js = _todo_o_js()
        nomes = set()
        # o `nome:` sai SO das chamadas com acao "fx" - solto pelo repositorio
        # ele colhia o `nome:` de qualquer objeto (um `nome: "meu groove"` no
        # grooves.mjs quebrava o teste). Apontado na revisao de 17/08/2026.
        nomes |= {p["nome"] for _arq, p in _chamadas_agir()
                  if p.get("acao") == "fx" and "nome" in p}
        # estes sao especificos o bastante para valer no arquivo todo. QUALQUER
        # string neles, nao so as minusculas: uma sabotagem renomeando para
        # "inst gainX" passou batida na primeira versao
        for padrao in (r'doCat\(D,\s*"([^"]+)"\)',
                       r'faixaDoCatalogo\(D,\s*"([^"]+)"\)',
                       r'\bfx\["([^"]+)"\]',
                       r'\bmapa\["([^"]+)"\]',
                       r'\barr\("([^"]+)"\)',
                       r'\bfileira\("([^"]+)"'):
            nomes |= set(re.findall(padrao, js))
        self.assertTrue(nomes, "nenhum nome extraido - o extrator quebrou")
        for n in sorted(nomes):
            with self.subTest(nome=n):
                # assertTrue e nao assertIn: o assertIn imprime o mapa INTEIRO
                # (75 KB) so para dizer que um nome nao esta la
                self.assertTrue(n in mapa,
                                f"a tela usa o parametro '{n}' e ele nao esta "
                                "no mapa (renomeado? o controle ficou mudo)")


class TesteSintaxeJS(unittest.TestCase):
    """`node --check` em todos os modulos.

    Em 17/08/2026 um `fileira2` que nao existia entrou no fx.mjs e so apareceu
    quando o Luan abriu a pagina. O navegador e o unico interpretador do projeto
    e ele so reclama em runtime; isto traz a reclamacao para ca."""

    def test_todos_os_mjs_compilam(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            # no CI, pular e pior que falhar: se o step do setup-node cair, o
            # workflow fica verde sem ter compilado um .mjs sequer, e o README
            # continua prometendo que todos compilam. Apontado na revisao de
            # 17/08/2026
            if os.environ.get("CI"):
                self.fail("node ausente no CI - a checagem de sintaxe dos "
                          ".mjs nao rodou, e verde aqui viraria mentira")
            self.skipTest("node nao instalado - a checagem de sintaxe some")
        for arq, _ in _mjs():
            with self.subTest(arquivo=arq):
                r = subprocess.run([node, "--check",
                                    os.path.join(WEB_JS, arq)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr.strip())


class TesteCatalogoFX(unittest.TestCase):
    """Invariantes do efeitos.py que so o __main__ dele checava.

    As escalas entraram em 17/08/2026, lidas no visor da maquina: sao o unico
    lugar do projeto onde um numero magico vale uma sessao de hardware."""

    def test_nomes_do_catalogo_sao_unicos(self):
        import efeitos
        nomes = [e["nome"] for e in efeitos.CATALOGO]
        dup = sorted({n for n in nomes if nomes.count(n) > 1})
        self.assertFalse(dup, f"nome duplicado no catalogo: {dup}")

    def test_toda_entrada_fixa_tem_off_e_bloco_valido(self):
        """carregar() NAO garante 'off': uma entrada sem ele passa e so quebra
        na hora de ler o byte."""
        import efeitos
        for nome, ent in sorted(efeitos.PARAMS_FIXOS.items()):
            with self.subTest(param=nome):
                self.assertIn("off", ent, "entrada sem offset")
                bloco = ent.get("bloco") or (
                    "inst" if ent.get("tipo") == "inst" else "kit")
                self.assertIn(bloco, efeitos.BLOCOS,
                              f"bloco '{bloco}' nao existe em BLOCOS")

    def test_opcoes_do_catalogo_so_onde_o_catalogo_tem_opcoes(self):
        import efeitos
        for nome, ent in sorted(efeitos.PARAMS_FIXOS.items()):
            if not ent.get("opcoes_do_catalogo"):
                continue
            with self.subTest(param=nome):
                cat = efeitos.POR_NOME.get(nome, {})
                self.assertTrue(cat.get("opcoes"),
                                "marcado como opcoes_do_catalogo e o catalogo "
                                "nao tem lista de opcoes")

    def test_escala_do_gain(self):
        """Lida no visor em 17/08/2026: byte 0 = -INF, 81 = 0.0 dB, 161 = +40.0.
        A tela mostrava "-47" onde a maquina dizia 0.0 dB."""
        import efeitos
        self.assertEqual(efeitos.GANHO_ESCALA[0], "-INF")
        self.assertEqual(efeitos.GANHO_ESCALA[81], "0.0 dB")
        self.assertEqual(efeitos.GANHO_ESCALA[161], "+40.0 dB")
        self.assertEqual(efeitos.GANHO_ESCALA[95], "+7.0 dB")   # o EXT IN
        self.assertEqual(max(efeitos.GANHO_ESCALA), efeitos.GANHO_MAX)

    def test_escala_do_pan(self):
        """O CENTER ocupa DOIS bytes (127 e 128) - era esse o erro de um que
        fazia a tela dizer -10 onde a maquina dizia L9."""
        import efeitos
        self.assertEqual(efeitos.PAN_ESCALA[0], "L127")
        self.assertEqual(efeitos.PAN_ESCALA[118], "L9")
        self.assertEqual(efeitos.PAN_ESCALA[126], "L1")
        self.assertEqual(efeitos.PAN_ESCALA[127], "CENTER")
        self.assertEqual(efeitos.PAN_ESCALA[128], "CENTER")
        self.assertEqual(efeitos.PAN_ESCALA[129], "R1")
        self.assertEqual(efeitos.PAN_ESCALA[255], "R127")


class TesteProtocolo(unittest.TestCase):
    """Os offsets que custaram sessao de hardware.

    Congelados de proposito: nenhum deles pode ser "arrumado" por dedução. Cada
    um tem a data e o metodo no comentario do lp_tr8s.py."""

    def test_offsets_medidos(self):
        self.assertEqual(L.OFF_SCALE, 0x16)          # snapdiff ida e volta
        self.assertEqual(L.OFF_FILL, 0x09)           # watch, 17 fills
        self.assertEqual(L.OFF_AUTO_FILL, 0x7F)      # snapdiff, 3 pontos
        self.assertEqual(L.OFF_TEMPO_NO, 0x10)       # sniff do TR-EDITOR
        self.assertEqual(L.OFF_TEMPO, 0x3A)          # espelho, so leitura
        self.assertEqual(L.AUTO_FILL_VALORES, [32, 16, 12, 8, 4, 2])
        import efeitos
        self.assertEqual(efeitos.CTRL_OFF_BASE, 0x01)

    def test_bpm_escreve_quatro_nibbles_no_no_do_pattern(self):
        """A REGRESSAO de 17/08: escrevia 3 nibbles no espelho da performance.
        A maquina aceitava o valor, a leitura de volta confirmava... e o
        andamento nao mudava. So medir o clock revelou."""
        m = object.__new__(L.Motor)
        m.log = lambda *a, **k: None
        m.modo_geral = L.MODO_ON
        m.pattern_atual = 0
        m._garantir_pattern = lambda: 0
        enviadas = []

        class SaidaFalsa:
            def send(self, msg):
                enviadas.append(msg)

        m.tr_out = SaidaFalsa()
        m.definir_bpm(120.0)
        self.assertEqual(len(enviadas), 1, "mandou mais de uma mensagem")
        dados = list(enviadas[0].data)
        endereco = dados[7:11]
        esperado = list(L.addr_soma(L.addr_no_pattern(0), L.OFF_TEMPO_NO))
        self.assertEqual(endereco, esperado,
                         "o tempo tem que ir para o NO do pattern")
        # 1200 = 0x4B0 em quatro nibbles
        self.assertEqual(dados[11:15], [0x0, 0x4, 0xB, 0x0],
                         "o campo inteiro ou nada: escrita parcial e recusada")

    def test_mudo_preserva_os_bits_que_ninguem_mapeou(self):
        """Achado da revisao de 17/08: a mascara tem 16 bits e a 2.7 decodificou
        11. Remontar do zero mandava ZERO nos outros cinco."""
        m = self._motor_de_mute()
        m.mudo_bits_altos = 0x0800
        m.alternar_mudo(7)
        self.assertEqual(m.escritas, [0x0880],
                         "o bit 11 tinha que voltar como estava")

    def test_mudo_nao_escreve_com_leitura_falha(self):
        """ler_mudos devolve False tanto para 'nada mudou' quanto para 'nao
        consegui ler', e no segundo caso deixa o espelho intacto. Seguir ali
        ressuscitaria um mute feito no painel."""
        m = self._motor_de_mute(falhar=True)
        m.alternar_mudo(0)
        self.assertEqual(m.escritas, [], "escreveu em cima de espelho velho")

    def _motor_de_mute(self, falhar=False):
        m = object.__new__(L.Motor)
        m.log = lambda *a, **k: None
        m.modo_geral = L.MODO_ON
        m.tr_out = object()
        m.mudo = [False] * len(L.INSTRUMENTOS)
        m.mudo_bits_altos = 0
        m.leituras_falhas = 0
        m.escritas = []

        def ler(quieto=False):
            if falhar:
                m.leituras_falhas += 1
            return False

        m.ler_mudos = ler
        m.definir_mudos = lambda mascara: m.escritas.append(mascara)
        return m

    def test_offset_por_instrumento(self):
        """O terceiro modo de enderecamento (CTRL): um byte por instrumento
        DENTRO de um bloco de kit."""
        ent = {"off": 0x01, "off_por_inst": True}
        self.assertEqual(L.Motor._fx_off(ent, 0), 0x01)    # BD
        self.assertEqual(L.Motor._fx_off(ent, 10), 0x0B)   # RC
        self.assertEqual(L.Motor._fx_off(ent, None), 0x01)
        self.assertEqual(L.Motor._fx_off({"off": 0x10}, 5), 0x10,
                         "sem off_por_inst o indice nao pode somar")


class TesteRespiroDoFill(unittest.TestCase):
    """O playhead some e o grid respira enquanto a maquina toca um FILL IN.

    Decidido em 17/08/2026, no dia seguinte ao byte do fill ser decifrado
    (perf 0x09). Antes disso o verde corria sobre a variacao aberta durante o
    fill - a unica cor da tela e dos pads mentindo sobre o som. Nao era
    descuido: ate haver o byte, nao havia informacao, e a regra da casa quando
    falta informacao e mostrar, nao apagar."""

    def motor(self, fill=None, variacao=1, tocando=1, passo=0, last=16):
        m = object.__new__(L.Motor)
        m.fill_ativo = fill
        m.variacao = variacao
        m.variacao_tocando = tocando
        m.passo = passo
        m.ultimo_var = {v: last for v in range(1, 11)}
        return m

    def test_playhead_fica_no_fill_como_na_maquina(self):
        """A primeira versao fazia o playhead SUMIR no fill. O Luan olhou o
        painel da TR-8S e viu que ela o MANTEM - e ela esta certa: a posicao e
        verdadeira, o sequenciador esta naquele step. O que muda e de qual
        variacao sai o som, e disso cuida o respiro.

        Guarda a licao, nao so o comportamento: "nao desenhar o que nao esta
        soando" foi aplicado a um dado que ESTAVA soando."""
        self.assertTrue(self.motor(fill=True).playhead_visivel())
        self.assertTrue(self.motor(fill=True, variacao=9).playhead_visivel())

    def test_sem_fill_vale_a_regra_antiga(self):
        self.assertTrue(self.motor(fill=False).playhead_visivel())
        self.assertFalse(self.motor(fill=False, variacao=2).playhead_visivel(),
                         "grid noutra variacao continua sem playhead")

    def test_fill_nao_lido_nao_muda_nada(self):
        """None = o bloco de performance ainda nao foi lido. Sem leitura, o
        comportamento e o de antes - mesma disciplina do pulsos_p_step()."""
        self.assertTrue(self.motor(fill=None).playhead_visivel())

    def test_tela_e_pads_respiram_na_MESMA_condicao(self):
        """A revisao de 18/08 pegou as duas superficies discordando: o motor
        respirava so com o playhead visivel e a tela so olhava fill_ativo -
        entao com o grid noutra variacao a tela pulsava e os pads nao. Num
        projeto que persegue "a cor da tela e a do aparelho nunca divergem",
        isso e o pior tipo de bug: cada metade parece certa sozinha.

        Este teste le a condicao dos DOIS lados e exige que sejam a mesma."""
        import inspect
        fonte_motor = inspect.getsource(L.Motor.mover_playhead)
        self.assertIn("self.fill_ativo and self.modo_geral == MODO_ON",
                      fonte_motor)
        # no motor o respiro esta DEPOIS do guarda do playhead_visivel
        pos_guarda = fonte_motor.index("if not self.playhead_visivel()")
        pos_respiro = fonte_motor.index("if self.fill_ativo")
        self.assertLess(pos_guarda, pos_respiro,
                        "o respiro tem que ficar depois do guarda do playhead")
        js = dict(_mjs())["app.mjs"]
        self.assertIn("e.fill_ativo && e.playhead_visivel", " ".join(js.split()),
                      "a tela tem que exigir as MESMAS duas condicoes do motor")

    def test_a_curva_do_respiro_fecha(self):
        """O respiro TEM que voltar a 1 nas pontas do compasso: e isso que
        garante que o grid nao fica apagado quando o fill acaba - e o fill acaba
        exatamente na virada (medido: 17 de 17 transicoes no step 15 -> 0)."""
        m = self.motor(fill=True)
        m.passo = 0
        self.assertAlmostEqual(m._fator_respiro(), 1.0, places=6)
        fatores = []
        for p in range(16):
            m.passo = p
            f = m._fator_respiro()
            self.assertTrue(0.0 <= f <= 1.0, f"fator fora de faixa no step {p}")
            fatores.append(f)
        self.assertAlmostEqual(min(fatores), L.RESPIRO_FUNDO, places=6)
        self.assertEqual(fatores.index(min(fatores)), 8,
                         "o fundo do respiro tem que cair no meio do compasso")

    def test_respirar_escurece_sem_explodir(self):
        """Indice de paleta nao escurece - por isso a cor passa por RGB. Indice
        que a tabela nao conhece sai INTACTO em vez de virar preto: cor errada
        e pior que cor sem respiro."""
        cheia = L.respirar(L.COR_FORTE, 1.0)
        fundo = L.respirar(L.COR_FORTE, L.RESPIRO_FUNDO)
        self.assertTrue(all(0 <= c <= 127 for c in cheia))
        self.assertTrue(all(0 <= c <= 127 for c in fundo))
        self.assertLess(sum(fundo), sum(cheia), "o respiro nao escureceu")
        self.assertEqual(L.respirar(0x7E, 0.5), 0x7E,
                         "indice desconhecido tem que sair intacto")
        self.assertEqual(L.respirar(L.COR_FORTE, 0.0), (0, 0, 0))


class TesteTravaNoMotorReal(unittest.TestCase):
    """A trava no Motor de verdade, nao no MotorFalso.

    Existe porque a sabotagem mostrou o limite dos testes com fake: quebrar o
    travar_variacao REAL deixava a suite inteira verde, ja que o unico teste da
    trava falava com o dublê. Sao os dois pontos que a revisao do PR #9 achou
    e que so aparecem aqui: o rodizio guardado uma vez so, e a mascara que
    nao saiu virando recusa."""

    def motor(self, **kw):
        m = object.__new__(L.Motor)
        m.log = lambda *a, **k: None
        m.lock = threading.RLock()
        m.modo_geral = L.MODO_ON
        m.pattern_atual = 0
        m._garantir_pattern = lambda: 0
        m.variacao = 1
        m.vars_habilitadas = [1, 2, 3]
        m.var_travada = None
        m.var_pedida = None
        m.rodizio_antes = None
        m.chain = None
        m.tocando = False
        m.executar = lambda *a, **k: None
        self.enviadas = []
        saida = type("SaidaFalsa", (), {
            "send": lambda _s, msg: self.enviadas.append(msg)})()
        m.tr_out = saida
        for k, v in kw.items():
            setattr(m, k, v)
        return m

    def test_rodizio_guardado_so_na_primeira_trava(self):
        """BUG DA REVISAO: gravava a cada chamada, e o chain retrava a cada
        tick em que o grid diverge. A segunda passagem guardava o rodizio JA
        TRAVADO por cima do original - B e C sumiam para sempre, e o botao
        Restaurar devolvia a propria trava."""
        m = self.motor()
        self.assertTrue(m.travar_variacao(1))
        self.assertEqual(m.rodizio_antes[0], [1, 2, 3])
        m.vars_habilitadas = [1]     # a leitura seguinte ve so a travada
        m.variacao = 4               # alguem abriu a D no grid
        self.assertTrue(m.travar_variacao(1))
        self.assertEqual(m.rodizio_antes[0], [1, 2, 3],
                         "a retrava comeu o rodizio original")

    def test_mascara_que_nao_saiu_e_recusa(self):
        """BUG DA REVISAO: _escrever_var_mask devolvia None no sucesso e nas
        duas desistencias, e travar_variacao lia isso como sucesso. Entre as
        guardas e a escrita roda um recarregar() com dezenas de RQ1, depois do
        qual o _garantir_pattern pode voltar None - o chain armava convencido
        de que travou, com varias variacoes habilitadas."""
        m = self.motor()
        m._garantir_pattern = lambda: 0

        def some_no_meio(*a, **k):   # o recarregar perde o pattern
            m._garantir_pattern = lambda: None
        m.executar = some_no_meio
        m.variacao = 2               # forca o passo que chama executar()
        self.assertFalse(m.travar_variacao(1),
                         "disse que travou sem a mascara ter saido")
        self.assertIsNone(m.var_travada)
        self.assertEqual(self.enviadas, [], "escreveu mesmo sem pattern")

    def test_restaurar_recusa_com_o_loop_no_ar(self):
        """BUG DA REVISAO: soltar a trava com o chain rodando devolve a
        deducao pelo clock e a perseguicao passa a escrever no escuro - e a
        invariante do Chain so olha motor.variacao, entao nunca retravaria."""
        m = self.motor()
        m.travar_variacao(1)
        m.chain = type("ChainFalso", (), {"ativo": True})()
        m.destravar_variacao(True)
        self.assertEqual(m.var_travada, 1, "soltou a trava com o loop no ar")
        self.assertIsNotNone(m.rodizio_antes)

    def test_restaurar_recusa_noutro_pattern(self):
        """BUG DA REVISAO: a mascara mora no no do pattern. Uma entrada de
        pattern no chain move a maquina, e o restaurar escrevia o rodizio
        guardado no no NOVO - mudando em silencio as variacoes habilitadas de
        um pattern que nunca entrou no loop."""
        m = self.motor()
        m.travar_variacao(1)
        self.enviadas.clear()
        m.pattern_atual = 24
        m._garantir_pattern = lambda: 24
        m.destravar_variacao(True)
        self.assertEqual(self.enviadas, [],
                         "escreveu o rodizio no pattern errado")
        self.assertIsNotNone(m.rodizio_antes, "perdeu o rodizio guardado")

    def test_pedir_variacao_recusa_com_a_trava(self):
        """BUG DA REVISAO: so avisava, apostando que "a trava volta a valer no
        proximo tick" - e nao volta: quem atende o pedido nao mexe em
        self.variacao, entao a invariante do Chain nunca fica falsa. A caixa
        tocava uma variacao e o loop escrevia noutra."""
        m = self.motor(tocando=True)
        m.travar_variacao(1)
        m.vars_habilitadas = [1]
        self.enviadas.clear()
        m.pedir_variacao(3)
        self.assertIsNone(m.var_pedida, "aceitou o pedido com a trava no ar")
        self.assertEqual(self.enviadas, [])


class MotorFalso:
    """O minimo do Motor que o Chain toca, com registro de chamadas.

    Existe porque o Chain e' a peca que mais depende de estado do Motor
    (variacao aberta, last step, passo_abs, tocando) e a que menos da' para
    exercitar com hardware: cada teste de loop e' uma sessao de 5 minutos com a
    caixa tocando. Aqui os quatro estados que importam sao ajustaveis a mao."""

    def __init__(self, variacao=1, last=16, tocando=True):
        self.variacao = variacao
        self.variacao_tocando = variacao
        self.vars_habilitadas = [variacao]
        self.ultimo_var = {v: last for v in range(1, 11)}
        self.passo_abs = 0
        self.tocando = True if tocando else False
        self.acc = 0
        self.pattern_atual = 0
        self.var_travada = None
        self.rodizio_antes = None
        self.escritos = []          # (inst, step) de cada escrever_step aceito
        self.travas = []            # cada travar_variacao pedido
        self.escrita_ok = True      # False = escrever_step recusa (bloqueada)
        self.trava_ok = True        # False = travar_variacao falha
        self.pintou = 0
        self.log = lambda *a, **k: None

    # ── o que o Chain chama ──
    def last_var(self):
        return self.ultimo_var.get(self.variacao, 16)

    def last_var_de(self, var):
        return self.ultimo_var.get(var, 16)

    def travar_variacao(self, v):
        self.travas.append(v)
        if not self.trava_ok:
            return False
        # espelha o real: guarda o rodizio SO na primeira trava. O fake nao
        # fazia isto, e era exatamente onde morava o bug que a revisao do PR #9
        # achou - a suite passava com o rodizio sendo destruido a cada retrava
        if self.var_travada is None:
            self.rodizio_antes = (list(self.vars_habilitadas), self.variacao,
                                  self.pattern_atual)
        self.var_travada = v
        self.variacao = v            # o travar_variacao real abre a variacao
        return True

    def destravar_variacao(self, restaurar=False):
        self.var_travada = None

    def escrever_step(self, i, s, vel, sub, alt=False, prob=None):
        if not self.escrita_ok:
            return False
        self.escritos.append((i, s, self.variacao))
        return True

    def escrever_pattern(self, dados, accent=0, last_var=16, nome=""):
        self.escritos.append(("pattern", self.variacao))
        return True

    def escrita_bloqueada(self, rotulo=""):
        return not self.escrita_ok

    def pintar(self):
        self.pintou += 1

    def _pattern_para_escrever(self, rotulo=""):
        return self.pattern_atual


class TesteChainVariacaoTravada(unittest.TestCase):
    """O loop trabalhava na "variacao aberta", que e uma variavel que muda
    debaixo dele. Diagnostico de 18/08/2026, e cada teste aqui guarda um dos
    bugs que isso causava - todos silenciosos, todos so audiveis na caixa."""

    def chain(self, **kw):
        import ferramentas
        return ferramentas.Chain([{"tipo": "groove", "nome": "g1",
                                   "dados": {}, "reps": 2}], log=lambda *a: None,
                                 **kw)

    def test_armar_trava_antes_de_escrever(self):
        """A ordem importa: travar depois de escrever poe o groove na variacao
        errada e so' entao acerta a maquina."""
        m, c = MotorFalso(variacao=1), self.chain(var=3)
        c.armar(m)
        self.assertEqual(m.travas, [3], "nao travou, ou travou na errada")
        self.assertTrue(c.ativo)
        self.assertEqual(m.escritos[0], ("pattern", 3),
                         "escreveu antes de travar - o groove foi para a "
                         "variacao errada")

    def test_nao_arma_se_a_trava_falha(self):
        """Meio loop e' pior que loop nenhum: sem trava, a perseguicao escreve
        no escuro e a conta de repeticoes salta."""
        m = MotorFalso()
        m.trava_ok = False
        c = self.chain(var=2)
        c.armar(m)
        self.assertFalse(c.ativo, "armou sem conseguir travar")
        self.assertEqual(m.escritos, [], "escreveu mesmo sem trava")

    def test_recusa_travar_num_fill_in(self):
        """Fill In (9 e 10) nao tem slot na mascara de variacao habilitada
        (2.3.2) nem last step decodificado - travar ali nao tem endereco."""
        m = MotorFalso(variacao=9)
        m.variacao_tocando = None
        m.vars_habilitadas = []
        c = self.chain()
        c.armar(m)
        self.assertFalse(c.ativo, "armou num Fill In")
        self.assertEqual(m.travas, [], "chegou a pedir trava num Fill In")

    def test_perseguicao_mede_pela_variacao_FIXADA(self):
        """BUG 1: o `lim` vinha do last_var() da variacao ABERTA, e ele decide
        ATE ONDE a perseguicao escreve (`passo_abs % lim`, "atras do playhead").
        Com o divisor errado, o groove entra na hora errada.

        RESSALVA HONESTA sobre o alcance deste teste: no fluxo do tick a
        invariante devolve o grid para a variacao do loop ANTES de calcular o
        lim, entao hoje os dois caminhos coincidem ali - a primeira versao
        deste teste passava com o bug reintroduzido, e so a sabotagem mostrou
        isso. Aqui o _perseguir e' chamado direto, que e' onde a diferenca e'
        observavel, e o teste existe para que mexer na invariante amanha nao
        reintroduza o bug em silencio."""
        m = MotorFalso(variacao=1, last=16)
        m.ultimo_var[5] = 4          # a aberta tem last step BEM menor
        c = self.chain(var=1)
        c.armar(m)
        m.variacao = 5               # alguem abriu outra variacao
        m.passo_abs = 8              # 8 % 16 = 8 pela fixada; 8 % 4 = 0 pela aberta
        m.escritos.clear()
        c._fila_escrita = {"passo": 0, "dados": {}}
        c._perseguir(m)
        self.assertGreater(c._fila_escrita["passo"], 0,
                           "nao escreveu nada: mediu com o last step da "
                           "variacao ABERTA em vez da fixada")

    def test_volta_para_a_variacao_do_loop(self):
        """A invariante: o cache e' da variacao aberta, e o escrever_step copia
        dele os bytes 0-2 que ninguem sabe ler. Escrever com o grid noutra
        variacao injeta lixo de uma na outra."""
        m = MotorFalso(variacao=1)
        c = self.chain(var=1)
        c.armar(m)
        m.variacao = 4               # o operador abriu outra
        c.tick(m)
        self.assertEqual(m.travas[-1], 1, "nao tentou voltar para a do loop")
        self.assertEqual(m.variacao, 1)

    def test_para_se_nao_consegue_voltar(self):
        m = MotorFalso(variacao=1)
        c = self.chain(var=1)
        c.armar(m)
        m.variacao, m.trava_ok = 4, False
        c.tick(m)
        self.assertFalse(c.ativo, "seguiu escrevendo na variacao errada")

    def test_escrita_recusada_nao_avanca_o_passo(self):
        """BUG 2: o _perseguir ignorava o retorno do escrever_step. Com a
        escrita bloqueada ele avancava fe["passo"] assim mesmo - o groove
        entrava PELA METADE, calado."""
        m = MotorFalso(variacao=1)
        c = self.chain(var=1)
        c.armar(m)
        c._fila_escrita = {"passo": 0, "dados": {}}
        m.escrita_ok = False
        m.passo_abs = 8
        c._perseguir(m)
        self.assertEqual(c._fila_escrita["passo"], 0,
                         "avancou o passo sem ter escrito nada")

    def _recusar(self, c, m, vezes):
        m.escrita_ok = False
        m.passo_abs = 8
        for _ in range(vezes):
            c._fila_escrita = {"passo": 0, "dados": {}}
            c._perseguir(m)

    def test_engasgo_passageiro_nao_mata_a_corrente(self):
        """O laco do servidor chama tick a cada 3 ms: contar TICKS fazia "tres
        recusas" caberem em ~9 ms e nenhum engasgo passageiro sobreviveria.
        A tolerancia e' uma janela de TEMPO (revisao do PR #9)."""
        m = MotorFalso(variacao=1)
        c = self.chain(var=1)
        c.armar(m)
        self._recusar(c, m, c.FALHAS_ATE_PARAR * 4)
        self.assertTrue(c.ativo,
                        "matou a corrente dentro da janela de tolerancia")

    def test_para_quando_a_escrita_segue_bloqueada(self):
        """Passada a janela, escrita bloqueada de verdade nao pode virar meio
        groove no ar."""
        m = MotorFalso(variacao=1)
        c = self.chain(var=1)
        c.armar(m)
        self._recusar(c, m, c.FALHAS_ATE_PARAR)
        # em vez de dormir meio segundo: envelhece a primeira recusa
        c._desde_falha -= c.TOLERANCIA_ESCRITA_S
        self._recusar(c, m, 1)
        self.assertFalse(c.ativo, "seguiu tentando escrever para sempre")

    def test_recusa_nao_zera_o_historico_sem_escrita(self):
        """O zeramento morava DEPOIS do while e rodava tambem nos ticks em que
        o corpo nao executou (fe['passo'] >= alvo, o caso comum logo apos a
        virada): o historico de recusas era apagado sem ter havido escrita
        nenhuma, e o chain nunca chegava ao limite (revisao do PR #9)."""
        m = MotorFalso(variacao=1)
        c = self.chain(var=1)
        c.armar(m)
        self._recusar(c, m, c.FALHAS_ATE_PARAR)
        marca = c._desde_falha
        # tick sem nada a escrever: o passo ja alcancou o alvo
        m.passo_abs = 0
        c._fila_escrita = {"passo": 0, "dados": {}}
        c._perseguir(m)
        self.assertEqual(c._falhas_escrita, c.FALHAS_ATE_PARAR,
                         "apagou as recusas num tick que nao escreveu nada")
        self.assertEqual(c._desde_falha, marca)

    def test_retrava_nao_destroi_o_rodizio_guardado(self):
        """BUG DA REVISAO: travar_variacao gravava rodizio_antes toda vez. A
        retrava da invariante gravava por cima o rodizio JA TRAVADO ([A]), e o
        A/B/C original sumia - o botao Restaurar devolvia a propria trava."""
        m = MotorFalso(variacao=1)
        m.vars_habilitadas = [1, 2, 3]
        c = self.chain(var=1)
        c.armar(m)
        self.assertEqual(m.rodizio_antes[0], [1, 2, 3])
        m.vars_habilitadas = [1]     # a leitura seguinte ve so a travada
        m.variacao = 4               # alguem abriu a D para editar
        c.tick(m)                    # a invariante retrava
        self.assertEqual(m.rodizio_antes[0], [1, 2, 3],
                         "a retrava comeu o rodizio original")

    def test_tick_para_de_trabalhar_num_chain_morto(self):
        """BUG DA REVISAO: o _avancar podia PARAR o chain (tres recusas la
        dentro) e o tick seguia - recriava a fila de um chain morto e a deixava
        nao-None para sempre, o que congela os adiamentos do motor (kit nunca
        mais relido, troca de pattern nunca mais recarrega o grid)."""
        m = MotorFalso(variacao=1, last=16)
        c = self.chain(var=1)
        c.entradas[0]["reps"] = 1
        c.armar(m)
        c._ciclo = 0
        m.passo_abs = 16             # virou o ciclo: cai no _avancar
        m.escrita_ok = False
        c._desde_falha = time.time() - c.TOLERANCIA_ESCRITA_S
        c._falhas_escrita = c.FALHAS_ATE_PARAR
        c.tick(m)
        self.assertFalse(c.ativo, "o cenario nao chegou a parar o chain - "
                                  "o teste estaria passando por vacuidade")
        self.assertIsNone(c._fila_escrita,
                          "chain parado ficou com fila pendente - o motor nao "
                          "volta a ler o kit nem a recarregar o grid")
        self.assertFalse(c.perseguindo())

    def test_var_fora_da_faixa_nao_estoura(self):
        """BUG DA REVISAO: _resolver_var indexava L.VARIACOES sem limite
        superior. Um var=99 levantava IndexError DENTRO do armar, antes de o
        servidor anular motor.chain: sobrava um Chain meio construido e todo
        estado() seguinte morria no resumo() dele - a pagina congelava."""
        m = MotorFalso(variacao=1)
        c = self.chain(var=99)
        c.armar(m)                   # nao pode levantar
        self.assertEqual(c.var, 1, "nao caiu para a variacao aberta")
        c.resumo()                   # nem aqui

    def test_parar_solta_a_trava_e_nao_restaura_sozinho(self):
        """Reescrever a mascara com varias variacoes com a musica tocando
        derruba a ancora do ciclo. Quem parou o loop normalmente quer continuar
        ouvindo o que ficou - o rodizio volta pelo botao."""
        m = MotorFalso(variacao=1)
        m.vars_habilitadas = [1, 2, 3]
        c = self.chain(var=1)
        c.armar(m)
        c.parar(m)
        self.assertFalse(c.ativo)
        self.assertIsNone(m.var_travada, "nao soltou a trava")
        self.assertIsNotNone(m.rodizio_antes,
                             "restaurou o rodizio sozinho, com a musica tocando")

    def test_resumo_diz_em_que_variacao_travou(self):
        m, c = MotorFalso(variacao=1), self.chain(var=2)
        c.armar(m)
        r = c.resumo()
        self.assertEqual(r["var"], 2)
        self.assertEqual(r["var_nome"], L.VARIACOES[1])


class TesteServidorSemMotor(unittest.TestCase):
    """O servidor de pe, sem TR-8S nenhuma - que e como ele nasce.

    Pega o que teste de unidade nao pega: chave que nao serializa em JSON (o
    cache_invalido e um set no motor), endpoint que sumiu, e a unica superficie
    de rede do projeto aceitando POST sem token."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import servidor
        cls.servidor_mod = servidor
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                    servidor.Handler)
        cls.porta = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def url(self, rota):
        return f"http://127.0.0.1:{self.porta}{rota}"

    def test_estado_serializa_e_diz_que_esta_desligado(self):
        import json
        import urllib.request
        with urllib.request.urlopen(self.url("/estado"), timeout=5) as r:
            e = json.load(r)
        self.assertFalse(e["ligado"], "sem motor, 'ligado' tem que ser False")
        for chave in ("log", "fresco", "tem_tr8s", "tem_lp", "cache_invalido",
                      "mapa_fx"):
            self.assertIn(chave, e, f"/estado sem a chave '{chave}'")
        self.assertIsInstance(e["cache_invalido"], list,
                              "o set do motor tem que virar lista no JSON")

    def test_dados_traz_o_que_a_pagina_monta(self):
        import json
        import urllib.request
        with urllib.request.urlopen(self.url("/dados"), timeout=5) as r:
            d = json.load(r)
        for chave in ("instrumentos", "variacoes", "velocidades", "modos_step",
                      "biblioteca", "catalogo_fx", "paineis_fx", "tones",
                      "cores", "build"):
            self.assertIn(chave, d, f"/dados sem a chave '{chave}'")
        self.assertEqual(len(d["instrumentos"]), len(L.INSTRUMENTOS))

    def test_estado_sobrevive_a_midi_quebrado(self):
        """Achado pelo CI no primeiro dia dele (17/08/2026): sem motor, o
        /estado enumera portas MIDI - e num runner sem ALSA isso levantava,
        a excecao subia pelo handler e a conexao caia SEM RESPOSTA. A pagina
        mostrava "sem contato com o servidor", o pior sintoma possivel para o
        problema mais bobo. Vale para o Mac tambem: CoreMIDI reiniciando faria
        o mesmo."""
        import json
        servidor = self.servidor_mod
        original = L.listar_portas

        def explode(entradas=True):
            raise SystemError("subsistema de MIDI indisponivel")

        L.listar_portas = explode
        try:
            e = servidor.HOST.estado()
            json.dumps(e)                       # tem que continuar serializando
            self.assertFalse(e["tem_tr8s"])
            self.assertFalse(e["tem_lp"])
            servidor.HOST.estado()              # de novo: nao pode logar duas
            avisos = sum("enumerar portas" in l
                         for l in servidor.HOST.log.ultimas())
            self.assertEqual(avisos, 1,
                             "o estado roda 4x/s: o aviso tem que sair UMA vez")
        finally:
            L.listar_portas = original
            servidor.HOST._midi_mudo = False

    def test_post_sem_token_e_recusado(self):
        """O token e sorteado a cada boot e vive so no processo. Sem esta
        recusa, qualquer pagina aberta no navegador escreveria na TR-8S."""
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            self.url("/acao"), data=b'{"acao":"reler"}', method="POST",
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)


class TesteInstaladores(unittest.TestCase):
    """As duas copias (LaunchAgent e .app) carregam a lista de arquivos a mao.

    Modulo novo que o servidor importa e que ninguem acrescenta na lista some
    da copia - e a copia e o que roda de verdade (CLAUDE.md)."""

    def modulos_do_servidor(self):
        """Todo modulo local que o servidor alcanca - TRANSITIVAMENTE.

        A primeira versao so olhava os `import X` diretos do servidor.py:
        modulo novo importado pelo lp_tr8s.py passava batido, e a copia do
        LaunchAgent (a que costuma estar no ar) quebrava no primeiro uso.
        Apontado na revisao de 17/08/2026."""
        raiz = os.path.dirname(os.path.abspath(__file__))
        locais = {a[:-3] for a in os.listdir(raiz) if a.endswith(".py")}
        vistos, fila = set(), ["servidor"]
        while fila:
            mod = fila.pop()
            if mod in vistos:
                continue
            vistos.add(mod)
            try:
                with open(os.path.join(raiz, mod + ".py"), encoding="utf-8") as f:
                    fonte = f.read()
            except OSError:
                continue
            for linha in fonte.splitlines():
                linha = linha.strip()
                m = (re.match(r'import (\w+)(?: as \w+)?$', linha)
                     or re.match(r'from (\w+) import ', linha))
                if m and m.group(1) in locais:
                    fila.append(m.group(1))
        # o servidor tambem DISPARA um script por subprocess (blackout): ele
        # nao aparece em import nenhum e mesmo assim precisa estar na copia
        return vistos | {"apagar_luzes"}

    def test_os_dois_instaladores_copiam_o_que_o_servidor_importa(self):
        raiz = os.path.dirname(os.path.abspath(__file__))
        precisa = self.modulos_do_servidor()
        for instalador in ("instalar_agente.py", "criar_app.py"):
            with open(os.path.join(raiz, instalador), encoding="utf-8") as f:
                fonte = f.read()
            for mod in sorted(precisa):
                with self.subTest(instalador=instalador, modulo=mod):
                    self.assertIn(f"{mod}.py", fonte,
                                  f"{instalador} nao copia {mod}.py, que o "
                                  "servidor importa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
