"""
Content negotiation on the public redirect path (ROADMAP 8.x, Shlink parity): a link that can't be
followed answers a person's browser with a page, and everything else with the JSON it always had.
"""

PAGE = ("text/html", "application/xhtml+xml")
JSON = ("application/json", "application/*", "*/*")


def prefers_html(accept: str | None) -> bool:
    """
    Whether an Accept header asks for a page: it names text/html (or XHTML) with a higher quality
    than application/json gets, by name or by a wildcard. A browser sends text/html at 1 and
    `*/*` at 0.8. A wildcard alone (curl, fetch), JSON, no header or a tie: no.
    """
    page = json = 0.0
    for part in (accept or "").split(","):
        media, *params = (piece.strip() for piece in part.split(";"))
        quality = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = min(max(float(value), 0.0), 1.0)
                except ValueError:
                    quality = 0.0
        media = media.lower()
        if media in PAGE:
            page = max(page, quality)
        elif media in JSON:
            json = max(json, quality)
    return page > json
