"""Prévia visual — ver a máscara antes de ela virar cartão.

Esta é a peça que torna o resto confiável. Coordenada errada é invisível num
JSON e óbvia numa imagem. Sem a prévia, o modo de falha seria descobrir a
máscara torta na revisão, três dias depois, quando corrigir custa mais.

Gera dois arquivos: um com as máscaras aplicadas (o que você veria na frente do
cartão) e outro com contorno e número, para conferir a correspondência entre
cada máscara e o rótulo que ela deveria cobrir.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# A mesma cor que o Anki usa por padrão nas máscaras.
COR_MASCARA = (255, 202, 0)
COR_CONTORNO = (10, 44, 238)
COR_TEXTO = (255, 255, 255)


def _fonte(tamanho: int):
    for nome in (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def _para_pixels(forma, largura: int, altura: int) -> tuple[int, int, int, int]:
    f = forma.limitada()
    esq = int(round(f.esquerda * largura))
    topo = int(round(f.topo * altura))
    return (
        esq,
        topo,
        max(esq + 1, int(round((f.esquerda + f.largura) * largura))),
        max(topo + 1, int(round((f.topo + f.altura) * altura))),
    )


def gerar(
    caminho_imagem: Path | str,
    grupos_de_formas: list[tuple[str, list]],
    destino: Path | str,
) -> tuple[Path, Path]:
    """Escreve `destino` (mascarado) e `destino` com sufixo `-conferencia`."""
    caminho_imagem = Path(caminho_imagem)
    destino = Path(destino)

    with Image.open(caminho_imagem) as arquivo:
        base = arquivo.convert("RGB")

    largura, altura = base.size
    tamanho_fonte = max(12, int(altura * 0.022))
    fonte = _fonte(tamanho_fonte)

    mascarada = base.copy()
    desenho_mascara = ImageDraw.Draw(mascarada)

    conferencia = base.copy()
    desenho_conf = ImageDraw.Draw(conferencia)

    espessura = max(2, int(min(largura, altura) * 0.003))

    for ordinal, (rotulo, formas) in enumerate(grupos_de_formas, start=1):
        for forma in formas:
            caixa = _para_pixels(forma, largura, altura)
            desenho_mascara.rectangle(caixa, fill=COR_MASCARA)
            desenho_conf.rectangle(caixa, outline=COR_CONTORNO, width=espessura)

            etiqueta = f"{ordinal}"
            caixa_texto = desenho_conf.textbbox((0, 0), etiqueta, font=fonte)
            larg_texto = caixa_texto[2] - caixa_texto[0]
            alt_texto = caixa_texto[3] - caixa_texto[1]

            x = caixa[0]
            y = max(0, caixa[1] - alt_texto - 6)
            desenho_conf.rectangle(
                (x, y, x + larg_texto + 8, y + alt_texto + 6), fill=COR_CONTORNO
            )
            desenho_conf.text((x + 4, y + 2), etiqueta, font=fonte, fill=COR_TEXTO)

        # O número também vai na versão mascarada, senão não dá para saber qual
        # máscara corresponde a qual cartão.
        if formas:
            caixa = _para_pixels(formas[0], largura, altura)
            desenho_mascara.text(
                (caixa[0] + 4, caixa[1] + 2), str(ordinal), font=fonte, fill=(0, 0, 0)
            )

    destino.parent.mkdir(parents=True, exist_ok=True)
    mascarada.save(destino)

    destino_conf = destino.with_name(f"{destino.stem}-conferencia{destino.suffix}")
    conferencia.save(destino_conf)

    return destino, destino_conf
