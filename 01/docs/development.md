# Vývoj a testy

## VS Code a Docker

Otevřete kořen repozitáře s `01/` a `.vscode/`. Po [nastavení Unsloth a `.env`](../README.md#spuštění)
spusťte **Run and Debug → Marketplace: Start Web UI → F5**.
Profil sestaví a spustí Compose, počká na připravenost služeb a otevře Chrome na portu 8080.
Ukončení ladění spustí `docker compose stop`. Jde o ladění prohlížeče, nikoli Pythonu v kontejneru.
Při změně `APP_PORT` upravte i URL v [`.vscode/launch.json`](../../.vscode/launch.json).

Úlohy **Marketplace: Start**, **Marketplace: Stop** a **Marketplace: Tests** jsou dostupné
přes **Terminal → Run Task**. Testovací úloha vyžaduje lokální uv.
Příkazy pro běh bez VS Code jsou v [README](../README.md#spuštění), diagnostika v [popisu gateway](agentgateway.md#diagnostika).

## Lokální Python

Vyžaduje Python 3.12+, [uv](https://docs.astral.sh/uv/) a běžící gateway s oběma MCP servery
(spuštěné pomocí Compose). Unsloth zůstává samostatnou službou.

```bash
cd 01
uv sync --locked
LLM_BASE_URL=http://127.0.0.1:3001/v1 \
AGENTGATEWAY_URL=http://127.0.0.1:3000/mcp \
APP_HOST=127.0.0.1 APP_PORT=8081 uv run --locked python -m marketplace_agent
```

Stejný webový chat pak běží na http://localhost:8081. Příkazový chat není implementovaný.
Při změně publikovaných portů gateway upravte také URL v příkazech níže.

## Běžné kontroly

Všechny následující příkazy spouštějte ze složky `01/`:

```bash
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Výchozí testy nepotřebují Docker ani LLM. Používají simulovaný model, MCP výsledky a HTTP data;
ověřují skutečnou smyčku smolagents, validaci, filtry, stránkování, PSČ i webové rozhraní.
Testy externích služeb se bez příslušné proměnné přeskočí.

## Testy s Dockerem a živými službami

Integrační test gateway spustí izolované kontejnery se skutečnou gateway a MCP servery,
ale se simulovaným LLM a bazary. Ověřuje transport a kontrakty; nevolá Unsloth ani živé bazary.

```bash
GATEWAY_DOCKER_TESTS=true uv run --locked pytest tests/integration/test_agentgateway.py
```

Kompletní cyklus s reálným modelem a oběma MCP zdroji vyžaduje nakonfigurované `.env`,
běžící Compose a Unsloth. Kontroluje také navazující dotaz se zachováním cenového filtru:

```bash
AGENT_LIVE_E2E=true \
LLM_BASE_URL=http://127.0.0.1:3001/v1 AGENTGATEWAY_URL=http://127.0.0.1:3000/mcp \
uv run --locked pytest tests/integration/test_agent_live.py -s
```

Pro test dohledání PSČ a následného MCP hledání ve stejném příkazu nahraďte
`AGENT_LIVE_E2E=true` za `POSTCODE_LIVE_E2E=true`. Vyžaduje navíc webové vyhledávání.

Samostatné testy dostupnosti bazarů:

```bash
BAZOS_LIVE_SMOKE=true uv run --locked pytest tests/test_bazos.py -m live -v
SBAZAR_LIVE_SMOKE=true uv run --locked pytest tests/test_sbazar.py -m live -v
```

Samotné LLM spojení přímo i přes gateway lze ověřit bez kontroly volání nástrojů:

```bash
UNSLOTH_LIVE_SMOKE=true \
UNSLOTH_BASE_URL=http://127.0.0.1:8888/v1 LLM_BASE_URL=http://127.0.0.1:3001/v1 \
uv run --locked pytest tests/integration/test_agentgateway.py -k optional_live_unsloth
```

Port `8888` nahraďte skutečným portem Unsloth API.

Výsledky živých testů závisí na dostupnosti zdrojů a zvoleném modelu. Prázdná odpověď
s varováním značí neúplné hledání. Simulované testy nepotvrzují aktuální dostupnost inzerátů;
po změně modelu nebo jeho šablony znovu ověřte celý živý cyklus.
