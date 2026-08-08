"""O *plano de oclusão* — o arquivo onde o julgamento acontece.

Este é o formato que separa as duas metades do trabalho. O `ocluir ler` produz
um plano cheio de candidatos e nenhum grupo. Você (ou o Claude, lendo a imagem
junto com a lista de candidatos) preenche `grupos`. O `ocluir enviar` executa.

A decisão de qual rótulo vira cartão nunca é do programa. Isso é deliberado e
vem do próprio método: *decidir quais peças são âncoras é o teste de auditoria,
o núcleo do método.* O que se automatiza é o que vem depois da decisão.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .oclusao import ESCONDER_TUDO, Forma
from .ocr import Token

VERSAO = 1


def slugificar(texto: str) -> str:
    import unicodedata

    normalizado = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in normalizado if not unicodedata.combining(c))
    limpo = re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()
    return limpo or "sem-titulo"


@dataclass
class Grupo:
    """Um cartão. O rótulo é a resposta; a caixa é onde ela mora na imagem."""

    rotulo: str
    # Ids de tokens do OCR. A caixa do grupo é a união das caixas deles.
    tokens: list[int] = field(default_factory=list)
    # Caixa manual em frações 0–1: [esquerda, topo, largura, altura].
    # Usada quando o OCR não leu o rótulo (texto em imagem, seta sem legenda,
    # região sem texto nenhum). Tem precedência sobre `tokens`.
    caixa: list[float] | None = None
    nota: str = ""

    def formas(self, tokens_por_id: dict[int, Token], tamanho, folga: float) -> list[Forma]:
        if self.caixa is not None:
            if len(self.caixa) != 4:
                raise ValueError(
                    f"Grupo {self.rotulo!r}: 'caixa' precisa de 4 números "
                    f"[esquerda, topo, largura, altura], recebi {len(self.caixa)}."
                )
            return [Forma(*(float(v) for v in self.caixa))]

        if not self.tokens:
            raise ValueError(
                f"Grupo {self.rotulo!r} não tem 'tokens' nem 'caixa' — "
                "não há o que ocluir."
            )

        largura, altura = tamanho
        formas = []
        for token_id in self.tokens:
            token = tokens_por_id.get(token_id)
            if token is None:
                disponiveis = ", ".join(str(i) for i in sorted(tokens_por_id)[:12])
                raise ValueError(
                    f"Grupo {self.rotulo!r} cita o token {token_id}, que não existe. "
                    f"Ids disponíveis começam em: {disponiveis}…"
                )
            formas.append(Forma(*token.caixa_normalizada(largura, altura, folga)))
        return formas


@dataclass
class Plano:
    imagem: str
    titulo: str = ""
    deck: str = "Medicina::Anatomia"
    modo: str = ESCONDER_TUDO
    # Metadados que viram tag, no esquema já decidido no vault.
    pergunta: str = ""
    disciplina: str = ""
    aula: str = ""
    verso_extra: str = ""
    comentarios: str = ""
    folga: float = 0.06
    grupos: list[Grupo] = field(default_factory=list)
    # Preenchido pelo `ler`; só serve de referência para escolher os ids.
    candidatos: list[dict] = field(default_factory=list)
    tamanho: list[int] = field(default_factory=list)
    versao: int = VERSAO

    # -- tags ---------------------------------------------------------------

    def tags(self) -> list[str]:
        """Monta as tags no esquema do vault, pulando o que estiver vazio."""
        tags = ["oclusao"]
        if self.pergunta:
            tags.append(f"pergunta::{slugificar(self.pergunta)}")
        if self.disciplina:
            tags.append(f"disc::{slugificar(self.disciplina)}")
        if self.aula:
            tags.append(f"aula::{self.aula}")
        return tags

    # -- serialização -------------------------------------------------------

    def para_json(self) -> str:
        dados = asdict(self)
        return json.dumps(dados, ensure_ascii=False, indent=2)

    def salvar(self, caminho: Path | str) -> Path:
        caminho = Path(caminho)
        caminho.write_text(self.para_json(), encoding="utf-8")
        return caminho

    @classmethod
    def carregar(cls, caminho: Path | str) -> "Plano":
        caminho = Path(caminho)
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        grupos = [Grupo(**g) for g in dados.pop("grupos", [])]
        dados.pop("versao", None)
        conhecidos = {f for f in cls.__dataclass_fields__ if f != "grupos"}
        desconhecidos = set(dados) - conhecidos
        if desconhecidos:
            raise ValueError(
                f"Campos desconhecidos no plano: {', '.join(sorted(desconhecidos))}"
            )
        return cls(grupos=grupos, **dados)


def plano_a_partir_do_ocr(
    caminho_imagem: Path | str,
    tokens: list[Token],
    tamanho: tuple[int, int],
    **metadados,
) -> Plano:
    """Cria o plano inicial: candidatos preenchidos, decisão em aberto."""
    caminho_imagem = Path(caminho_imagem)
    largura, altura = tamanho

    candidatos = []
    for token in tokens:
        esq, topo, larg, alt = token.caixa_normalizada(largura, altura)
        candidatos.append(
            {
                "id": token.id,
                "texto": token.texto,
                "confianca": token.confianca,
                # A caixa em pixels é a fonte da verdade — guardar só a versão
                # normalizada e arredondada custaria um erro de 1–2 px na volta,
                # justamente onde a precisão é a razão de existir do OCR.
                "caixa_px": list(token.caixa),
                # Redundante, mas é o que se lê ao abrir o arquivo para decidir.
                "posicao": {
                    "esquerda": round(esq, 3),
                    "topo": round(topo, 3),
                    "largura": round(larg, 3),
                    "altura": round(alt, 3),
                },
            }
        )

    return Plano(
        imagem=caminho_imagem.name,
        tamanho=[largura, altura],
        candidatos=candidatos,
        **metadados,
    )
