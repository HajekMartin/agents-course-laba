# Sbazar MCP

FastMCP server nabízí jeden nástroj `search_listings` na interní adrese
`http://sbazar-mcp:8002/mcp` (stateless Streamable HTTP). Agent k němu přistupuje přes gateway
jako `sbazar_search_listings`. Vstupy a výstupy popisuje [společný MCP kontrakt](architecture.md#společný-mcp-kontrakt).

## Hledání a omezení

Adaptér používá JSON rozhraní veřejné webové aplikace `https://www.sbazar.cz`:

- `/api/v1/items/search`: `phrase`, `price_from`, `price_to`, `limit=60` a stránkování `offset`.
- `/api/v2/localities/suggest`: dohledání obce k PSČ pomocí `query` a `include_zip=1`.
- Pro polohu předává `locality=municipality,<id>` a `radius_precision`.

PSČ převádí na první platnou obec z našeptávače zdroje. Odpověď uvádí zvolenou obec
s varováním: jedno PSČ může zahrnovat více míst a přesné vzdálenosti se neověřují.
Při selhání převodu nepřejde na celostátní hledání.

Načítá nejvýše `max_pages` stránek po 60 souhrnech a respektuje `pagination.total`.
Detailní stránky nečte. Cenu „dohodou“ nepovažuje za nulu; chybějící údaje zůstávají `null`.
Společná pravidla filtrování a neúplného pokrytí jsou v [architektuře](architecture.md#zpracování-výsledků).

Nejde o garantované rozhraní pro cizí aplikace; formát se může změnit.
Živé hledání je ve výchozím stavu zapnuté; `SBAZAR_ACCESS_PERMITTED=false` ho vypne.
HTTP chyby, omezení přístupu a neplatné odpovědi vrací jako varování. Blokace neobchází
ani požadavky neopakuje. Při selhání další stránky zachová dříve načtené nabídky.

## Implementace, testy a původ

Kód je v `providers/sbazar.py` a `mcp/sbazar_server.py` pod `src/marketplace_agent/`.
Samostatný server lze spustit přes `python -m marketplace_agent.mcp.sbazar_server`.
Postup a příkazy testů jsou v [dokumentaci vývoje](development.md).

Normalizace JSON vychází z projektu [basta/sbazar-mcp](https://github.com/basta/sbazar-mcp).
Jeho [licenční text MIT](licenses/sbazar-mcp-MIT.txt) je zachovaný v původním znění.
