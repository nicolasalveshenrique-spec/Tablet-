"""Linha de comando do ocluir."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .anki import Anki, AnkiErro, AnkiIndisponivel, montar_campos
from .contrato import ERRO, tem_erro, verificar
from .oclusao import ESCONDER_TUDO, MODOS, contar_cartoes, montar_campo
from .ocr import TesseractAusente, Token, extrair_tokens
from .plano import Plano, plano_a_partir_do_ocr, slugificar
from . import previa as previa_mod


def _erro(mensagem: str) -> int:
    print(f"\n{mensagem}\n", file=sys.stderr)
    return 1


def _tokens_do_plano(plano: Plano) -> dict[int, Token]:
    """Reconstrói os tokens a partir dos candidatos guardados no plano.

    O plano é autossuficiente de propósito: depois do `ler`, nada precisa rodar
    OCR de novo. Isso torna o arquivo reproduzível e permite editá-lo à mão
    numa máquina que nem tem o Tesseract instalado.
    """
    if not plano.tamanho:
        return {}
    largura, altura = plano.tamanho
    tokens: dict[int, Token] = {}

    for candidato in plano.candidatos:
        caixa = candidato.get("caixa_px")
        if caixa is None:
            # Plano antigo, sem a caixa em pixels: reconstrói da normalizada,
            # aceitando o erro de arredondamento de um ou dois pixels.
            posicao = candidato["posicao"]
            caixa = [
                int(round(posicao["esquerda"] * largura)),
                int(round(posicao["topo"] * altura)),
                int(round(posicao["largura"] * largura)),
                int(round(posicao["altura"] * altura)),
            ]

        tokens[candidato["id"]] = Token(
            id=candidato["id"],
            texto=candidato["texto"],
            caixa=tuple(caixa),
            confianca=candidato.get("confianca", 0.0),
        )
    return tokens


def _formas_dos_grupos(plano: Plano):
    tokens = _tokens_do_plano(plano)
    tamanho = tuple(plano.tamanho) if plano.tamanho else (1, 1)
    return [
        (grupo.rotulo, grupo.formas(tokens, tamanho, plano.folga))
        for grupo in plano.grupos
    ]


# --------------------------------------------------------------------------
# ler
# --------------------------------------------------------------------------


def comando_ler(args) -> int:
    caminho = Path(args.imagem)
    try:
        tokens, tamanho = extrair_tokens(
            caminho,
            idioma=args.idioma,
            confianca_minima=args.confianca,
            granularidade="palavra" if args.palavra else "linha",
            fator_de_vao=args.vao,
            rapido=args.rapido,
        )
    except TesseractAusente as e:
        return _erro(str(e))
    except FileNotFoundError as e:
        return _erro(str(e))

    plano = plano_a_partir_do_ocr(
        caminho,
        tokens,
        tamanho,
        titulo=args.titulo or "",
        deck=args.deck,
        modo=args.modo,
        pergunta=args.pergunta or "",
        disciplina=args.disciplina or "",
        aula=args.aula or "",
    )

    destino = Path(args.saida) if args.saida else caminho.with_suffix(".plano.json")
    plano.salvar(destino)

    print(f"\nImagem: {caminho.name}  ({tamanho[0]}×{tamanho[1]} px)")
    print(f"Plano:  {destino}")
    print(f"\n{len(tokens)} candidatos legíveis:\n")
    for token in tokens:
        esq, topo, *_ = token.caixa_normalizada(*tamanho)
        print(
            f"  {token.id:>3}. {token.texto[:52]:<52} "
            f"conf {token.confianca:>5.1f}   x={esq:.2f} y={topo:.2f}"
        )

    print(
        "\nO OCR já fez a parte dele: as caixas acima estão em pixel exato.\n"
        "Falta a parte que não se automatiza — decidir quais desses rótulos são\n"
        "âncoras. Preencha 'grupos' no plano e rode:\n"
        f"  ocluir previa {destino}\n"
    )
    return 0


# --------------------------------------------------------------------------
# previa / verificar
# --------------------------------------------------------------------------


def _carregar(args) -> tuple[Plano, Path] | None:
    caminho = Path(args.plano)
    try:
        plano = Plano.carregar(caminho)
    except (ValueError, KeyError, TypeError) as e:
        print(f"\nPlano inválido: {e}\n", file=sys.stderr)
        return None
    return plano, caminho


def comando_previa(args) -> int:
    carregado = _carregar(args)
    if carregado is None:
        return 1
    plano, caminho_plano = carregado

    imagem = caminho_plano.parent / plano.imagem
    if not imagem.exists():
        return _erro(f"Imagem do plano não encontrada: {imagem}")

    if not plano.grupos:
        return _erro(
            "O plano ainda não tem grupos. Preencha 'grupos' com os rótulos que "
            "você decidiu que são âncoras."
        )

    try:
        grupos = _formas_dos_grupos(plano)
    except ValueError as e:
        return _erro(str(e))

    destino = Path(args.saida) if args.saida else imagem.with_name(
        f"{imagem.stem}-previa.png"
    )
    mascarada, conferencia = previa_mod.gerar(imagem, grupos, destino)

    print(f"\n{len(grupos)} cartões seriam criados.\n")
    print(f"  frente do cartão:  {mascarada}")
    print(f"  conferência:       {conferencia}")
    print("\nAbra a conferência e confirme que cada contorno cobre o rótulo certo.")

    achados = verificar(plano, _tokens_do_plano(plano))
    if achados:
        print("\nContrato do cartão:")
        for achado in achados:
            print(achado)
    print()
    return 0


def comando_verificar(args) -> int:
    carregado = _carregar(args)
    if carregado is None:
        return 1
    plano, _ = carregado

    achados = verificar(plano, _tokens_do_plano(plano))
    if not achados:
        print("\nPlano limpo — nenhum apontamento do contrato.\n")
        return 0

    print()
    for achado in achados:
        print(achado)
    print()
    return 1 if tem_erro(achados) else 0


# --------------------------------------------------------------------------
# enviar
# --------------------------------------------------------------------------


def comando_enviar(args) -> int:
    carregado = _carregar(args)
    if carregado is None:
        return 1
    plano, caminho_plano = carregado

    imagem = caminho_plano.parent / plano.imagem
    if not imagem.exists():
        return _erro(f"Imagem do plano não encontrada: {imagem}")

    achados = verificar(plano, _tokens_do_plano(plano))
    for achado in achados:
        print(achado)
    if tem_erro(achados) and not args.forcar:
        return _erro("O plano tem erros de contrato. Corrija, ou use --forcar.")

    try:
        grupos = _formas_dos_grupos(plano)
        campo_occlusion = montar_campo([formas for _, formas in grupos], plano.modo)
    except ValueError as e:
        return _erro(str(e))

    anki = Anki(endereco=args.endereco)
    try:
        modelo, campos_do_modelo = anki.detectar_modelo_de_oclusao()
        anki.garantir_deck(plano.deck)

        # Nome estável e único, para o media não colidir entre aulas.
        prefixo = slugificar(plano.aula or plano.titulo or "oclusao")
        nome_midia = f"ocluir-{prefixo}-{slugificar(imagem.stem)}{imagem.suffix}"
        nome_guardado = anki.guardar_midia(imagem, nome_midia)

        campos = montar_campos(
            campos_do_modelo,
            occlusion=campo_occlusion,
            html_da_imagem=f'<img src="{nome_guardado}">',
            cabecalho=plano.titulo,
            verso_extra=plano.verso_extra,
            comentarios=plano.comentarios,
        )

        id_nota = anki.adicionar_nota(
            deck=plano.deck,
            modelo=modelo,
            campos=campos,
            tags=plano.tags(),
            permitir_duplicata=args.forcar,
        )
    except (AnkiIndisponivel, AnkiErro) as e:
        return _erro(str(e))

    print(f"\nNota criada: {id_nota}")
    print(f"  notetype: {modelo}")
    print(f"  deck:     {plano.deck}")
    print(f"  tags:     {' '.join(plano.tags())}")
    print(f"  cartões:  {contar_cartoes(campo_occlusion)}")
    print(f"  mídia:    {nome_guardado}\n")
    return 0


# --------------------------------------------------------------------------
# pdf
# --------------------------------------------------------------------------


def comando_pdf(args) -> int:
    try:
        import pypdfium2
    except ImportError:
        return _erro(
            "Este comando precisa do pypdfium2:  pip install pypdfium2"
        )

    origem = Path(args.arquivo)
    if not origem.exists():
        return _erro(f"PDF não encontrado: {origem}")

    destino = Path(args.saida) if args.saida else origem.parent / f"{origem.stem}-paginas"
    destino.mkdir(parents=True, exist_ok=True)

    documento = pypdfium2.PdfDocument(str(origem))
    total = len(documento)

    if args.paginas:
        indices = _interpretar_intervalo(args.paginas, total)
        if indices is None:
            return _erro(f"Intervalo inválido: {args.paginas!r}. Use algo como 3 ou 2-7.")
    else:
        indices = range(total)

    escritos = []
    for indice in indices:
        pagina = documento[indice]
        # 200 dpi: legível pelo OCR sem gerar arquivo gigante.
        imagem = pagina.render(scale=200 / 72).to_pil()
        caminho = destino / f"{origem.stem}-p{indice + 1:03d}.png"
        imagem.save(caminho)
        escritos.append(caminho)

    print(f"\n{len(escritos)} páginas em {destino}:")
    for caminho in escritos:
        print(f"  {caminho.name}")
    print()
    return 0


def _interpretar_intervalo(texto: str, total: int) -> range | list[int] | None:
    texto = texto.strip()
    try:
        if "-" in texto:
            inicio, fim = texto.split("-", 1)
            a, b = int(inicio), int(fim)
        else:
            a = b = int(texto)
    except ValueError:
        return None
    if a < 1 or b < a or b > total:
        return None
    return range(a - 1, b)


# --------------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ocluir",
        description=(
            "Cartões de oclusão de imagem para o Anki, com a geometria vindo do "
            "OCR e a decisão continuando sua."
        ),
    )
    parser.add_argument("--version", action="version", version=f"ocluir {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ler = sub.add_parser("ler", help="lê a imagem e monta o plano com os candidatos")
    p_ler.add_argument("imagem")
    p_ler.add_argument("-o", "--saida", help="caminho do plano (padrão: <imagem>.plano.json)")
    p_ler.add_argument("--idioma", default="por", help="idioma do OCR (padrão: por)")
    p_ler.add_argument("--confianca", type=float, default=40.0)
    p_ler.add_argument("--palavra", action="store_true", help="um token por palavra")
    p_ler.add_argument(
        "--vao",
        type=float,
        default=1.2,
        help="vão máximo entre palavras da mesma linha, em alturas de texto "
        "(menor = separa mais rótulos vizinhos)",
    )
    p_ler.add_argument(
        "--rapido",
        action="store_true",
        help="uma passagem de OCR em vez de quatro: mais rápido, recall menor",
    )
    p_ler.add_argument("--titulo", help="cabeçalho do cartão")
    p_ler.add_argument("--deck", default="Medicina::Anatomia")
    p_ler.add_argument("--modo", choices=MODOS, default=ESCONDER_TUDO)
    p_ler.add_argument("--pergunta", help="slug da pergunta lógica que originou")
    p_ler.add_argument("--disciplina")
    p_ler.add_argument("--aula", help="data da aula, AAAA-MM-DD")
    p_ler.set_defaults(funcao=comando_ler)

    p_previa = sub.add_parser("previa", help="desenha as máscaras para conferir")
    p_previa.add_argument("plano")
    p_previa.add_argument("-o", "--saida")
    p_previa.set_defaults(funcao=comando_previa)

    p_verificar = sub.add_parser("verificar", help="só aplica o contrato do cartão")
    p_verificar.add_argument("plano")
    p_verificar.set_defaults(funcao=comando_verificar)

    p_enviar = sub.add_parser("enviar", help="cria a nota no Anki")
    p_enviar.add_argument("plano")
    p_enviar.add_argument("--endereco", default="http://127.0.0.1:8765")
    p_enviar.add_argument("--forcar", action="store_true", help="ignora erros de contrato")
    p_enviar.set_defaults(funcao=comando_enviar)

    p_pdf = sub.add_parser("pdf", help="extrai páginas de um PDF como imagem")
    p_pdf.add_argument("arquivo")
    p_pdf.add_argument("-o", "--saida")
    p_pdf.add_argument("--paginas", help="ex.: 4 ou 2-9")
    p_pdf.set_defaults(funcao=comando_pdf)

    return parser


def principal(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    return args.funcao(args)
