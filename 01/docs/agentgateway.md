# Gateway a Unsloth

agentgateway spojuje oba MCP servery a směruje LLM požadavky do samostatně běžícího Unsloth.
Compose používá obraz **v1.7.0** připnutý digestem. Konfigurace
[`config/agentgateway.yaml`](../config/agentgateway.yaml) je připojená pouze pro čtení.

## Rozhraní a porty

| Adresa při výchozím nastavení | Účel |
| --- | --- |
| `http://localhost:3000/mcp` | Společné MCP rozhraní pro hledání |
| `http://localhost:3001/v1/chat/completions` | LLM API kompatibilní s OpenAI Chat Completions |
| `http://localhost:3001/v1/models` | Seznam nakonfigurovaných modelů, nikoli kontrola jejich dostupnosti |
| `http://localhost:3002/ui/` | Diagnostické UI pouze pro čtení |
| `http://bazos-mcp:8001/mcp` | Bazoš, dostupný jen uvnitř Compose |
| `http://sbazar-mcp:8002/mcp` | Sbazar, dostupný jen uvnitř Compose |

Publikované porty jsou vázané na `127.0.0.1`. Hostitelské porty lze změnit pomocí
`GATEWAY_MCP_PORT`, `GATEWAY_LLM_PORT` a `GATEWAY_UI_PORT`; vnitřní porty zůstávají stejné.
Webový agent v Compose používá `http://agentgateway:3000/mcp` a `http://agentgateway:3001/v1`.

Oba zdroje používají stateless Streamable HTTP. Gateway přidává prefixy, takže nástroje
jsou dostupné jako `bazos_search_listings` a `sbazar_search_listings`.
Při výpadku jednoho zdroje může druhý dál fungovat (`failureMode: failOpen`).
Compose při prvním startu gateway čeká na oba MCP servery; při jejich obnovení restartuje
závislou gateway, aby obnovila spojení.

## Připojení modelu

První nastavení a spuštění popisuje [README](../README.md#spuštění).
`UNSLOTH_BASE_URL` musí obsahovat skutečný port a API prefix, obvykle `/v1`.
`UNSLOTH_MODEL` musí přesně odpovídat ID načteného modelu z Unsloth API `/v1/models`.
Volitelný `UNSLOTH_API_KEY`
zůstává v lokálním `.env`; gateway ho použije pro přístup k Unsloth API.
Časový limit určuje `LLM_TIMEOUT` v sekundách.

Unsloth běží na hostiteli. V Docker Desktop se k němu gateway připojuje přes
`host.docker.internal`; `localhost` uvnitř kontejneru označuje kontejner samotný.
Pokud API funguje z hostitele, ale ne z Dockeru, zkontrolujte naslouchací adresu Unsloth,
port a firewall. Při zpřístupnění API mimo loopback použijte autentizaci a omezte přístup.
Projekt Unsloth ani model neinstaluje, nenačítá a nespouští.

Gateway předává zadané ID modelu beze změny; jiná ID odmítá. Cloudový náhradní model
není nakonfigurovaný. Historické nastavení `LLM_MODEL` se pro volbu modelu nepoužívá.

Po změně `.env` ze složky `01/` znovu vytvořte kontejnery; samotný restart nové proměnné nepřevezme:

```bash
docker compose up -d --force-recreate app agentgateway
```

## Diagnostika

Ze složky `01/`:

```bash
docker compose ps
docker compose logs --tail 50 app agentgateway bazos-mcp sbazar-mcp
docker compose run --rm --no-deps agentgateway --file /etc/agentgateway/config.yaml --validate-only
```

| Problém | Co zkontrolovat |
| --- | --- |
| Chybí nástroj nebo gateway čeká při startu | Stav a logy obou MCP služeb |
| HTTP 401 z LLM | `UNSLOTH_API_KEY` a znovuvytvoření gateway |
| HTTP 404 z LLM | Přesné ID načteného modelu a správný API prefix v URL |
| HTTP 503/504 nebo timeout | Dostupnost Unsloth z Dockeru, odezvu modelu a `LLM_TIMEOUT` |
| Obsazený port | Příslušnou proměnnou `GATEWAY_*_PORT` nebo `APP_PORT`; ve VS Code i URL v launch profilu |
| Inzeráty chybí a odpověď obsahuje varování | Chybu nebo vypnutí zdroje; podrobnosti v dokumentaci daného MCP serveru |

Healthcheck gateway ověřuje konfiguraci, MCP healthcheck zjištění nástrojů a app healthcheck
načtení stránky Gradio. Žádný z nich nepotvrzuje dostupnost živých nabídek ani schopnost modelu
používat nástroje. Skutečný provoz ověřují [integrační a živé testy](development.md#testy-s-dockerem-a-živými-službami).
