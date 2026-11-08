"""Conservative title checks before price sorting; no inferred price floors or AI ranking."""

import re
import unicodedata

ACCESSORIES = re.compile(
    r"\b(?:kryt\w*|pouzdr\w*|obal\w*|foli\w*|nabijeck\w*|adapter\w*|"
    r"stojan\w*|drzak\w*|krabic\w*|ramecek\w*|case\w*|cover\w*|charger\w*|"
    r"(?:ochrann\w*|tvrzen\w*|privacy)\s+(?:\w+\s+){0,2}skl\w*|nahradni\s+dil\w*)\b"
)
PARTS = re.compile(r"\b(?:lcd|displej\w*|baterie|zakladni\s+deska|dotykov\w*\s+skl\w*)\b")
TRADE = re.compile(r"^(?:vymen\w*|koupim|shanim|poptav\w*|hledam|wanted)\b")
BUNDLE = re.compile(r"(?:\b(?:s|se|vc|vcetne|plus|with|and|a)|[+&])(?:\s+\w+){0,2}\s*$")
DAMAGE = re.compile(r"\b(?:praskl\w*|poskozen\w*|rozbit\w*|nefunkcn\w*)\b")


def normalized(value: str) -> str:
    value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    value = re.sub(r"\bplaystation", "ps", value)
    value = re.sub(r"([0-9]+)\s*(gb|tb)\b", r"\1 \2", value)
    return re.sub(r"(?<=[a-z])(?=[0-9])", " ", value)


def matches_product(title: str, query: str) -> bool:
    """Reject obvious accessories/trades unless sought; preserve whole-product bundles."""
    title, query = normalized(title), normalized(query)
    if TRADE.search(title) and not TRADE.search(query):
        return False
    if not ACCESSORIES.search(query) and not PARTS.search(query):
        for marker in ACCESSORIES.finditer(title):
            if not BUNDLE.search(title[: marker.start()]):
                return False
        # 'iPhone with a broken display' is still a phone; 'LCD display for iPhone' is not.
        root = next(iter(re.findall(r"[a-z]+", query)), "")
        product = re.search(r"\b" + re.escape(root) + r"\b", title) if root else None
        for marker in PARTS.finditer(title):
            if product and marker.start() < product.start():
                return False
            battery_condition = marker.group() == "baterie" and re.match(
                r"\s*[0-9]{1,3}\s*%", title[marker.end() :]
            )
            if (
                not BUNDLE.search(title[: marker.start()])
                and not DAMAGE.search(title[: marker.start()])
                and not battery_condition
            ):
                return False
    tokens = set(re.findall(r"[a-z0-9]+", query))
    if any(token.isdigit() for token in tokens):
        title_tokens = set(re.findall(r"[a-z0-9]+", title))
        return all(
            any(
                word == token or (token.isalpha() and len(token) >= 3 and word.startswith(token))
                for word in title_tokens
            )
            for token in tokens
        )
    return True
