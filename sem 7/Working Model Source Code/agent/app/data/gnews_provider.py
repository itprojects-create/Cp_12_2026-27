"""GNews (free RSS) provider: filter published_at <= as_of, sanitize, dedupe."""
from __future__ import annotations
from datetime import datetime, timezone
from dateutil import parser as dateparser
from app.data.base import assert_pit
from app.data.sanitize import sanitize

class GNewsProvider:
    name = "gnews-rss"

    def headlines(self, query: str, as_of: datetime, max_items: int = 10) -> list[dict]:
        from gnews import GNews
        as_of_utc = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        gn = GNews(max_results=max_items * 2)
        raw = gn.get_news(query) or []
        out, seen = [], set()
        for r in raw:
            title = (r.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            try:
                pub = dateparser.parse(r.get("published date", ""))
                if pub and not pub.tzinfo:
                    pub = pub.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if not pub or pub > as_of_utc:
                continue  # PIT filter: drop future news
            try:
                assert_pit(pub, as_of_utc)
            except ValueError:
                continue
            out.append({"title": sanitize(title, 300),
                        "publisher": sanitize(str(r.get("publisher", {}).get("title", "")), 120),
                        "published_at": pub.isoformat(),
                        "url": r.get("url", "")})
            if len(out) >= max_items:
                break
        return out
