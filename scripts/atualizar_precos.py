"""Substitui o conteudo do canal de precos por embeds organizados."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv


CHANNEL_ID = "1474869322139566167"
API_BASE = "https://discord.com/api/v10"


def api_request(method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bot {os.environ['DISCORD_TOKEN']}",
        "User-Agent": "DiscordBot (price-channel-maintenance, 1.0)",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    for _ in range(5):
        request = urllib.request.Request(
            API_BASE + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            retry = json.loads(exc.read()).get("retry_after", 1)
            time.sleep(float(retry) + 0.1)
    raise RuntimeError("Limite de requisicoes persistiu apos cinco tentativas")


def lines(items: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"**{name}**\n{detail}" for name, detail in items)


def embed(title: str, color: int, items: list[tuple[str, str]], note: str | None = None):
    result = {
        "title": title,
        "description": lines(items),
        "color": color,
        "footer": {"text": "Tabela oficial de precos"},
    }
    if note:
        result["fields"] = [{"name": "Observacao", "value": note, "inline": False}]
    return result


EMBEDS = [
    embed(
        "ITENS | Taxa de 30%",
        0x4F8C9D,
        [
            ("Drogas", "R$ 60 a R$ 150"),
            ("Camisa de For\u00e7a", "R$ 6.000 a R$ 6.500"),
            ("Placa Clonada", "R$ 5.000 a R$ 5.500"),
            ("Ticket Corrida", "R$ 1.000 a R$ 1.200"),
            ("Bloqueador de Sinal", "R$ 7.500 a R$ 8.000"),
            ("Masterpick", "R$ 2.000 a R$ 2.500"),
            ("Sabonete", "R$ 1.500 a R$ 2.500"),
            ("Adrenalina", "R$ 2.500 a R$ 3.000"),
            ("C4", "R$ 1.200 a R$ 2.000"),
            ("Capuz", "R$ 1.500 a R$ 2.000"),
            ("Colete", "R$ 4.500 a R$ 5.000"),
            ("Algema", "R$ 5.000 a R$ 5.500"),
            ("Nitro", "R$ 10.000 a R$ 12.000"),
            ("Chimas", "R$ 1.000 a R$ 1.500"),
            ("Vaselina", "R$ 3.000 a R$ 3.500"),
            ("Pager", "R$ 12.000"),
            ("Tesoura", "R$ 1.500 a R$ 3.000"),
        ],
    ),
    embed(
        "ITENS | Taxa de 20%",
        0x76A5AF,
        [
            ("Drogas", "R$ 120 a R$ 150"),
            ("Masterpick", "R$ 2.000 a R$ 2.500"),
            ("C4", "R$ 1.200 a R$ 2.000"),
            ("Colete", "R$ 4.500 a R$ 5.000"),
        ],
    ),
    embed(
        "MUNI\u00c7\u00d5ES | Taxa de 35%",
        0xF5B041,
        [
            ("5mm", "R$ 100 a R$ 120 por unidade"),
            ("9mm", "R$ 125 a R$ 150 por unidade"),
            ("762mm", "R$ 200 a R$ 250 por unidade"),
            ("12cbc", "R$ 200 a R$ 250 por unidade"),
        ],
    ),
    embed(
        "ATTACHS | Taxa de 30%",
        0xFF6D00,
        [
            ("Clip Extendido", "R$ 3.000 a R$ 4.000"),
            ("Supressor", "R$ 3.000 a R$ 4.000"),
            ("Compensador", "R$ 3.000 a R$ 4.000"),
            ("Lanterna Acopl\u00e1vel", "R$ 3.000 a R$ 4.000"),
            ("Mira Avan\u00e7ada", "R$ 3.000 a R$ 4.000"),
            ("Grip Avan\u00e7ado", "R$ 3.000 a R$ 4.000"),
            ("Valor do kit", "R$ 15.000 a R$ 24.000"),
        ],
    ),
    embed(
        "ARMAS 1 | Taxa de 45%",
        0xD65C5C,
        [
            ("Pistola Colt .45", "R$ 25.000 a R$ 35.000"),
            ("Pistola M1911", "R$ 35.000 a R$ 45.000"),
            ("Sub Skorpion VZ61", "R$ 50.000"),
            ("Sub Uzi", "R$ 50.000"),
            ("Sub M-Tar 21", "R$ 70.000"),
            ("Fuzil AK-103", "R$ 110.000"),
            ("Fuzil G36C", "R$ 140.000"),
            ("Escopeta Remington", "R$ 100.000"),
        ],
        "Limite semanal: 10 de cada categoria.",
    ),
    embed(
        "ARMAS ADICIONAIS | Taxa de 30%",
        0x666666,
        [
            ("Carabina (IA2)", "R$ 130.000"),
            ("SPAS-12", "R$ 120.000"),
        ],
    ),
    embed(
        "ARMAS 2 | Taxa de 45%",
        0x2ECC71,
        [
            ("Pistola Five-Seven", "R$ 30.000 a R$ 40.000"),
            ("Pistola D-Eagle", "R$ 35.000 a R$ 45.000"),
            ("Pistola AP", "R$ 50.000"),
            ("Sub Thompson", "R$ 50.000"),
            ("Sub Tec-9", "R$ 50.000"),
            ("Sub M-Tar X", "R$ 70.000"),
            ("Fuzil AK-47", "R$ 110.000"),
            ("Fuzil AUG", "R$ 130.000"),
            ("Escopeta Remington", "R$ 100.000"),
        ],
    ),
    embed(
        "PRESET SUBS / PISTOLAS 1",
        0x3498DB,
        [
            ("Pistola Five-Seven", "R$ 30.000 a R$ 40.000"),
            ("Pistola M1911", "R$ 35.000 a R$ 45.000"),
            ("Sub Skorpion VZ61", "R$ 50.000"),
            ("Sub Tec-9", "R$ 50.000"),
        ],
    ),
    embed(
        "ITENS ADICIONAIS",
        0xF9E79F,
        [
            ("Pistola AP", "R$ 50.000"),
            ("FN Fal (Taxa 30%)", "R$ 160.000"),
        ],
    ),
    embed(
        "OUTROS",
        0xE67E22,
        [
            ("FN Fal (Taxa 30%)", "R$ 160.000"),
            ("Arco", "R$ 50.000"),
            ("Flecha", "R$ 250"),
            ("M16 (Taxa 30%)", "R$ 145.000"),
            ("SPAS-12 (Taxa 30%)", "R$ 120.000"),
        ],
    ),
    embed(
        "FLIPPERS | Taxa de 50%",
        0xF1C40F,
        [
            ("Flipper MK5", "R$ 100.000 | Limite: 2 por grupo\nUso: Central e Paleto"),
            ("Flipper MK4", "R$ 80.000 | Limite: 2 por grupo\nUso: Conce e Merryweather"),
            ("Flipper MK3", "R$ 70.000 | Limite: 2 por grupo\nUso: Joalheria e Mergulhador"),
            ("Chave Platina", "R$ 40.000 | Limite: 3 por grupo\nUso: A\u00e7ougue, Biblioteca e Galinheiro"),
            ("Chave Gold (Ouro)", "R$ 35.000 | Limite: 2 por grupo\nUso: Fleeca"),
            ("Flipper MK2", "R$ 30.000 | Sem limite informado\nUso: Ammu-Nation e Loja Depto"),
            ("Flipper MK1", "R$ 20.000 | Sem limite informado\nUso: Barbearia"),
        ],
        "Os limites indicados sao semanais.",
    ),
    embed(
        "VALORES DE RECICLAGEM",
        0xE74C3C,
        [
            ("Pistolas", "R$ 10.000"),
            ("Subs", "R$ 20.000"),
            ("M-Tar", "R$ 30.000"),
            ("Fuzil", "R$ 40.000"),
        ],
    ),
    embed(
        "ARMAS BRANCAS",
        0x95A5A6,
        [
            ("Katana", "R$ 5.000"),
            ("P\u00e3o (Arma Branca)", "R$ 3.000"),
            ("Canivete", "R$ 4.000"),
            ("Picareta", "R$ 3.000"),
            ("Placa (Arma Branca)", "R$ 3.000"),
            ("Kit de Desmanche", "R$ 2.000"),
            ("Tablet Corrida", "R$ 10.000"),
        ],
    ),
]


def main() -> None:
    load_dotenv()
    old_messages = api_request("GET", f"/channels/{CHANNEL_ID}/messages?limit=100")
    old_ids = [message["id"] for message in old_messages]

    created_ids = []
    try:
        for item in EMBEDS:
            message = api_request("POST", f"/channels/{CHANNEL_ID}/messages", {"embeds": [item]})
            created_ids.append(message["id"])
    except Exception:
        for message_id in created_ids:
            api_request("DELETE", f"/channels/{CHANNEL_ID}/messages/{message_id}")
        raise

    for message_id in old_ids:
        api_request("DELETE", f"/channels/{CHANNEL_ID}/messages/{message_id}")

    current = api_request("GET", f"/channels/{CHANNEL_ID}/messages?limit=100")
    current_ids = {message["id"] for message in current}
    if set(created_ids) != current_ids:
        raise RuntimeError("A verificacao final encontrou mensagens inesperadas no canal")

    print(json.dumps({"removidas": len(old_ids), "publicadas": len(created_ids)}))


if __name__ == "__main__":
    main()
