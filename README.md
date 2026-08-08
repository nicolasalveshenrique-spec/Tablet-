# ocluir

Cartões de oclusão de imagem para o Anki, com a **geometria vindo do OCR** e a
**decisão continuando sua**.

O problema que isto resolve não é desenhar retângulos — o editor do Anki já faz
isso, e bem. É o trabalho em volta: ler os rótulos de um diagrama, decidir quais
merecem virar cartão, acertar o deck e as tags que ligam o cartão à pergunta
lógica que o originou, e não descobrir a máscara torta três dias depois na
revisão.

## Dois caminhos, porque o AnkiConnect não existe no AnkiDroid

| | **computador** | **tablet** |
|---|---|---|
| destino | Anki no Windows | AnkiDroid, direto |
| como | AnkiConnect, na hora | arquivo `.apkg` |
| precisa de PC | sim | **não** |
| comando | `ocluir enviar` | `ocluir empacotar` |

Detalhes dos dois, e do caminho pelo chat do Claude: [docs/dois-caminhos.md](docs/dois-caminhos.md).

## O desenho em uma frase

Um modelo de visão sabe *o que* importa numa imagem e erra *onde exatamente*
aquilo está. O Tesseract é o contrário. Então o Tesseract dá a caixa em pixel
exato, o julgamento escolhe entre as caixas, e o programa só executa.

```
imagem ──► ocluir ler ──► plano.json ──► você decide ──► ocluir previa ──► ocluir enviar ──► Anki
             (OCR)        (candidatos)    (grupos)         (conferir)        (AnkiConnect)
```

## Instalação no Windows 10

1. **Python 3.11+** — <https://www.python.org/downloads/>
   Marque **"Add python.exe to PATH"** na primeira tela do instalador.

2. **Tesseract** — <https://github.com/UB-Mannheim/tesseract/wiki>
   Durante a instalação, em *Additional language data*, marque **Portuguese**.
   Sem isso o OCR lê português como se fosse inglês e erra acentos.

3. **O ocluir**, no Prompt de Comando:

   ```
   git clone https://github.com/nicolasalveshenrique-spec/tablet-.git
   cd tablet-
   pip install -r requirements.txt
   ```

4. **AnkiConnect** — no Anki: `Ferramentas → Complementos → Obter complementos`,
   cole `2055492159`, reinicie o Anki.
   Teste: com o Anki aberto, abra <http://localhost:8765> — deve aparecer a
   palavra `AnkiConnect`.

5. **Confira que o Anki é 23.10 ou mais novo** (`Ajuda → Sobre`). A oclusão
   nativa não existe antes disso, e o complemento antigo *Image Occlusion
   Enhanced* usa outro formato, incompatível com esta ferramenta.

## Uso

### 1. Ler a imagem

```
python -m ocluir ler slide.png --titulo "Divisões do encéfalo" ^
    --pergunta divisoes-encefalo --disciplina anatomia --aula 2026-08-10
```

Sai uma lista numerada dos rótulos que o OCR achou e um arquivo
`slide.plano.json`. O plano nasce **sem grupos** — de propósito.

```
   1. Divisoes do encefalo        conf  92.4   x=0.04 y=0.05
   2. Encefalo                    conf  92.7   x=0.46 y=0.17
   3. Cerebro                     conf  96.2   x=0.24 y=0.36
   4. Tronco encefalico           conf  93.2   x=0.65 y=0.36
   ...
```

### 2. Decidir o que vira cartão

Abra o plano e preencha `grupos`. Cada grupo é **um cartão**:

```json
"grupos": [
  { "rotulo": "Telencéfalo", "tokens": [6] },
  { "rotulo": "Diencéfalo",  "tokens": [5] },
  { "rotulo": "Mesencéfalo", "tokens": [7] }
]
```

Três recursos que resolvem os casos difíceis:

- **Vários tokens no mesmo grupo** → as máscaras aparecem e somem juntas. É
  como se pede "a enzima *e* o cofator deste passo, de uma vez".
- **`"caixa": [esquerda, topo, largura, altura]`** em frações de 0 a 1 → máscara
  manual, para quando o rótulo está dentro da imagem (não é texto selecionável),
  ou quando o alvo é uma região sem legenda nenhuma.
- **`modo`** → `esconder-tudo` (o diagrama inteiro coberto, revela um por vez) ou
  `esconder-uma` (só o alvo coberto, resto à vista).

### 3. Conferir

```
python -m ocluir previa slide.plano.json
```

Gera duas imagens: como o cartão vai aparecer, e uma versão com contorno e
número para confirmar que cada máscara cobre o rótulo certo. **Sempre olhe esta
segunda antes de enviar.**

### 4. Enviar

**Para o Anki no computador**, com o Anki aberto:

```
python -m ocluir enviar slide.plano.json
```

**Para o AnkiDroid**, sem computador na equação:

```
python -m ocluir empacotar slide.plano.json -o cartoes.apkg --conferir
```

Manda o `.apkg` para o tablet (Drive, e-mail, cabo) e toca nele. As imagens vão
dentro do arquivo. O `--conferir` reimporta o pacote com a biblioteca oficial do
Anki e relata o que entrou — vale a pena, porque pacote malformado só falha na
importação, no aparelho.

### Sem Tesseract

```
python -m ocluir caixas slide.png --titulo "Glicólise"
```

Acha as caixas de texto por análise de imagem e escreve uma versão numerada.
Este método **mede, não lê** — quem diz que a caixa 3 é a hexoquinase é você,
olhando a imagem numerada. É o caminho que funciona no chat do Claude, via
`chat/ocluir_chat.py`, que é o projeto inteiro num arquivo só.

### Extra: PDF do professor

```
pip install pypdfium2
python -m ocluir pdf aula.pdf --paginas 12-18
```

## Máscaras do mesmo tamanho

Ligado por padrão. A largura da máscara é informação: com "Ponte" e
"Fosfofrutoquinase-1" ocluídas, o retângulo curto só pode ser o primeiro, e o
cartão fica respondível pela geometria. Iguala-se o tamanho para que a única
pista seja a posição.

No plano, o campo `mascara_uniforme`: `"maior"` (padrão), um tamanho fixo como
`"0.18x0.04"`, ou vazio para desligar.

## O contrato do cartão

O `verificar` (e o `enviar`, antes de inserir) aplica as regras que vêm do
método, não do Anki:

| Regra | Nível | Por quê |
|---|---|---|
| mais de 12 cartões numa imagem | erro | é uma prancha virando baralho, não um conjunto de âncoras |
| mais de 6 cartões numa imagem | aviso | passa, mas peça o teste de auditoria |
| rótulo repetido na mesma imagem | erro | dois cartões competindo pela mesma resposta |
| rótulo com mais de 5 palavras | aviso | rótulo longo é mecanismo disfarçado de âncora |
| sem `pergunta` | aviso | o cartão nasce solto, sem vínculo com o mecanismo |
| máscara minúscula ou de área zero | aviso | quase sempre é ruído do OCR |
| duas máscaras se sobrepondo >25% | aviso | ao igualar tamanhos, a curta cresce e invade a vizinha |

`--forcar` passa por cima. Ele existe para quando a decisão foi consciente, não
para silenciar o aviso por pressa.

## O formato, para quem for mexer

O campo `Occlusion` da nota é texto puro, uma cloze por forma:

```
{{c1::image-occlusion:rect:left=0.0893:top=0.5688:width=0.1072:height=0.0224:oi=1}}<br>
{{c2::image-occlusion:rect:left=0.3497:top=0.5647:width=0.0992:height=0.0373:oi=1}}
```

- coordenadas são **frações de 0 a 1**, não pixels — o cartão sobrevive a
  redimensionar a imagem;
- o **ordinal da cloze é o agrupamento**: duas formas com `c1` viram um cartão só;
- **`oi=1`** é `occludeInactive`, o "Esconder tudo, adivinhar uma".

Confirmado contra `ts/routes/image-occlusion/shapes/` no código do Anki.

## Testes

```
pip install pytest
python -m pytest tests/ -q
```

146 testes. Os dois que mais valem:

- um **AnkiConnect falso** que valida o corpo exato das requisições, inclusive
  com a interface do Anki em português, caso em que os campos do notetype mudam
  de nome e o mapeamento por posição é o que salva;
- o `.apkg` gerado **sem dependência nenhuma** é reimportado pela biblioteca
  **oficial** do Anki e conferido do outro lado. Escrever com uma implementação e
  ler com outra, independente, é o que dá confiança de que o arquivo chega
  inteiro no AnkiDroid.

`pip install anki` habilita o segundo grupo; sem ele esses testes são pulados,
porque gerar o pacote não precisa da biblioteca — esse é justamente o ponto.

## O que este projeto deliberadamente não faz

Não escolhe as âncoras por você. Uma IA que lê um diagrama e cospe trinta
cartões produz exatamente o baralho de rótulos que o método existe para evitar.
A parte automatizável é a que vem *depois* da decisão — e é toda ela.
