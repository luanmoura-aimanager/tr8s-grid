# Sessão V1–V7 — a trava de variação em hardware

Roteiro da verificação do PR #9 (PR-A do PLANO-GROOVES).

## RESULTADO — rodado em 18/08/2026, passou inteiro

TR-8S tocando, pattern 1-01, kit TR-707, 86 bpm. Os oito pontos, com o horário do log:

| | resultado |
|---|---|
| **V1** | ✅ **~2 s** — travada 01:06:46, tocando só a B em 01:06:48 (menos de uma volta) |
| **V2** | ✅ 4 repetições, sem meia-batida nem conteúdo velho |
| **V3** | ✅ troca na virada |
| **V4** | ✅ volta sozinho no mesmo segundo (01:10:01); a variação aberta fica intacta |
| **V5** | ✅ devolveu **A/B/C**, as três (01:11:11) |
| **V6** | ✅ o primeiro compasso depois do play já é a travada |
| **V7** | ✅ recusa o Fill e cai na primeira válida (01:27:08) |
| **V7b** | ✅ recusado; `var_pedida` nem foi enfileirado (01:29:06) |

Duas ressalvas de método ficaram registradas na REFERENCIA 7.8, e valem mais que a
tabela: o **V4 quase virou "falhou"** por defeito do observador (diferenciava o log por
tamanho, e o log tem teto de 25 linhas — encheu e ficou cego), e o **V7 quase passou por
acidente** (do jeito que o roteiro estava escrito, o "auto" acharia a variação que toca
antes de chegar ao Fill, e a recusa nunca seria exercitada — foi preciso restaurar o
rodízio antes).

O texto abaixo é o roteiro como foi executado, para quem precisar repetir.

---

**Quando isto foi escrito, nada tinha sido testado na TR-8S** — a suíte de mesa prova
que o código faz o que eu quis, não que a máquina obedece. Quem diz que funciona é o
Luan, na frente dela.

Eu leio o log e o estado daqui, por um observador que roda em segundo plano (só GET
`/estado`, sem escrever nada). A tela mostra **só a última linha** do log, então não
tente caçar mensagens: faça o passo e me diga o que **viu e ouviu**.

---

## Antes de começar (4 checagens)

**A.** A TR-8S está tocando de verdade? O estado diz `tocando: true`, mas a TR-8S manda
MIDI clock **mesmo parada** (REFERENCIA 2.8) — só o seu olho resolve. Confirme o
playhead andando no visor dela.

**B.** **Desligue o AUTO FILL IN.** Ele está com o intervalo em **4** e, ligado, entra um
fill a cada 4 compassos — no meio de toda observação de "só a B está repetindo". É o
botão de liga/desliga que fica **fora** do knob.

**C.** Confirme no visor que **A, B e C** estão habilitadas. O app já lê `[A, B, C]`, e é
o cenário que o V1 precisa: com uma só habilitada não há rodízio para a trava desligar.

**D.** Dê **Cmd+R** na página. O agente foi reiniciado quando instalei, o motor releu
tudo, mas o navegador pode estar com o JS antigo — e o chip e o botão novos vêm dele.

---

## ⚠️ Antes do V1, uma coisa que muda a máquina

Armar o loop **escreve o groove por cima da variação escolhida** do pattern corrente
(agora o **1-01**, kit TR-707). Se houver algo na **B** do 1-01 que você queira manter,
troque para um pattern descartável antes — ou aceite e use o **Desfazer**, que volta.

A trava também **desliga o rodízio A→B→C** enquanto o loop roda. Ele **não volta
sozinho** ao parar: volta pelo botão **"Restaurar rodízio"**, que agora só aparece
**depois** que o loop para.

---

## V1 — a trava pega

1. Aba **Grooves**. No painel de fontes, escolha um groove qualquer da biblioteca.
2. Clique em **"+ Loop"** — ele vira um card no painel **"Loop de encadeamento"**.
3. Nesse painel, no seletor **variação**, escolha **B**.
4. Clique em **"Tocar loop"**.

**O que esperar** — a volta do pattern são 16 steps e a máquina está em 86 bpm, ou seja
**~2,8 s por volta**. Em uma ou duas voltas:

- o visor da TR-8S passa a repetir **só a B**;
- na tela aparece o chip **"travado na B"** ao lado do seletor;
- na aba **Pattern**, o botão **B** ganha a marca verde de "tocando" (antes ela não
  existia, porque com três habilitadas a variação que toca era dedução — o log dizia
  literalmente "passou a tocar a variacao **?**").

**Me diga:** quantas voltas demorou até parar de ciclar, e se a **A** ou a **C** ainda
entraram depois disso.

---

## V2 — o groove entra inteiro

Deixe rodar **4 repetições** sem tocar em nada.

**Ouça:** alguma volta em que o groove entra **pela metade**, ou com conteúdo velho
misturado. Era esse o sintoma que o PR conserta — a escrita ia para a variação aberta,
e metade do groove ficava numa e metade noutra.

**Me diga:** soou igual nas 4 voltas, ou teve volta torta.

---

## V3 — duas entradas

Ponha um **segundo groove** na fila (**"+ Loop"** de novo) e deixe cada card em **2×**
(os botões `−` / `+` do card).

**Esperar:** a troca acontece **na virada**, sem meia-batida e sem buraco.

**Me diga:** o primeiro step depois da troca sai em tempo, ou sai atrasado/adiantado.

---

## V4 — brigar de propósito (este é o teste da invariante)

Com o loop **rodando**, vá à aba **Pattern** e dê **um clique simples** no botão da
variação **D** — clique simples abre a variação no grid para editar.

**Esperar:**

- o log diz **"o grid saiu para a D; voltando para a B, que e a do loop"**;
- o grid **volta sozinho** para a B em ~2 s (a volta reabre a variação, e reabrir custa
  uma releitura inteira);
- **nada** foi escrito na **D**. Confira: pare o loop depois e abra a D para ver.

**Me diga:** o grid voltou sozinho? Quanto tempo levou? A D ficou intacta?

> Cuidado para não dar **clique duplo** aqui — duplo é "peça essa variação à máquina", e
> com a trava no ar ele agora é **recusado** com uma mensagem. Isso é o V7b, abaixo.

---

## V5 — parar e restaurar

1. Clique em **"Parar"**.
2. O botão **"Restaurar rodízio"** aparece (ele fica escondido enquanto o loop roda,
   porque o motor recusa restaurar com o loop no ar).
3. Clique nele.

**Esperar:** a máquina volta a ciclar **A→B→C**, e a variação tocando na tela volta a ser
**"?"**. Isso está **certo**: com três habilitadas, qual toca vira dedução de novo.

**Me diga:** o rodízio voltou com as **três** (não só a B)? Este é o ponto que a revisão
pegou — a versão anterior teria devolvido só a B.

---

## V6 — máquina parada

1. **Pare** a TR-8S.
2. Arme o loop (**"Tocar loop"**) — a tela deve dizer **"esperando play na TR-8S"**.
3. Dê **play** na TR-8S.

**Esperar:** o **primeiro** ciclo já é a variação fixada, não uma volta da A antes.

**Me diga:** a primeira volta já foi a B?

---

## V7 — o Fill In é recusado

1. Com o loop **parado**, vá à aba **Pattern** e abra um **Fill In** no grid.
2. Volte à aba Grooves, ponha o seletor de variação em **"auto"** e clique em
   **"Tocar loop"**.

**Esperar:** recusa clara no log — o Fill In não tem slot na máscara de variação nem last
step decodificado, então travar nele não tem endereço. O loop **não** arma... ou arma
noutra variação A–H, se houver uma para escolher. Qualquer um dos dois está certo; o
errado seria travar no Fill.

**Me diga:** o que apareceu na mensagem.

### V7b — o pedido de variação com a trava (bônus, achado da revisão)

Com o loop rodando na B, dê **clique duplo** na variação **D** na aba Pattern.

**Esperar:** recusa — *"o loop esta travado na B: pedir a D poria a maquina a tocar uma
variacao e o loop a escrever noutra. Pare o loop antes"*.

Antes desta correção isso só **avisava** e deixava passar: a caixa ia tocar a D enquanto
o loop seguia escrevendo na B, e nada retravava.

**Me diga:** foi recusado mesmo, ou a máquina trocou para a D?

---

## Se algo travar no meio

- **A porta CTRL é de um processo só.** Se a tela parar de responder, me avise antes de
  reiniciar qualquer coisa — reiniciar o agente derruba o motor e obriga a reler tudo.
- Se a escrita começar a ser recusada, o loop agora **para sozinho** depois de meio
  segundo insistindo, e diz por quê. Isso é o comportamento novo e correto: meio groove
  no ar é pior que loop nenhum.
