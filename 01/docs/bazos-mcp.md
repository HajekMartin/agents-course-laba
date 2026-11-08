# Bazoš MCP

FastMCP server nabízí jeden nástroj `search_listings` na interní adrese
`http://bazos-mcp:8001/mcp` (stateless Streamable HTTP). Agent k němu přistupuje přes gateway
jako `bazos_search_listings`. Vstupy a výstupy popisuje [společný MCP kontrakt](architecture.md#společný-mcp-kontrakt).

## Hledání a omezení

Adaptér čte souhrny inzerátů ze všech kategorií přes `https://www.bazos.cz/search.php`.
Používá parametry veřejného formuláře: `hledat`, `rubriky=www`, `cenaod`, `cenado`,
`hlokalita`, `humkreis` a `kitx=ano`. Další stránky prochází podle skutečných odkazů `crz`
až do konce výsledků nebo limitu `max_pages`.

Kontroluje potvrzení dotazu a případného PSČ s okruhem ve vráceném formuláři.
Při chybě nepotvrzené výsledky nepoužije. Ověřuje tím předání filtru, nikoli přesnou
vzdálenost jednotlivých nabídek. Cenové řazení provádí lokálně nad načtenými výsledky.

Vrací pouze rozpoznané odkazy na inzeráty Bazoše a údaje ze souhrnu; detailní stránky
nenačítá. Ceny typu „dohodou“ zůstávají neznámé, chybějící popis je prázdný řetězec.
Společná pravidla filtrování a neúplného pokrytí jsou v [architektuře](architecture.md#zpracování-výsledků).

Živé hledání je ve výchozím stavu zapnuté; `BAZOS_ACCESS_PERMITTED=false` ho vypne.
HTTP chyby, omezení přístupu a nerozpoznané HTML vrací jako varování. Blokace neobchází
ani požadavky neopakuje. Při selhání další stránky zachová dříve načtené nabídky.

## Implementace a testy

Kód je v `providers/bazos.py` a `mcp/bazos_server.py` pod `src/marketplace_agent/`.
Samostatný server lze spustit přes `python -m marketplace_agent.mcp.bazos_server`.
Postup a příkazy testů jsou v [dokumentaci vývoje](development.md).

Původní adaptér vychází z referenčního projektu
[progresak/bazos-mcp-server](https://github.com/progresak/bazos-mcp-server).
