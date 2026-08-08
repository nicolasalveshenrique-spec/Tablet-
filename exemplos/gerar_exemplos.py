"""Gera duas imagens sintéticas para exercitar o pipeline sem depender de
material com direito autoral.

Elas imitam os dois casos que motivaram o projeto:

  encefalo.png  — divisão anatômica hierárquica (rótulo por posição)
  glicolise.png — sequência de enzimas (rótulo por posição na ordem)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

AQUI = Path(__file__).parent

FUNDO = (252, 252, 250)
CAIXA = (232, 240, 252)
BORDA = (70, 98, 150)
TEXTO = (20, 30, 45)
SETA = (120, 135, 160)


def fonte(tamanho: int):
    for nome in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
        "arial.ttf",
    ):
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def caixa_com_texto(desenho, centro, texto, f, largura=260, altura=54):
    cx, cy = centro
    caixa = (cx - largura // 2, cy - altura // 2, cx + largura // 2, cy + altura // 2)
    desenho.rounded_rectangle(caixa, radius=8, fill=CAIXA, outline=BORDA, width=2)
    limites = desenho.textbbox((0, 0), texto, font=f)
    desenho.text(
        (cx - (limites[2] - limites[0]) // 2, cy - (limites[3] - limites[1]) // 2 - 3),
        texto,
        font=f,
        fill=TEXTO,
    )
    return caixa


def seta(desenho, de, para):
    desenho.line([de, para], fill=SETA, width=3)
    x, y = para
    desenho.polygon([(x, y), (x - 7, y - 12), (x + 7, y - 12)], fill=SETA)


def gerar_encefalo() -> Path:
    largura, altura = 1400, 900
    imagem = Image.new("RGB", (largura, altura), FUNDO)
    d = ImageDraw.Draw(imagem)
    f_titulo = fonte(34)
    f = fonte(24)

    d.text((60, 40), "Divisoes do encefalo", font=f_titulo, fill=TEXTO)

    caixa_com_texto(d, (700, 160), "Encefalo", f, largura=300)

    caixa_com_texto(d, (380, 330), "Cerebro", f)
    caixa_com_texto(d, (1020, 330), "Tronco encefalico", f, largura=320)

    caixa_com_texto(d, (200, 520), "Telencefalo", f, largura=240)
    caixa_com_texto(d, (560, 520), "Diencefalo", f, largura=240)

    caixa_com_texto(d, (830, 520), "Mesencefalo", f, largura=240)
    caixa_com_texto(d, (1090, 520), "Ponte", f, largura=200)
    caixa_com_texto(d, (1300, 520), "Bulbo", f, largura=180)

    caixa_com_texto(d, (200, 700), "Hemisferios cerebrais", f, largura=300)
    caixa_com_texto(d, (560, 700), "Talamo", f, largura=200)

    for de, para in [
        ((700, 187), (380, 303)),
        ((700, 187), (1020, 303)),
        ((380, 357), (200, 493)),
        ((380, 357), (560, 493)),
        ((1020, 357), (830, 493)),
        ((1020, 357), (1090, 493)),
        ((1020, 357), (1300, 493)),
        ((200, 547), (200, 673)),
        ((560, 547), (560, 673)),
    ]:
        seta(d, de, para)

    destino = AQUI / "encefalo.png"
    imagem.save(destino)
    return destino


def gerar_glicolise() -> Path:
    largura, altura = 900, 1250
    imagem = Image.new("RGB", (largura, altura), FUNDO)
    d = ImageDraw.Draw(imagem)
    f_titulo = fonte(32)
    f = fonte(22)
    f_enzima = fonte(20)

    d.text((50, 35), "Glicolise - fase preparatoria", font=f_titulo, fill=TEXTO)

    metabolitos = [
        "Glicose",
        "Glicose-6-fosfato",
        "Frutose-6-fosfato",
        "Frutose-1,6-bisfosfato",
        "Gliceraldeido-3-fosfato",
    ]
    enzimas = [
        "Hexoquinase",
        "Fosfoglicose isomerase",
        "Fosfofrutoquinase-1",
        "Aldolase",
    ]

    y = 140
    passo = 230
    for indice, metabolito in enumerate(metabolitos):
        caixa_com_texto(d, (300, y), metabolito, f, largura=420, altura=56)
        if indice < len(enzimas):
            seta(d, (300, y + 28), (300, y + passo - 28))
            d.text((350, y + passo // 2 - 34), enzimas[indice], font=f_enzima, fill=(150, 30, 30))
        y += passo

    destino = AQUI / "glicolise.png"
    imagem.save(destino)
    return destino


if __name__ == "__main__":
    for caminho in (gerar_encefalo(), gerar_glicolise()):
        print(caminho)
