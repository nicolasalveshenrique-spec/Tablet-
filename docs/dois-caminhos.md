# Os dois caminhos até o cartão

Há dois destinos possíveis para um cartão de oclusão, e eles não usam a mesma
tecnologia. Escolher o errado custa tempo, então vale saber por que são dois.

**O AnkiConnect não existe no AnkiDroid.** Ele é um complemento do Anki de
computador, e complementos são código Python que o app Android não roda. Não é
uma limitação temporária nem algo que se resolva instalando outra coisa: é a
razão de existirem dois caminhos em vez de um.

| | **Caminho A — computador** | **Caminho B — tablet** |
|---|---|---|
| Destino | Anki no Windows 10 | AnkiDroid, direto |
| Como entra | AnkiConnect, na hora | arquivo `.apkg`, importado |
| Precisa do Anki aberto | sim | não |
| Precisa de computador | sim | **não** |
| Onde acha os rótulos | Tesseract (OCR) | análise de imagem, sem OCR |
| Precisão da caixa | maior | boa, com conferência visual |
| Chega no tablet | sincronizando depois | na hora |
| Comando | `ocluir enviar` | `ocluir empacotar` |

Nenhum dos dois é "o certo". O A é melhor quando você está no computador com o
material da aula aberto; o B é o único que existe quando você está no tablet
assistindo aula, e é o que funciona pelo chat do Claude.

---

## Caminho A — do computador para o Anki

Cria a nota diretamente na coleção aberta. É o caminho de maior precisão porque
o Tesseract mede os rótulos em pixel exato.

```
python -m ocluir ler slide.png --titulo "Divisões do encéfalo" \
    --pergunta divisoes-encefalo --disciplina anatomia --aula 2026-08-10

# abra o plano, preencha "grupos" com o que você decidiu que é âncora

python -m ocluir previa slide.plano.json     # confira as máscaras
python -m ocluir enviar slide.plano.json     # cria a nota
```

Exige: Anki aberto, AnkiConnect instalado (código `2055492159`), Tesseract com
o pacote de português.

Depois, o AnkiWeb leva a nota para o tablet no próximo sync.

---

## Caminho B — do tablet para o AnkiDroid

Produz um arquivo `.apkg` que carrega as notas **e** as imagens dentro dele.
Você toca no arquivo no Android e o AnkiDroid importa. Nenhum computador,
nenhum servidor, nenhuma conta.

### B1 — pelo computador, gerando o arquivo

```
python -m ocluir empacotar slide.plano.json -o cartoes.apkg --conferir
```

O `--conferir` reimporta o pacote com a biblioteca oficial do Anki e relata o
que de fato entrou. Vale a pena: um `.apkg` malformado é aceito na escrita e só
falha na importação, no aparelho, quando já não dá para consertar.

### B2 — sem OCR, quando o Tesseract não está disponível

```
python -m ocluir caixas slide.png --titulo "Glicólise" --pergunta glicolise
```

Acha as caixas de texto por análise de imagem — projeção de perfil, com remoção
de traços longos para que moldura e seta não virem rótulo. Escreve uma imagem
com as caixas **numeradas**.

O campo `texto` dos candidatos sai vazio de propósito: este método *mede*, não
*lê*. Quem lê é você (ou eu, olhando a imagem numerada) — e é aí que se diz "a
caixa 3 é a hexoquinase".

### B3 — pelo chat do Claude, sem repositório nenhum

`chat/ocluir_chat.py` é o projeto inteiro num arquivo só, sem dependência além
do Pillow. É o que roda no sandbox do chat.

```python
from ocluir_chat import detectar, desenhar_numeradas, criar_apkg, ESCONDER_UMA

caixas, tamanho = detectar("slide.png")
desenhar_numeradas("slide.png", caixas, "numeradas.png")   # eu olho esta

criar_apkg(
    "slide.png", caixas,
    [
        {"rotulo": "Hexoquinase", "caixas": [3]},
        {"rotulo": "Aldolase",    "caixas": [9]},
    ],
    "cartoes.apkg",
    titulo="Glicólise — fase preparatória",
    deck="Medicina::Bioquímica",
    modo=ESCONDER_UMA,
    tags=["oclusao", "pergunta::glicolise", "disc::bioquimica"],
)
```

O ciclo no chat fica:

1. você manda o print da aula;
2. eu rodo a detecção e olho a imagem numerada;
3. eu digo qual número é qual rótulo e você confirma ou corrige;
4. sai o `.apkg`, você baixa no tablet e toca nele.

---

## Máscaras do mesmo tamanho

Ligado por padrão nos dois caminhos, via `mascara_uniforme` no plano.

O motivo não é estética. **A largura da máscara é informação.** Numa imagem com
"Ponte" e "Fosfofrutoquinase-1" ocluídas, o retângulo curto só pode ser o
primeiro — e o cartão fica respondível pela geometria, sem saber anatomia. Com
todas iguais, a única pista que sobra é a posição, que é exatamente a que o
cartão deveria estar cobrando.

| Valor | Efeito |
|---|---|
| `"maior"` (padrão) | todas ficam do tamanho da maior caixa do conjunto |
| `"0.18x0.04"` | tamanho fixo, em frações da imagem |
| `""` | desliga; cada máscara fica do tamanho do seu texto |

Cada máscara continua **centrada no rótulo que cobre**, e a maior é usada como
referência para que nenhuma fique menor que o texto que deveria esconder.

O efeito colateral está previsto e é avisado: ao igualar, a máscara de uma
palavra curta cresce, e num diagrama apertado pode encostar no rótulo vizinho.
O contrato avisa quando duas máscaras se sobrepõem em mais de 25%, e a saída é
fixar um tamanho menor ou desligar a uniformização naquela imagem.

---

## O que foi verificado, e o que não foi

**Verificado aqui:** o `.apkg` gerado pelo caminho B é reimportado pela
biblioteca **oficial** do Anki (versão 26.08) e chega do outro lado com as notas,
os cartões, as imagens, os decks e as tags certas — usando o notetype nativo de
oclusão, identificado por `originalStockKind = 6`. Essa marca é o que faz o
revisor desenhar máscara; um notetype com os mesmos campos e templates, mas sem
ela, importa sem erro e mostra a imagem sem oclusão nenhuma.

Escrever com uma implementação (sem dependência) e ler com outra, independente,
é o que dá confiança de que o arquivo chega inteiro.

**Não verificado aqui:** a importação num AnkiDroid de verdade. Não há aparelho
Android neste ambiente.

E essa lacuna já cobrou o preço uma vez.

## O erro que só o aparelho encontrou

O primeiro pacote gerado importava sem queixa na biblioteca de computador e o
AnkiDroid recusava com:

```
500: Failed to read '…/ocluir-teste-ankidroid.apkg':
stream did not contain valid UTF-8
```

A causa era estrutural. Um `.apkg` pode estar em três formatos, e quem decide
qual é um arquivo `meta` dentro do zip:

| Formato | Como se reconhece | Coleção fica em |
|---|---|---|
| Legacy1 | sem `meta` | `collection.anki2` |
| Legacy2 | `meta` com versão 2 | `collection.anki21` |
| Novo | `meta` com versão 3 | `collection.anki21b` (zstd) |

O escritor portátil produzia **Legacy1** — formalmente válido, e é por isso que
a biblioteca de computador o aceitava. Mas o AnkiDroid exercita esse caminho
antigo de um jeito diferente, e o mapa de mídia acabava sendo lido como se
fosse outro arquivo, dando o erro de UTF-8.

A correção foi passar a emitir **Legacy2**, que é exatamente o que o próprio
Anki exporta com `legacy=True`: `meta` com versão 2, dados em
`collection.anki21`, e `collection.anki2` mantido como resquício para clientes
antigos.

A lição, que vale além deste caso: **imitar o que a ferramenta produz é mais
seguro que imitar o que o formato permite.** Um formato aceita muitas coisas
que só um dos leitores implementa bem, e testar contra um leitor não é testar
contra todos.

Há agora um teste que trava a estrutura do zip contra a do exportador oficial —
mesmas entradas, mesmo `meta` — para que a regressão não volte silenciosamente.

## Duas vias para escrever o pacote

```
ocluir empacotar plano.json -o cartoes.apkg --via oficial
```

| `--via` | Quem escreve | Quando usar |
|---|---|---|
| `auto` (padrão) | oficial se instalada, senão portátil | o caso normal |
| `oficial` | biblioteca do Anki (`pip install anki`) | máxima compatibilidade |
| `portatil` | só biblioteca padrão | onde não dá para instalar nada — o chat |

As duas produzem o mesmo conjunto de entradas no zip. A oficial é maior porque
carrega índices e estatísticas que o Anki gera; nenhuma das duas é mais correta
que a outra, mas a oficial é, por construção, idêntica ao que sai do programa.
