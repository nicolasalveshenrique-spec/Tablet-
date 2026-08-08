"""Monta `chat/ocluir_chat.py` — um arquivo só, para colar no chat do Claude.

O script de chat precisa ser autossuficiente: no sandbox que roda Python no
chat não dá para instalar pacote nem importar o repositório. Mas manter uma
segunda cópia do código à mão garantiria que as duas versões divergissem na
terceira correção de bug.

A saída é gerada a partir dos módulos de verdade, com os imports relativos
retirados. Fonte única, cópia derivada.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ORIGEM = RAIZ / "ocluir"
DESTINO = RAIZ / "chat" / "ocluir_chat.py"

# Ordem importa: `portatil` não depende de ninguém, `caixas` só do Pillow.
MODULOS = ["oclusao.py", "caixas.py", "portatil.py"]

CABECALHO = '''"""ocluir — versão de arquivo único, para rodar no chat do Claude.

Gerado por ferramentas/gerar_script_de_chat.py. NÃO EDITE À MÃO:
edite os módulos em ocluir/ e gere de novo.

Depende só da biblioteca padrão do Python, mais o Pillow para achar as caixas
de texto. Gerar o .apkg em si não precisa nem do Pillow.

Uso típico, em três passos:

    # 1. medir — escreve uma imagem com as caixas numeradas
    caixas, tamanho = detectar("slide.png")
    desenhar_numeradas("slide.png", caixas, "slide-caixas.png")

    # 2. ler a imagem numerada e dizer qual número é qual rótulo
    grupos = [
        {"rotulo": "Hexoquinase", "caixas": [3]},
        {"rotulo": "Aldolase",    "caixas": [9]},
    ]

    # 3. gerar o pacote para o AnkiDroid
    criar_apkg(
        "slide.png", caixas, grupos, "cartoes.apkg",
        titulo="Glicólise — fase preparatória",
        deck="Medicina::Bioquímica",
        modo=ESCONDER_UMA,
        tags=["oclusao", "pergunta::glicolise", "disc::bioquimica"],
    )
"""

from __future__ import annotations

'''

RODAPE = '''

# ==========================================================================
# Fachada — o que se chama no chat
# ==========================================================================


def criar_apkg(
    imagem,
    caixas_detectadas,
    grupos,
    destino,
    titulo="",
    deck="Medicina::Anatomia",
    modo=ESCONDER_TUDO,
    tags=None,
    verso_extra="",
    folga=0.06,
    uniforme=True,
):
    """Monta o .apkg a partir das caixas medidas e dos grupos que você decidiu.

    `grupos` é uma lista de dicionários. Cada um vira **um cartão**:

        {"rotulo": "Hexoquinase", "caixas": [3]}          # por número de caixa
        {"rotulo": "Etapa 3", "caixas": [7, 8]}           # duas máscaras juntas
        {"rotulo": "Sem legenda", "caixa": [.1,.2,.3,.05]}  # à mão, em frações

    O `rotulo` não aparece no cartão — o cartão mostra a imagem com a máscara.
    Ele existe para você conferir o que decidiu e para as mensagens de erro.
    """
    from pathlib import Path as _Path

    imagem = _Path(imagem)
    with Image.open(imagem) as arquivo:
        largura, altura = arquivo.size

    por_id = {c.id: c for c in caixas_detectadas}
    formas_por_grupo = []

    for indice, grupo in enumerate(grupos, start=1):
        rotulo = grupo.get("rotulo", f"grupo {indice}")
        formas = []

        if grupo.get("caixa"):
            valores = grupo["caixa"]
            if len(valores) != 4:
                raise ValueError(
                    f"{rotulo!r}: 'caixa' precisa de 4 números "
                    f"[esquerda, topo, largura, altura] em frações de 0 a 1."
                )
            formas.append(Forma(*(float(v) for v in valores)))
        else:
            numeros = grupo.get("caixas") or []
            if not numeros:
                raise ValueError(
                    f"{rotulo!r}: nem 'caixas' nem 'caixa' — não há o que ocluir."
                )
            for numero in numeros:
                if numero not in por_id:
                    disponiveis = ", ".join(str(i) for i in sorted(por_id))
                    raise ValueError(
                        f"{rotulo!r}: a caixa {numero} não existe. "
                        f"Disponíveis: {disponiveis}"
                    )
                formas.append(
                    Forma(*por_id[numero].normalizada(largura, altura, folga))
                )

        formas_por_grupo.append(formas)

    # Máscaras do mesmo tamanho: sem isto, a largura do retângulo entrega o
    # comprimento da palavra e o cartão fica respondível pela geometria.
    if uniforme:
        formas_por_grupo = uniformizar(
            formas_por_grupo, uniforme if isinstance(uniforme, tuple) else None
        )

    campo = montar_campo(formas_por_grupo, modo)

    nota = NotaPortatil(
        imagem=imagem,
        campo_occlusion=campo,
        cabecalho=titulo,
        verso_extra=verso_extra,
        tags=list(tags or ["oclusao"]),
        deck=deck,
    )
    return gerar_apkg([nota], destino)


def previa_das_mascaras(
    imagem, caixas_detectadas, grupos, destino, folga=0.06, uniforme=True
):
    """Desenha as máscaras sobre a imagem, para conferir antes de gerar.

    Vale o mesmo que no fluxo do computador: máscara torta é invisível numa
    lista de números e óbvia numa imagem.
    """
    from pathlib import Path as _Path
    from PIL import ImageDraw

    imagem = _Path(imagem)
    with Image.open(imagem) as arquivo:
        base = arquivo.convert("RGB")
    largura, altura = base.size
    desenho = ImageDraw.Draw(base)
    por_id = {c.id: c for c in caixas_detectadas}

    por_grupo = []
    for grupo in grupos:
        alvos = []
        if grupo.get("caixa"):
            alvos.append(Forma(*(float(v) for v in grupo["caixa"])))
        else:
            for numero in grupo.get("caixas") or []:
                if numero in por_id:
                    alvos.append(
                        Forma(*por_id[numero].normalizada(largura, altura, folga))
                    )
        por_grupo.append(alvos)

    if uniforme:
        por_grupo = uniformizar(
            por_grupo, uniforme if isinstance(uniforme, tuple) else None
        )

    for alvos in por_grupo:
        for forma in alvos:
            f = forma.limitada()
            desenho.rectangle(
                (
                    int(f.esquerda * largura),
                    int(f.topo * altura),
                    int((f.esquerda + f.largura) * largura),
                    int((f.topo + f.altura) * altura),
                ),
                fill=(255, 202, 0),
            )

    destino = _Path(destino)
    base.save(destino)
    return destino
'''


def _limpar(texto: str) -> str:
    """Tira docstring de módulo, imports relativos e `from __future__`."""
    texto = re.sub(r'\A"""(?:.|\n)*?"""\n', "", texto, count=1)
    linhas = []
    for linha in texto.splitlines():
        if linha.startswith("from __future__"):
            continue
        if re.match(r"^from \.\w* import", linha) or linha.startswith("from . import"):
            continue
        linhas.append(linha)
    return "\n".join(linhas).strip("\n")


def gerar() -> Path:
    partes = [CABECALHO]

    # Os imports de biblioteca padrão dos três módulos, reunidos no topo.
    partes.append(
        "import base64\nimport hashlib\nimport json\nimport re\nimport sqlite3\n"
        "import time\nimport zipfile\nfrom dataclasses import dataclass\n"
        "from pathlib import Path\n\nfrom PIL import Image\n"
    )

    for nome in MODULOS:
        corpo = _limpar((ORIGEM / nome).read_text(encoding="utf-8"))
        # Remove os imports já reunidos acima.
        corpo = "\n".join(
            linha
            for linha in corpo.splitlines()
            if not re.match(
                r"^(import (base64|hashlib|json|re|sqlite3|time|zipfile|tempfile)|"
                r"from (dataclasses|pathlib|PIL) import)",
                linha,
            )
        )
        partes.append(
            f"\n# {'=' * 74}\n# de ocluir/{nome}\n# {'=' * 74}\n\n{corpo.strip()}\n"
        )

    partes.append(RODAPE)

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text("\n".join(partes), encoding="utf-8")
    return DESTINO


if __name__ == "__main__":
    caminho = gerar()
    print(f"{caminho}  ({len(caminho.read_text(encoding='utf-8').splitlines())} linhas)")
