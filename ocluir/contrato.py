"""O contrato do cartão, aplicado à oclusão de imagem.

O vault já define um contrato para cartões de texto: uma coisa só por frente,
verso de no máximo uma linha, nada de lista, nada de mecanismo. A oclusão de
imagem não escapa desse contrato — ela o cumpre de um jeito diferente, e cria
uma tentação nova que o contrato de texto não previa.

A tentação é esta: uma prancha de anatomia com 30 rótulos permite gerar 30
cartões em dois cliques. Nenhum deles é errado isoladamente e o conjunto é
exatamente o "baralho de rótulos" que o método existe para evitar.

Por isso as regras abaixo são quase todas sobre *quantidade* e *vínculo*, não
sobre forma. A forma o Anki já garante.
"""

from __future__ import annotations

from dataclasses import dataclass

from .plano import Plano

ERRO = "erro"
AVISO = "aviso"

# Acima disto não é um conjunto de âncoras, é uma prancha inteira virando
# baralho. Bloqueia, e só passa com --forcar.
TETO_DURO = 12
# Acima disto ainda passa, mas merece um segundo olhar.
TETO_CONFORTAVEL = 6
# Um rótulo com mais palavras que isto provavelmente é um mecanismo disfarçado
# de âncora — o mesmo erro que a regra do "verso de uma linha" pega no texto.
PALAVRAS_MAXIMAS_NO_ROTULO = 5

# Área mínima de máscara, em fração da imagem. Abaixo disso a caixa costuma ser
# ruído do OCR (um traço, um acento solto) e não um rótulo.
AREA_MINIMA = 0.00015


@dataclass
class Achado:
    nivel: str
    mensagem: str

    def __str__(self) -> str:
        marca = "ERRO " if self.nivel == ERRO else "aviso"
        return f"  [{marca}] {self.mensagem}"


def verificar(plano: Plano, tokens_por_id: dict) -> list[Achado]:
    achados: list[Achado] = []
    total = len(plano.grupos)

    if total == 0:
        achados.append(Achado(ERRO, "O plano não tem grupos: nenhum cartão seria criado."))
        return achados

    # --- quantidade ------------------------------------------------------
    if total > TETO_DURO:
        achados.append(
            Achado(
                ERRO,
                f"{total} cartões numa imagem só (teto: {TETO_DURO}). "
                "Isso é uma prancha virando baralho, não um conjunto de âncoras. "
                "Divida a imagem em regiões e faça uma nota por região — ou use "
                "--forcar se você decidiu conscientemente que é esse o caso.",
            )
        )
    elif total > TETO_CONFORTAVEL:
        achados.append(
            Achado(
                AVISO,
                f"{total} cartões numa imagem só. Passa, mas vale o teste de "
                "auditoria: se você apagasse metade destes, a pergunta lógica "
                "ainda poderia ser respondida?",
            )
        )

    # --- vínculo com a pergunta lógica -----------------------------------
    if not plano.pergunta:
        achados.append(
            Achado(
                AVISO,
                "Sem 'pergunta': o cartão nasce solto, sem a tag pergunta:: que "
                "liga ele ao mecanismo que o justifica. É a tag que sustenta o "
                "teste central do método.",
            )
        )
    if not plano.titulo:
        achados.append(
            Achado(
                AVISO,
                "Sem 'titulo': o cabeçalho do cartão fica vazio e a imagem "
                "aparece sem contexto na revisão.",
            )
        )

    # --- forma de cada grupo ---------------------------------------------
    rotulos_vistos: dict[str, int] = {}
    for indice, grupo in enumerate(plano.grupos, start=1):
        rotulo = grupo.rotulo.strip()

        if not rotulo:
            achados.append(Achado(ERRO, f"Grupo {indice} está sem rótulo."))
            continue

        palavras = len(rotulo.split())
        if palavras > PALAVRAS_MAXIMAS_NO_ROTULO:
            achados.append(
                Achado(
                    AVISO,
                    f"{rotulo!r} tem {palavras} palavras. Rótulo longo costuma ser "
                    "mecanismo disfarçado de âncora — mecanismo mora na pergunta "
                    "lógica, não no cartão.",
                )
            )

        chave = rotulo.casefold()
        if chave in rotulos_vistos:
            achados.append(
                Achado(
                    ERRO,
                    f"{rotulo!r} aparece nos grupos {rotulos_vistos[chave]} e {indice}. "
                    "Dois cartões com a mesma resposta na mesma imagem competem "
                    "entre si na revisão.",
                )
            )
        else:
            rotulos_vistos[chave] = indice

        # A caixa precisa existir e ter tamanho plausível.
        try:
            formas = grupo.formas(tokens_por_id, plano.tamanho or [1, 1], plano.folga)
        except ValueError as erro:
            achados.append(Achado(ERRO, str(erro)))
            continue

        for forma in formas:
            limitada = forma.limitada()
            area = limitada.largura * limitada.altura
            if area < AREA_MINIMA:
                achados.append(
                    Achado(
                        AVISO,
                        f"{rotulo!r}: máscara muito pequena ({area:.5f} da imagem). "
                        "Confira na prévia se ela cobre o rótulo inteiro.",
                    )
                )
            if limitada.largura <= 0 or limitada.altura <= 0:
                achados.append(
                    Achado(ERRO, f"{rotulo!r}: máscara com largura ou altura zero.")
                )

    return achados


def tem_erro(achados: list[Achado]) -> bool:
    return any(a.nivel == ERRO for a in achados)
