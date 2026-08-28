"""FlightDataExtractor — fallback heuristic that greps the captured RSC payload.

LinkedIn embeds a large amount of profile data inside the initial HTML as an RSC
(React Server Components) flight payload — the same payload that powers the
/profileCards API. When the /details/* pages change or fail, this extractor
grep the already-captured HTML for known shapes (dates, company/school names,
skill pills) as a last-resort, low-confidence strategy.

It is deliberately conservative: it only returns data whose shape it recognises
(title + date range, school + date range, or pill text), so it never fabricates
content. If nothing recognisable is found it reports MISSING and the engine
falls through to the next strategy.
"""
from __future__ import annotations

import re
from typing import Any

from app.engine.parsing import clean
from app.engine.types import ExtractionContext, ExtractionResult, FieldSource

DATE_RANGE_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s*\d{4}\s*[-–]\s*(?:Present|\w+\s*\d{4}|[A-Za-z]+\s\d{4})"
    r"|\d{4}\s*[-–]\s*(?:\d{4}|Present)"
)
STRING_VALUE_RE = re.compile(r'"stringValue":"([^"]{1,120})"')


class FlightDataExtractor:
    """Fallback extractor. `field` is set per instance (experience/education/skills/...)."""

    source = FieldSource.FLIGHT_DATA
    base_confidence = 0.45

    def __init__(self, field: str):
        self.field = field

    def _strings(self, html: str) -> list[str]:
        return [s for s in STRING_VALUE_RE.findall(html) if len(s.strip()) > 1]

    def _titles_with_dates(self, html: str) -> list[str]:
        """Pairs of (possible title, date range) where a date is adjacent."""
        strings = self._strings(html)
        out: list[str] = []
        for s in strings:
            if DATE_RANGE_RE.search(s):
                # s itself is a date; find nearby strings that look like titles
                idx = html.find(s)
                window = html[max(0, idx - 400): idx]
                titles = STRING_VALUE_RE.findall(window)
                if titles:
                    out.append(clean(titles[-1]) or s)
        return out

    def extract(self, ctx: ExtractionContext) -> ExtractionResult:
        html = ctx.main.html
        # prefer the details page HTML if captured (contains the same payload)
        for section in ("experience", "education", "skills", "certifications", "languages"):
            cap = ctx.details.get(section) or ctx.captures.get(section)
            if cap:
                html = cap.html
                break

        value: Any = None
        valid = False

        if self.field == "experience":
            pairs = self._titles_with_dates(html)
            if pairs:
                value = [{"title": p, "company": None, "date_range": None, "location": None, "description": None} for p in pairs[:10]]
                valid = True
        elif self.field == "education":
            pairs = self._titles_with_dates(html)
            if pairs:
                value = [{"school": p, "degree": None, "date_range": None, "description": None} for p in pairs[:6]]
                valid = True
        elif self.field == "skills":
            # skill pills on details page appear as plain lines; the flight payload
            # repeats them as stringValue entries. Take short, non-date strings.
            strings = [s for s in self._strings(html) if 2 <= len(s) <= 60 and not DATE_RANGE_RE.search(s)]
            seen: list[str] = []
            for s in strings:
                if s.lower() not in {x.lower() for x in seen}:
                    seen.append(s)
            if seen:
                value = [{"name": n} for n in seen[:20]]
                valid = True

        if not valid:
            return ExtractionResult(
                field=self.field, value=None, source=self.source,
                confidence=0.0, valid=False,
                warning="flight_data_grep_found_nothing",
            )
        return ExtractionResult(
            field=self.field, value=value, source=self.source,
            confidence=self.base_confidence, valid=valid,
        )
