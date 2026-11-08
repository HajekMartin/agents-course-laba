# Agent

`MarketplaceAgent` rozšiřuje `smolagents.ToolCallingAgent` o pravidla hledání na bazarech.
Smyčku LLM → nástroj → výsledek → LLM řídí smolagents. Rozhraní zajišťuje standardní GradioUI;
`python -m marketplace_agent` spouští webový chat.

## Pravidla volání nástrojů

- Nástroje se zjišťují přes MCP při prvním požadavku. Agent povoluje pouze
  `search_listings` ve jmenných prostorech `bazos` a `sbazar`; ověřuje jejich schémata i vstupy.
- Výchozí zadání používá oba zdroje, výslovná volba bazaru omezuje dostupné nástroje
  i v navazujících dotazech. Selhání zvoleného zdroje nevyvolá hledání na druhém.
- Každý zdroj se volá nejvýše jednou za tah. Stránkování probíhá uvnitř MCP volání
  podle `max_pages`. První platné hledání určí stejné parametry pro zbytek tahu;
  nový uživatelský dotaz je může změnit.
- Po dokončení pokusů na vybraných zdrojích zůstane dostupný jen `final_answer`.
  Model vytváří shrnutí, Python vykresluje skutečné nabídky a varování.
  Model smí vyřadit pouze URL, které byly skutečně načteny.
- Adaptér modelu přijímá nativní `tool_calls`. Chybná nebo zkrácená volání odmítá;
  textové napodobeniny volání nástroje nespouští. Agent nemá nástroj pro vykonávání Python kódu.

Filtr názvů před řazením odstraňuje zjevné příslušenství, díly, poptávky, výměny a neshodné
číselné modely, pokud je uživatel nehledá. Jde o heuristiku; celé poškozené telefony
nebo balíčky s příslušenstvím mohou zůstat. Minimální cena se neodhaduje.

## PSČ a paměť

`lookup_postcode` používá webové vyhledávání smolagents/DDGS, nejvýše 5 výsledků a timeout 10 s.
Vyhledává název místa a PSČ, nikoli celou konverzaci. Jednoznačně nalezené PSČ se zdrojovým
odkazem lze předat bazaru; při chybě nebo více kandidátech má agent požádat o upřesnění.
Do MCP lze použít jen PSČ výslovně dodané uživatelem nebo podložené tímto nástrojem.
Odkaz na zdroj dohledaného PSČ se připojí k výsledku; nejde o úřední ověření adresy.

Paměť konverzace je omezená počtem tahů a velikostí kontextu. Agent si ponechá nejvýše
32 dohledaných PSČ. **New chat** vymaže paměť i PSČ. Jedna instance slouží jedné lokální
konverzaci; oddělené relace pro více uživatelů nejsou implementované.

## Moduly

| Soubor v `src/marketplace_agent/` | Úloha |
| --- | --- |
| `web.py`, `__main__.py` | Spuštění GradioUI a reset konverzace |
| `agent.py` | Agent a obálky nástrojů hledání a finální odpovědi |
| `agent_tools.py` | Zjištění MCP nástrojů, validace a volání přes gateway |
| `llm.py` | Klient modelu a kontrola nativních volání |
| `results.py`, `providers/common.py`, `providers/matching.py` | Spojení, filtry a výpis výsledků |
| `postcodes.py` | Dohledání PSČ se zdrojovým odkazem |
| `config.py`, `domain/models.py` | Nastavení a společné datové modely |
| `gateway_check.py` | Pomocné kontroly protokolů pro integrační testy |

## Konfigurace

Úplná šablona je v [`.env.example`](../.env.example). Proměnné prostředí mají přednost
před `.env` v pracovním adresáři a výchozími hodnotami.

| Proměnná | Výchozí hodnota | Význam |
| --- | --- | --- |
| `AGENT_MAX_ITERATIONS` | 20 | Maximum kroků včetně finální odpovědi a oprav chybných volání |
| `AGENT_MAX_TOOL_CALLS` | 8 | Maximum volání v jedné odpovědi modelu |
| `AGENT_MAX_TOKENS` | 4096 | Limit generované odpovědi modelu |
| `AGENT_HISTORY_TURNS` | 6 | Limit uchovaných tahů konverzace |
| `AGENT_HISTORY_CHARS` | 64000 | Limit uchovaného kontextu ve znacích |
| `AGENT_MAX_MESSAGE_CHARS` | 4000 | Maximum znaků uživatelské zprávy |
| `LLM_TIMEOUT`, `MCP_TIMEOUT` | 120 s, 30 s | Timeout modelu a jednotlivého MCP požadavku |

Kompatibilitu konkrétního modelu a jeho šablony ověřuje [volitelný živý test](development.md#testy-s-dockerem-a-živými-službami).
Samotná úspěšná textová odpověď z API nepotvrzuje podporu volání nástrojů.
