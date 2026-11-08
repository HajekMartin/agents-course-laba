# Marketplace AI Agent

Python agent pro hledání inzerátů na **Bazoši a Sbazaru** přes webový chat.
Používá `smolagents.ToolCallingAgent`, standardní GradioUI a lokální LLM v Unsloth Studio.
Model vybere nástroj, Python ho zavolá přes MCP a vrátí výsledek modelu k vytvoření odpovědi.
Spojení k modelu i oběma bazarům zprostředkovává agentgateway.

## Zadání úkolu

> 📍 Napiš Python skript, který zavolá LLM API, použije nástroj (např. výpočetní funkci) a vrátí odpověď zpět LLM.
>
> 📄 Formát: Vypracovaný úkol odevzdejte ve formě zdrojového kódu. Projekt ideálně nahrajte na Github a odevzdejte link na Github repositáře.
>
> 📅 Deadline úkolu máš do 23. 11. 2026 23:59
>
> 📍 Maximální počet bodů, které můžeš získat je 100 bodů.

## Co řešení umí

- Hledat na obou bazarech nebo jen na zvoleném zdroji podle přirozeného zadání.
- Filtrovat cenu v Kč, PSČ a okruh; spojit výsledky, odstranit duplicitní URL,
  seřadit je a omezit jejich počet. Vrací názvy, ceny, lokality a odkazy na původní inzeráty.
- Dohledat PSČ města na webu. Při nejednoznačném výsledku požádá o upřesnění.
- Navazovat na předchozí dotazy v omezené paměti konverzace a zobrazit kroky volání nástrojů.
  **New chat** paměť vymaže.

## Omezení

- Projde standardně nejvýše 3 stránky každého zdroje (nastavitelné na 1–5).
  Řazení platí pro načtené nabídky; nezaručuje nejlevnější nabídku na celém trhu.
- Okruh předává bazaru, přesné vzdálenosti neověřuje. Sbazar používá první obec
  nabídnutou k PSČ, které může pokrývat více míst. Dohledání PSČ není ověření adresy.
- Jednoduchý filtr názvů odstraňuje zjevné příslušenství, díly a poptávky, ale může chybovat.
  Stav zboží ani pravdivost inzerátu neověřuje; čte pouze souhrny nabídek.
- Výpadek nebo blokaci zdroje hlásí jako varování, nikoli jako důkaz, že nabídky neexistují.
  Dostupnost závisí na veřejných rozhraních bazarů, která se mohou změnit.
- Jde o lokální aplikaci pro jednoho uživatele, bez nákupu, kontaktování prodejců a databáze.
  Model musí podporovat nativní `tool_calls`; projekt ho neinstaluje ani nespouští.

## Spuštění

Potřebujete **Docker Desktop** a samostatně spuštěné **Unsloth Studio** s načteným modelem
podporujícím volání nástrojů a API dostupným z Dockeru.

Při prvním nastavení vytvořte konfiguraci (existující `.env` nepřepisujte):

```bash
cd 01
cp .env.example .env
```

V `.env` nastavte skutečný port API, přesné ID načteného modelu a případný klíč:

```dotenv
UNSLOTH_BASE_URL=http://host.docker.internal:8888/v1
UNSLOTH_MODEL=your-loaded-model-id
UNSLOTH_API_KEY=
```

Port `8888` je příklad. Potom ze složky `01/` spusťte:

```bash
docker compose up -d --build --wait
```

Chat otevřete na **http://localhost:8080**. Logy zobrazíte přes `docker compose logs -f app`,
aplikaci zastavíte přes `docker compose stop`. Stav `healthy` nepotvrzuje dostupnost modelu
ani živých inzerátů.

Ve VS Code lze z kořene repozitáře použít **Run and Debug → Marketplace: Start Web UI → F5**.
Profil spustí Compose a otevře Chrome; ukončení ladění zastaví služby projektu.

## Ukázka použití

1. `Najdi iPhone 15 do 12000 Kč. Prohledej oba bazary a seřaď od nejlevnějších.`
2. `A teď jen Bazoš v okolí PSČ 46001 do 30 km, nejvýše 5 výsledků.`
3. V novém chatu: `Najdi MacBook Air M2 do 18000 Kč do 30 km od Liberce 1. PSČ dohledej.`

## Testy a technické podrobnosti

Běžné testy používají simulovaný model a testovací data. Ze složky `01/` je spustíte
pomocí `uv run --locked pytest` (vyžaduje Python 3.12+ a uv). Ověření s reálným modelem
je samostatný volitelný test; běžné testy jeho kompatibilitu nepotvrzují.

- [Vývoj a testy](docs/development.md) – lokální běh, kontroly a testy živých služeb.
- [Architektura](docs/architecture.md) – tok dat a společný kontrakt MCP nástrojů.
- [Agent](docs/agent.md) – volání nástrojů, paměť a limity.
- [Gateway a Unsloth](docs/agentgateway.md) – propojení, porty a řešení chyb.
- [Bazoš MCP](docs/bazos-mcp.md) a [Sbazar MCP](docs/sbazar-mcp.md) – chování jednotlivých zdrojů.
