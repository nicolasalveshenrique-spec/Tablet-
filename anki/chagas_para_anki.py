#!/usr/bin/env python3
"""Envia uma fila de cartões TSV para o Anki via AnkiConnect.

Uso:
    python3 chagas_para_anki.py fila.tsv --deck "BMFF II::Farmacologia"
    python3 chagas_para_anki.py fila.tsv --deck "..." --dry-run

Requisitos:
    - Anki aberto no computador
    - add-on AnkiConnect instalado (código 2055492159)
    - nada mais: só biblioteca padrão do Python

Formato da fila (TSV, uma linha por cartão, 3 colunas separadas por TAB):

    frente <TAB> verso <TAB> tag1 tag2

Linhas em branco e linhas começando com '#' são ignoradas.
A aprovação é por ausência: você apaga as linhas que não quer antes de rodar.
Depois do envio bem-sucedido o arquivo é movido para enviados/.
"""

import argparse
import json
import pathlib
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime

ANKI_URL = "http://127.0.0.1:8765"

# Anki em português usa "Básico" com campos "Frente"/"Verso";
# em inglês, "Basic" com "Front"/"Back". Detectamos qual existe.
MODELOS_ACEITOS = ("Básico", "Basic")


def invoke(action, **params):
    payload = json.dumps({"action": action, "version": 6, "params": params}).encode("utf-8")
    req = urllib.request.Request(ANKI_URL, payload, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resposta = json.load(r)
    except urllib.error.URLError as e:
        sys.exit(
            f"Não consegui falar com o Anki em {ANKI_URL} ({e.reason}).\n"
            "Abra o Anki no computador e confirme que o add-on AnkiConnect está instalado."
        )
    if resposta.get("error"):
        sys.exit(f"AnkiConnect recusou '{action}': {resposta['error']}")
    return resposta["result"]


def escolher_modelo():
    disponiveis = invoke("modelNames")
    for nome in MODELOS_ACEITOS:
        if nome in disponiveis:
            campos = invoke("modelFieldNames", modelName=nome)
            if len(campos) < 2:
                sys.exit(f"O tipo de nota '{nome}' tem menos de dois campos.")
            return nome, campos[0], campos[1]
    sys.exit(
        "Não achei nem 'Básico' nem 'Basic' entre os tipos de nota do seu Anki.\n"
        f"Tipos disponíveis: {', '.join(disponiveis)}"
    )


def ler_fila(caminho):
    cartoes = []
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), start=1):
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        partes = linha.split("\t")
        if len(partes) < 2:
            sys.exit(
                f"Linha {numero} não tem TAB separando frente e verso.\n"
                f"  {linha!r}\n"
                "Provável causa: o editor converteu tabulação em espaços ao colar."
            )
        frente = partes[0].strip()
        verso = partes[1].strip()
        tags = partes[2].split() if len(partes) > 2 else []
        if not frente or not verso:
            sys.exit(f"Linha {numero} tem frente ou verso vazio.")
        cartoes.append((frente, verso, tags))
    return cartoes


def main():
    ap = argparse.ArgumentParser(description="Envia cartões TSV para o Anki.")
    ap.add_argument("arquivo", type=pathlib.Path, help="arquivo .tsv com a fila")
    ap.add_argument("--deck", required=True, help='deck de destino, ex: "BMFF II::Farmacologia"')
    ap.add_argument("--dry-run", action="store_true", help="mostra o que faria e não envia")
    args = ap.parse_args()

    if not args.arquivo.is_file():
        sys.exit(f"Arquivo não encontrado: {args.arquivo}")

    cartoes = ler_fila(args.arquivo)
    if not cartoes:
        sys.exit("A fila está vazia — nada a enviar.")

    if args.dry_run:
        print(f"{len(cartoes)} cartões seriam enviados para '{args.deck}':\n")
        for frente, verso, tags in cartoes:
            print(f"  {frente}\n    → {verso}   {' '.join(tags)}\n")
        return

    modelo, campo_frente, campo_verso = escolher_modelo()
    if args.deck not in invoke("deckNames"):
        invoke("createDeck", deck=args.deck)
        print(f"Deck criado: {args.deck}")

    notas = [
        {
            "deckName": args.deck,
            "modelName": modelo,
            "fields": {campo_frente: frente, campo_verso: verso},
            "tags": tags,
            "options": {"allowDuplicate": False, "duplicateScope": "deck"},
        }
        for frente, verso, tags in cartoes
    ]

    # canAddNotes separa duplicata de erro real antes de gravar qualquer coisa.
    podem = invoke("canAddNotes", notes=notas)
    duplicatas = [c[0] for c, ok in zip(cartoes, podem) if not ok]
    novas = [n for n, ok in zip(notas, podem) if ok]

    if not novas:
        print(f"Todos os {len(cartoes)} cartões já existem no deck. Nada enviado.")
        return

    ids = invoke("addNotes", notes=novas)
    falhas = sum(1 for i in ids if i is None)
    enviados = len(ids) - falhas

    print(f"Enviados: {enviados}")
    if duplicatas:
        print(f"Ignorados por já existirem: {len(duplicatas)}")
        for frente in duplicatas:
            print(f"  - {frente}")
    if falhas:
        sys.exit(f"{falhas} cartões falharam no envio. Arquivo NÃO foi movido.")

    destino = args.arquivo.parent / "enviados"
    destino.mkdir(exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d-%H%M")
    shutil.move(str(args.arquivo), str(destino / f"{carimbo}-{args.arquivo.name}"))
    print(f"Fila movida para {destino}/{carimbo}-{args.arquivo.name}")


if __name__ == "__main__":
    main()
