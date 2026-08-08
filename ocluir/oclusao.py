"""O formato interno do cartão de oclusão nativo do Anki.

Confirmado contra o código-fonte do Anki (`ts/routes/image-occlusion/shapes/`,
`to-cloze.ts`, `base.ts`, `rectangle.ts`). O campo `Occlusion` da nota é texto
puro: uma cloze por forma, separadas por `<br>`.

    {{c1::image-occlusion:rect:left=0.1:top=0.2:width=0.3:height=0.05:oi=1}}<br>

Três coisas que decidem tudo e não estão documentadas no manual:

1. **As coordenadas são frações de 0 a 1**, não pixels. `toNormal(size)` divide
   pela largura/altura da imagem antes de serializar. Isso é ótimo: o cartão
   sobrevive a redimensionar a imagem.
2. **O ordinal da cloze é o agrupamento.** Duas formas com `c1` viram *um*
   cartão e são reveladas juntas. É assim que se faz "revele o passo inteiro".
3. **`oi=1` é `occludeInactive`** — "Esconder tudo, adivinhar uma". Sem ele, o
   modo é "Esconder uma, adivinhar uma", com o resto do diagrama à vista.
"""

from __future__ import annotations

from dataclasses import dataclass

# Modos, com os nomes que o Anki usa na interface.
ESCONDER_TUDO = "esconder-tudo"  # Hide All, Guess One  -> oi=1
ESCONDER_UMA = "esconder-uma"  # Hide One, Guess One  -> sem oi

MODOS = (ESCONDER_TUDO, ESCONDER_UMA)

# Nomes dos campos do notetype nativo, em inglês. Se o Anki estiver em
# português os nomes mudam, e por isso `anki.py` detecta por posição.
CAMPOS_PADRAO = ["Occlusion", "Image", "Header", "Back Extra", "Comments"]


def formatar_numero(valor: float) -> str:
    """Reproduz o `floatToDisplay` do Anki: 4 casas, sem zeros à toa."""
    texto = f"{round(valor, 4):.4f}".rstrip("0").rstrip(".")
    return texto or "0"


def _escapar(valor: str) -> str:
    # O parser do Anki separa propriedades por ":" e usa "\" como escape.
    return valor.replace("\\", "\\\\").replace(":", "\\:")


@dataclass
class Forma:
    """Um retângulo de máscara, em coordenadas normalizadas (0–1)."""

    esquerda: float
    topo: float
    largura: float
    altura: float

    def limitada(self) -> "Forma":
        """Impede que a máscara escape da imagem por causa da folga."""
        esq = min(max(self.esquerda, 0.0), 1.0)
        topo = min(max(self.topo, 0.0), 1.0)
        return Forma(
            esquerda=esq,
            topo=topo,
            largura=min(max(self.largura, 0.0), 1.0 - esq),
            altura=min(max(self.altura, 0.0), 1.0 - topo),
        )

    def para_cloze(self, ordinal: int, ocultar_inativas: bool) -> str:
        f = self.limitada()
        propriedades = [
            ("left", formatar_numero(f.esquerda)),
            ("top", formatar_numero(f.topo)),
            ("width", formatar_numero(f.largura)),
            ("height", formatar_numero(f.altura)),
        ]
        if ocultar_inativas:
            propriedades.append(("oi", "1"))

        corpo = "".join(f":{chave}={_escapar(valor)}" for chave, valor in propriedades)
        return f"{{{{c{ordinal}::image-occlusion:rect{corpo}}}}}"


def uniformizar(
    grupos: list[list[Forma]], alvo: tuple[float, float] | None = None
) -> list[list[Forma]]:
    """Iguala o tamanho de todas as máscaras, mantendo cada uma centrada.

    Por que isto importa, e não é estética: **a largura da máscara entrega o
    tamanho da palavra.** Numa prancha com "Ponte" e "Fosfofrutoquinase-1"
    ocluídas, o retângulo curto só pode ser a primeira. O cartão passa a ser
    respondível pela geometria, sem saber anatomia — e a revisão vira treino de
    reconhecer o formato do borrão.

    Com todas do mesmo tamanho, a única informação que sobra é a posição, que é
    exatamente a que o cartão deveria estar cobrando.

    `alvo` em frações de 0 a 1. Sem ele, usa a maior largura e a maior altura
    encontradas, para que nenhuma máscara fique menor que o texto que cobre.
    """
    todas = [forma for grupo in grupos for forma in grupo]
    if not todas:
        return grupos

    if alvo is None:
        largura_alvo = max(f.largura for f in todas)
        altura_alvo = max(f.altura for f in todas)
    else:
        largura_alvo, altura_alvo = alvo

    uniformes: list[list[Forma]] = []
    for grupo in grupos:
        novo = []
        for forma in grupo:
            centro_x = forma.esquerda + forma.largura / 2
            centro_y = forma.topo + forma.altura / 2
            novo.append(
                Forma(
                    esquerda=centro_x - largura_alvo / 2,
                    topo=centro_y - altura_alvo / 2,
                    largura=largura_alvo,
                    altura=altura_alvo,
                ).limitada()
            )
        uniformes.append(novo)

    return uniformes


def sobreposicao(a: Forma, b: Forma) -> float:
    """Fração da menor das duas caixas que está dentro da outra."""
    a, b = a.limitada(), b.limitada()
    x1 = max(a.esquerda, b.esquerda)
    y1 = max(a.topo, b.topo)
    x2 = min(a.esquerda + a.largura, b.esquerda + b.largura)
    y2 = min(a.topo + a.altura, b.topo + b.altura)
    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersecao = (x2 - x1) * (y2 - y1)
    menor = min(a.largura * a.altura, b.largura * b.altura)
    return intersecao / menor if menor > 0 else 0.0


def montar_campo(grupos: list[list[Forma]], modo: str = ESCONDER_TUDO) -> str:
    """Monta o conteúdo completo do campo `Occlusion`.

    Cada elemento de `grupos` é um cartão. Um grupo com mais de uma forma
    revela todas as suas formas ao mesmo tempo — é o mecanismo para "esta
    etapa da via tem enzima e cofator, e os dois aparecem juntos".
    """
    if modo not in MODOS:
        raise ValueError(f"Modo desconhecido: {modo!r}. Use um de {MODOS}.")
    if not grupos:
        raise ValueError("Nenhum grupo de oclusão: a nota não geraria cartão nenhum.")

    ocultar = modo == ESCONDER_TUDO
    linhas = []
    for ordinal, formas in enumerate(grupos, start=1):
        if not formas:
            raise ValueError(f"O grupo {ordinal} está vazio.")
        for forma in formas:
            linhas.append(forma.para_cloze(ordinal, ocultar))

    return "<br>".join(linhas)


def contar_cartoes(campo: str) -> int:
    """Quantos cartões o Anki vai gerar a partir deste campo."""
    import re

    ordinais = {int(n) for n in re.findall(r"\{\{c(\d+)::image-occlusion:", campo)}
    return len(ordinais)
