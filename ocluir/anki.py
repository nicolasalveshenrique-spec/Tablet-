"""Conversa com o Anki pelo AnkiConnect.

O AnkiConnect sobe um servidor HTTP em localhost:8765 enquanto o Anki está
aberto, e só responde à própria máquina. Instalação: Ferramentas → Complementos
→ Obter complementos → código 2055492159 → reiniciar.

Um detalhe que quebra silenciosamente e por isso é tratado aqui: se o Anki
estiver em português, os campos do notetype de oclusão têm nomes traduzidos.
Procurar pelo campo "Occlusion" pelo nome falharia. A detecção abaixo acha o
notetype pelo nome *e* confere a assinatura dos campos, e mapeia por posição.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import requests

ENDERECO_PADRAO = "http://127.0.0.1:8765"
VERSAO_API = 6

# Ordem dos campos no notetype nativo, que é estável entre idiomas.
POSICAO_OCCLUSION = 0
POSICAO_IMAGEM = 1
POSICAO_CABECALHO = 2
POSICAO_VERSO_EXTRA = 3
POSICAO_COMENTARIOS = 4
CAMPOS_ESPERADOS = 5


class AnkiIndisponivel(RuntimeError):
    pass


class AnkiErro(RuntimeError):
    pass


class Anki:
    def __init__(self, endereco: str = ENDERECO_PADRAO, tempo_limite: float = 20.0):
        self.endereco = endereco
        self.tempo_limite = tempo_limite

    def chamar(self, acao: str, **parametros):
        corpo = {"action": acao, "version": VERSAO_API}
        if parametros:
            corpo["params"] = parametros

        try:
            resposta = requests.post(
                self.endereco, data=json.dumps(corpo).encode("utf-8"),
                timeout=self.tempo_limite,
            )
        except requests.exceptions.ConnectionError as erro:
            raise AnkiIndisponivel(
                f"Não consegui falar com o Anki em {self.endereco}.\n"
                "  1. O Anki está aberto no computador?\n"
                "  2. O AnkiConnect está instalado? (código 2055492159)\n"
                "  3. Abra http://localhost:8765 no navegador — deve aparecer "
                "a palavra 'AnkiConnect'."
            ) from erro

        resposta.raise_for_status()
        dados = resposta.json()
        if dados.get("error"):
            raise AnkiErro(f"{acao}: {dados['error']}")
        return dados.get("result")

    # -- descoberta ---------------------------------------------------------

    def versao(self) -> int:
        return self.chamar("version")

    def nomes_de_modelos(self) -> list[str]:
        return self.chamar("modelNames")

    def campos_do_modelo(self, modelo: str) -> list[str]:
        return self.chamar("modelFieldNames", modelName=modelo)

    def detectar_modelo_de_oclusao(self) -> tuple[str, list[str]]:
        """Acha o notetype de oclusão de imagem e devolve (nome, campos)."""
        modelos = self.nomes_de_modelos()

        marcas = ("image occlusion", "oclusão de imagem", "oclusao de imagem")
        candidatos = [m for m in modelos if any(x in m.casefold() for x in marcas)]

        if not candidatos:
            raise AnkiErro(
                "Nenhum notetype de oclusão de imagem encontrado.\n"
                "  A oclusão nativa existe a partir do Anki 23.10. Confira sua "
                "versão em Ajuda → Sobre.\n"
                "  Se estiver atualizado, crie um cartão de oclusão pela "
                "interface uma vez — o Anki só cria o notetype no primeiro uso."
            )

        # Prefere o que tem exatamente a assinatura de 5 campos do nativo, para
        # não cair num "Image Occlusion Enhanced" antigo, que é incompatível.
        for nome in sorted(candidatos, key=len):
            campos = self.campos_do_modelo(nome)
            if len(campos) >= CAMPOS_ESPERADOS:
                return nome, campos

        nome = candidatos[0]
        raise AnkiErro(
            f"O notetype {nome!r} tem {len(self.campos_do_modelo(nome))} campos, "
            f"e o nativo tem {CAMPOS_ESPERADOS}. Provavelmente é o complemento "
            "'Image Occlusion Enhanced', que usa outro formato e não é compatível "
            "com esta ferramenta."
        )

    def decks(self) -> list[str]:
        return self.chamar("deckNames")

    def garantir_deck(self, deck: str) -> None:
        if deck not in self.decks():
            self.chamar("createDeck", deck=deck)

    # -- escrita ------------------------------------------------------------

    def guardar_midia(self, caminho: Path | str, nome_destino: str | None = None) -> str:
        caminho = Path(caminho)
        dados = base64.b64encode(caminho.read_bytes()).decode("ascii")
        nome = nome_destino or caminho.name
        return self.chamar("storeMediaFile", filename=nome, data=dados)

    def buscar_notas(self, consulta: str) -> list[int]:
        return self.chamar("findNotes", query=consulta)

    def adicionar_nota(
        self,
        deck: str,
        modelo: str,
        campos: dict[str, str],
        tags: list[str],
        permitir_duplicata: bool = False,
    ) -> int:
        nota = {
            "deckName": deck,
            "modelName": modelo,
            "fields": campos,
            "tags": tags,
            "options": {
                "allowDuplicate": permitir_duplicata,
                "duplicateScope": "deck",
            },
        }
        return self.chamar("addNote", note=nota)


def montar_campos(
    nomes_dos_campos: list[str],
    occlusion: str,
    html_da_imagem: str,
    cabecalho: str = "",
    verso_extra: str = "",
    comentarios: str = "",
) -> dict[str, str]:
    """Mapeia por posição, o que sobrevive ao Anki traduzido."""
    if len(nomes_dos_campos) < CAMPOS_ESPERADOS:
        raise AnkiErro(
            f"Esperava {CAMPOS_ESPERADOS} campos no notetype de oclusão, "
            f"encontrei {len(nomes_dos_campos)}: {nomes_dos_campos}"
        )

    valores = [occlusion, html_da_imagem, cabecalho, verso_extra, comentarios]
    campos = {nome: "" for nome in nomes_dos_campos}
    for posicao, valor in enumerate(valores):
        campos[nomes_dos_campos[posicao]] = valor
    return campos
