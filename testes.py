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
import sys
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
class TesteResyncNaoCongela(unittest.TestCase):
    """O bug que fazia o grid nao espelhar o que toca.

    _ressincronizar() reatribuia passo_abs (contador ABSOLUTO) com o step da
    maquina (MODULAR, 0..15). O ciclo de variacoes conta no absoluto, entao a
    contagem despencava e a variacao congelava ate o fim da sessao.

    Reproduz o laco real: pulsos de clock, perda de pulsos (a fila do rtmidi
    estourava - 657 vezes no log de 15/08), e o resync rodando a cada ~1,5 s.
    """

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
