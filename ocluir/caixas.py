"""Acha caixas de texto sem OCR, para quando não há Tesseract disponível.

O caso de uso é o chat do Claude: lá não dá para instalar o Tesseract, e eu não
sou confiável para estimar coordenada em pixel a olho. Mas eu *sei ler* a
imagem — sei que aquilo escrito ali é "mesencéfalo".

Então o trabalho se divide de novo, só que em outro corte: este módulo acha
*onde* há texto, sem fazer ideia do que está escrito; eu olho a imagem com as
caixas numeradas e digo qual número é qual rótulo. Junta a precisão da medição
com a leitura que só a visão faz.

O método é projeção de perfil, que é o clássico para texto alinhado ao eixo:
faixas horizontais com tinta, e dentro de cada faixa, trechos separados por
espaço em branco. Não serve para texto girado ou manuscrito — serve para slide
e fluxograma, que é o que aparece nas aulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# Um pixel conta como tinta quando se afasta do fundo mais que isto, numa
# escala de 0 a 255. Baixo demais pega ruído de compressão de vídeo.
LIMIAR_DE_TINTA = 60
# Faixa ou trecho com menos pixels de tinta que isto é ruído, não texto.
MINIMO_DE_TINTA_NA_LINHA = 2
# Vão em branco, em pixels, que separa dois rótulos vizinhos na horizontal.
# Proporcional à altura da faixa, porque texto grande tem espaço maior.
FATOR_DE_VAO = 0.6


@dataclass
class CaixaDetectada:
    id: int
    caixa: tuple[int, int, int, int]  # esquerda, topo, largura, altura em px
    densidade: float  # fração de tinta dentro da caixa

    def normalizada(
        self, largura: int, altura: int, folga: float = 0.0
    ) -> tuple[float, float, float, float]:
        esq, topo, larg, alt = self.caixa
        mx, my = larg * folga, alt * folga
        esq = max(0.0, esq - mx)
        topo = max(0.0, topo - my)
        larg = min(largura - esq, larg + 2 * mx)
        alt = min(altura - topo, alt + 2 * my)
        return (esq / largura, topo / altura, larg / largura, alt / altura)


def _mascara_de_tinta(imagem: Image.Image) -> tuple[list[int], int, int]:
    """Devolve 1 para pixel de tinta e 0 para fundo, achatado em uma lista."""
    cinza = imagem.convert("L")
    largura, altura = cinza.size
    # Em modo "L" cada pixel é um byte, então tobytes() já é a lista de tons —
    # sem o custo (nem a depreciação) de getdata().
    pixels = cinza.tobytes()

    # O fundo é o tom mais frequente. Em slide e diagrama isso é quase sempre
    # verdade, e é mais robusto que assumir branco — fundo escuro funciona
    # igual.
    histograma = [0] * 256
    for valor in pixels:
        histograma[valor] += 1
    fundo = histograma.index(max(histograma))

    tinta = [1 if abs(p - fundo) > LIMIAR_DE_TINTA else 0 for p in pixels]
    return tinta, largura, altura


def _apagar_linhas(
    tinta: list[int], largura: int, altura: int, limite: int
) -> list[int]:
    """Remove traços longos — bordas de caixa, setas, réguas, sublinhados.

    Sem isto, a projeção de perfil não funciona em fluxograma: a borda vertical
    de um retângulo põe tinta em todas as linhas que ele ocupa, e a imagem
    inteira vira uma faixa só. Foi exatamente o que aconteceu na primeira
    versão — duas "caixas" cobrindo o diagrama inteiro.

    A distinção que sustenta o corte: um traço de letra é curto nas duas
    direções; moldura e seta são longos em uma delas.
    """
    limpo = list(tinta)

    for y in range(altura):
        base = y * largura
        inicio = None
        for x in range(largura + 1):
            aceso = x < largura and tinta[base + x]
            if aceso and inicio is None:
                inicio = x
            elif not aceso and inicio is not None:
                if x - inicio > limite:
                    for k in range(inicio, x):
                        limpo[base + k] = 0
                inicio = None

    for x in range(largura):
        inicio = None
        for y in range(altura + 1):
            aceso = y < altura and tinta[y * largura + x]
            if aceso and inicio is None:
                inicio = y
            elif not aceso and inicio is not None:
                if y - inicio > limite:
                    for k in range(inicio, y):
                        limpo[k * largura + x] = 0
                inicio = None

    return limpo


def _trechos(contagens: list[int], minimo: int, vao_maximo: int) -> list[tuple[int, int]]:
    """Trechos contíguos com tinta, tolerando buracos até `vao_maximo`."""
    trechos: list[tuple[int, int]] = []
    inicio = None
    branco = 0

    for indice, contagem in enumerate(contagens):
        if contagem >= minimo:
            if inicio is None:
                inicio = indice
            branco = 0
        elif inicio is not None:
            branco += 1
            if branco > vao_maximo:
                trechos.append((inicio, indice - branco))
                inicio = None
                branco = 0

    if inicio is not None:
        trechos.append((inicio, len(contagens) - 1 - branco))

    return [(a, b) for a, b in trechos if b >= a]


def detectar(
    caminho: Path | str,
    altura_minima: int = 12,
    largura_minima: int = 18,
    densidade_minima: float = 0.06,
    densidade_maxima: float = 0.92,
    limite_de_linha: int | None = None,
) -> tuple[list[CaixaDetectada], tuple[int, int]]:
    """Acha as caixas de texto prováveis e o tamanho da imagem.

    Os filtros de densidade são o que separa rótulo de moldura: a borda de um
    retângulo tem densidade altíssima na sua caixa (é quase toda tinta), e uma
    região vazia tem densidade quase nula. Texto fica no meio.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Imagem não encontrada: {caminho}")

    with Image.open(caminho) as arquivo:
        imagem = arquivo.convert("RGB")

    tinta, largura, altura = _mascara_de_tinta(imagem)

    if limite_de_linha is None:
        # Acima de ~5% do lado menor, um traço contínuo não é letra.
        limite_de_linha = max(25, int(min(largura, altura) * 0.05))
    tinta = _apagar_linhas(tinta, largura, altura, limite_de_linha)

    por_linha = [
        sum(tinta[y * largura : (y + 1) * largura]) for y in range(altura)
    ]
    faixas = _trechos(por_linha, MINIMO_DE_TINTA_NA_LINHA, vao_maximo=1)

    caixas: list[CaixaDetectada] = []
    for topo, base in faixas:
        alt_faixa = base - topo + 1
        if alt_faixa < altura_minima:
            continue

        por_coluna = [0] * largura
        for y in range(topo, base + 1):
            deslocamento = y * largura
            for x in range(largura):
                if tinta[deslocamento + x]:
                    por_coluna[x] += 1

        vao = max(3, int(alt_faixa * FATOR_DE_VAO))
        for esquerda, direita in _trechos(por_coluna, 1, vao_maximo=vao):
            larg = direita - esquerda + 1
            if larg < largura_minima:
                continue

            total = sum(por_coluna[esquerda : direita + 1])
            densidade = total / (larg * alt_faixa)
            if not (densidade_minima <= densidade <= densidade_maxima):
                continue

            caixas.append(
                CaixaDetectada(
                    id=0, caixa=(esquerda, topo, larg, alt_faixa),
                    densidade=round(densidade, 3),
                )
            )

    caixas.sort(key=lambda c: (c.caixa[1], c.caixa[0]))
    for numero, caixa in enumerate(caixas, start=1):
        caixa.id = numero

    return caixas, (largura, altura)


def desenhar_numeradas(
    caminho_imagem: Path | str,
    caixas: list[CaixaDetectada],
    destino: Path | str,
) -> Path:
    """Escreve a imagem com cada caixa contornada e numerada.

    É esta imagem que se olha para dizer "a caixa 7 é o mesencéfalo" — o passo
    que precisa de leitura, e que nenhuma medição resolve.
    """
    from PIL import ImageDraw, ImageFont

    caminho_imagem = Path(caminho_imagem)
    destino = Path(destino)

    with Image.open(caminho_imagem) as arquivo:
        imagem = arquivo.convert("RGB")

    desenho = ImageDraw.Draw(imagem)
    tamanho = max(11, int(imagem.height * 0.02))
    try:
        fonte = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", tamanho
        )
    except OSError:
        fonte = ImageFont.load_default()

    espessura = max(2, int(min(imagem.size) * 0.0025))

    for caixa in caixas:
        esq, topo, larg, alt = caixa.caixa
        desenho.rectangle(
            (esq, topo, esq + larg, topo + alt), outline=(220, 30, 90), width=espessura
        )
        etiqueta = str(caixa.id)
        limites = desenho.textbbox((0, 0), etiqueta, font=fonte)
        larg_txt = limites[2] - limites[0]
        alt_txt = limites[3] - limites[1]
        y = max(0, topo - alt_txt - 6)
        desenho.rectangle(
            (esq, y, esq + larg_txt + 8, y + alt_txt + 6), fill=(220, 30, 90)
        )
        desenho.text((esq + 4, y + 2), etiqueta, font=fonte, fill=(255, 255, 255))

    destino.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(destino)
    return destino
