"""Leitura de texto com posição — a metade *geométrica* do problema.

O ponto central do desenho: um modelo de visão é excelente para decidir *o que*
importa numa imagem e não confiável para dizer *onde exatamente* aquilo está,
em pixels. O Tesseract é o contrário — não faz ideia do que é uma enzima, mas
devolve a caixa de cada palavra com precisão de pixel.

Duas coisas foram medidas na construção deste módulo e mudaram o desenho:

1. **Uma passagem só de OCR tem recall instável.** No diagrama de teste, a
   mesma imagem em escalas diferentes achava conjuntos *diferentes* de rótulos:
   10/12 numa escala, 12/12 na união de quatro. Rodar várias passagens e unir
   por sobreposição espacial é o que torna o resultado utilizável.
2. **Borda de caixa vira caractere.** Fluxograma com retângulo em volta do
   texto produz tokens `|`, `(`, `_`. Sem filtro, eles viram máscaras
   minúsculas em cima de nada.

O julgamento — quais rótulos são âncoras — entra depois, em `plano.py`.
"""

from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

# Escalas e modos de segmentação de página que compõem a união. PSM 3 (auto)
# saiu melhor que PSM 11 (sparse) em diagrama com caixas — medido, não supatado.
PASSAGENS_PADRAO: tuple[tuple[float, int], ...] = (
    (1.0, 3),
    (1.15, 3),
    (1.5, 3),
    (2.0, 3),
)
PASSAGEM_UNICA: tuple[tuple[float, int], ...] = ((1.0, 3),)

# Acima disto o Tesseract fica lento sem ganhar recall.
LARGURA_MAXIMA_UTIL = 3600
# Duas caixas com sobreposição acima disto são a mesma palavra vista em duas
# passagens.
IOU_MESMA_PALAVRA = 0.5

# Token que não tem nenhuma letra nem dígito é borda, seta ou ruído.
SO_SIMBOLOS = re.compile(r"^[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+$")


class TesseractAusente(RuntimeError):
    """O binário do Tesseract não está no PATH."""


@dataclass
class Token:
    """Um pedaço de texto reconhecido, com a caixa onde ele vive."""

    id: int
    texto: str
    # Caixa em pixels da imagem original: (esquerda, topo, largura, altura).
    caixa: tuple[int, int, int, int]
    confianca: float
    palavras: list[str] = field(default_factory=list)

    def caixa_normalizada(
        self, largura: int, altura: int, folga: float = 0.0
    ) -> tuple[float, float, float, float]:
        """Converte para as frações 0–1 que o Anki guarda no campo Occlusion.

        `folga` é uma margem proporcional ao tamanho da própria caixa, para a
        máscara cobrir o texto inteiro mesmo com antisserrilhado nas bordas.
        """
        esq, topo, larg, alt = self.caixa
        margem_x = larg * folga
        margem_y = alt * folga

        esq = max(0.0, esq - margem_x)
        topo = max(0.0, topo - margem_y)
        larg = min(largura - esq, larg + 2 * margem_x)
        alt = min(altura - topo, alt + 2 * margem_y)

        return (esq / largura, topo / altura, larg / largura, alt / altura)


def _exigir_tesseract() -> str:
    caminho = shutil.which("tesseract")
    if not caminho:
        raise TesseractAusente(
            "Tesseract não encontrado no PATH.\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki "
            "(marque o idioma 'Portuguese' durante a instalação)\n"
            "  Linux:   sudo apt install tesseract-ocr tesseract-ocr-por"
        )
    return caminho


def _sobreposicao(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersecao = (x2 - x1) * (y2 - y1)
    uniao = aw * ah + bw * bh - intersecao
    return intersecao / uniao if uniao > 0 else 0.0


def _uma_passagem(
    imagem: Image.Image,
    psm: int,
    escala: float,
    confianca_minima: float,
    idioma: str,
) -> list[dict]:
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")

    processo = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", idioma, "--psm", str(psm), "tsv"],
        input=buffer.getvalue(),
        capture_output=True,
        check=False,
    )
    if processo.returncode != 0:
        erro = processo.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"Tesseract falhou (código {processo.returncode}): {erro}")

    texto = processo.stdout.decode("utf-8", "replace")
    # QUOTE_NONE: o TSV do Tesseract não escapa aspas, e uma aspa solta no
    # slide engoliria o resto da linha.
    leitor = csv.DictReader(io.StringIO(texto), delimiter="\t", quoting=csv.QUOTE_NONE)

    palavras = []
    for linha in leitor:
        conteudo = (linha.get("text") or "").strip()
        if not conteudo or len(conteudo) < 2 or SO_SIMBOLOS.match(conteudo):
            continue
        try:
            confianca = float(linha["conf"])
            caixa = (
                int(linha["left"]) / escala,
                int(linha["top"]) / escala,
                int(linha["width"]) / escala,
                int(linha["height"]) / escala,
            )
        except (KeyError, ValueError):
            continue
        if confianca < confianca_minima:
            continue
        palavras.append({"texto": conteudo, "conf": confianca, "caixa": caixa})

    return palavras


def _unir(passagens: list[list[dict]]) -> list[dict]:
    """Une palavras de várias passagens, mantendo a de maior confiança."""
    aceitas: list[dict] = []
    for palavras in passagens:
        for palavra in palavras:
            duplicada = None
            for indice, aceita in enumerate(aceitas):
                if _sobreposicao(palavra["caixa"], aceita["caixa"]) > IOU_MESMA_PALAVRA:
                    duplicada = indice
                    break
            if duplicada is None:
                aceitas.append(palavra)
            elif palavra["conf"] > aceitas[duplicada]["conf"]:
                aceitas[duplicada] = palavra
    return aceitas


def _agrupar_em_linhas(palavras: list[dict], fator_de_vao: float) -> list[list[dict]]:
    """Junta palavras vizinhas da mesma linha visual.

    O agrupamento por número de linha do próprio Tesseract não serve aqui: ele
    considera "Mesencéfalo" e um rótulo a 400 px de distância como a mesma
    linha, e a máscara resultante cobriria os dois e o vão entre eles. O
    critério correto é geométrico — sobreposição vertical *e* vão horizontal
    pequeno em relação à altura do texto.
    """
    if not palavras:
        return []

    # Passo 1 — faixas horizontais. Agrupar só por altura, sem olhar o eixo x,
    # porque duas palavras da mesma linha podem chegar em ordem invertida: o
    # OCR devolve topos que diferem por frações de pixel entre passagens, e
    # ordenar por topo colocaria a palavra da direita antes da esquerda.
    faixas: list[list[dict]] = []
    for palavra in sorted(palavras, key=lambda p: p["caixa"][1] + p["caixa"][3] / 2):
        _, py, _, ph = palavra["caixa"]
        centro = py + ph / 2

        for faixa in faixas:
            alturas = [p["caixa"][3] for p in faixa]
            centros = [p["caixa"][1] + p["caixa"][3] / 2 for p in faixa]
            referencia = sum(centros) / len(centros)
            if abs(centro - referencia) <= 0.6 * max(ph, max(alturas)):
                faixa.append(palavra)
                break
        else:
            faixas.append([palavra])

    # Passo 2 — dentro da faixa, quebrar onde o vão horizontal for grande.
    # É o que separa "Mesencéfalo" de um rótulo a 400 px na mesma altura, sem
    # o que a máscara cobriria os dois e o espaço vazio entre eles.
    linhas: list[list[dict]] = []
    for faixa in faixas:
        ordenada = sorted(faixa, key=lambda p: p["caixa"][0])
        atual = [ordenada[0]]

        for palavra in ordenada[1:]:
            anterior = atual[-1]
            ax, _, aw, ah = anterior["caixa"]
            px, _, _, ph = palavra["caixa"]
            vao = px - (ax + aw)

            if vao <= fator_de_vao * max(ph, ah):
                atual.append(palavra)
            else:
                linhas.append(atual)
                atual = [palavra]

        linhas.append(atual)

    return linhas


def _fundir(palavras: list[dict], identificador: int) -> Token:
    esquerdas = [p["caixa"][0] for p in palavras]
    topos = [p["caixa"][1] for p in palavras]
    direitas = [p["caixa"][0] + p["caixa"][2] for p in palavras]
    fundos = [p["caixa"][1] + p["caixa"][3] for p in palavras]

    esq, topo = min(esquerdas), min(topos)
    caixa = (
        int(round(esq)),
        int(round(topo)),
        int(round(max(direitas) - esq)),
        int(round(max(fundos) - topo)),
    )

    return Token(
        id=identificador,
        texto=" ".join(p["texto"] for p in palavras),
        caixa=caixa,
        confianca=round(sum(p["conf"] for p in palavras) / len(palavras), 1),
        palavras=[p["texto"] for p in palavras],
    )


def extrair_tokens(
    caminho: Path | str,
    idioma: str = "por",
    confianca_minima: float = 40.0,
    granularidade: str = "linha",
    fator_de_vao: float = 1.2,
    rapido: bool = False,
) -> tuple[list[Token], tuple[int, int]]:
    """Devolve os rótulos legíveis da imagem e o tamanho dela em pixels.

    `granularidade="linha"` funde palavras vizinhas numa só caixa, que é o que
    quase sempre se quer: "núcleo caudado" é um rótulo, não dois. Use
    `"palavra"` quando os rótulos estiverem colados uns nos outros.

    `rapido=True` faz uma passagem em vez de quatro — três vezes mais rápido e
    com recall menor. Serve para conferir enquadramento, não para produzir.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Imagem não encontrada: {caminho}")

    _exigir_tesseract()

    with Image.open(caminho) as arquivo:
        base = arquivo.convert("RGB")

    tamanho = (base.width, base.height)
    passagens_desejadas = PASSAGEM_UNICA if rapido else PASSAGENS_PADRAO

    resultados = []
    ja_rodadas: set[tuple[int, int]] = set()
    for escala, psm in passagens_desejadas:
        largura_alvo = int(base.width * escala)
        if largura_alvo > LARGURA_MAXIMA_UTIL and escala != 1.0:
            continue
        chave = (largura_alvo, psm)
        if chave in ja_rodadas:
            continue
        ja_rodadas.add(chave)

        if escala == 1.0:
            imagem = base
        else:
            imagem = base.resize(
                (largura_alvo, int(base.height * escala)), Image.LANCZOS
            )
        resultados.append(
            _uma_passagem(imagem, psm, escala, confianca_minima, idioma)
        )

    palavras = _unir(resultados)

    if granularidade == "palavra":
        tokens = [_fundir([p], indice) for indice, p in enumerate(palavras, start=1)]
    else:
        linhas = _agrupar_em_linhas(palavras, fator_de_vao)
        tokens = [
            _fundir(sorted(linha, key=lambda p: p["caixa"][0]), indice)
            for indice, linha in enumerate(linhas, start=1)
        ]

    # De cima para baixo, depois da esquerda para a direita: a ordem em que se
    # lê o diagrama, e portanto a ordem em que os ids fazem sentido.
    tokens.sort(key=lambda t: (t.caixa[1], t.caixa[0]))
    for novo_id, token in enumerate(tokens, start=1):
        token.id = novo_id

    return tokens, tamanho
