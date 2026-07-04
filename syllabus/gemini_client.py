"""Syllabus text to structured schedule items, via the Gemini API.

The response is constrained with a JSON schema so it always comes back as
[{title, date, confident}]. Dates are plain "YYYY-MM-DD" strings or null.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from google import genai
from google.genai import types


# default model, override with GEMINI_MODEL in .env
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiError(Exception):
    """The API call failed or returned something unusable."""


@dataclass
class ScheduleItem:
    """One extracted syllabus item, same shape the frontend gets."""

    title: str
    date: str | None  # "YYYY-MM-DD" or None if no date was found
    confident: bool

    def to_dict(self) -> dict:
        return {"title": self.title, "date": self.date, "confident": self.confident}


# the shape Gemini's response has to match, date is nullable
_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        required=["title", "date", "confident"],
        properties={
            "title": types.Schema(
                type=types.Type.STRING,
                description="Short name of the assignment, exam, or deadline.",
            ),
            "date": types.Schema(
                type=types.Type.STRING,
                nullable=True,
                description="Due date as YYYY-MM-DD, or null if not stated.",
            ),
            "confident": types.Schema(
                type=types.Type.BOOLEAN,
                description=(
                    "True only if the title AND date are clearly a real, dated "
                    "deadline. False if the date is ambiguous/inferred or the "
                    "item may not be an actual deadline."
                ),
            ),
        },
    ),
)


_SYSTEM_PROMPT = """\
You are a precise academic-schedule extractor. You are given the raw text of a
course syllabus. Extract every graded deadline or scheduled event a student
would want on their calendar: assignments, homework, projects, quizzes, exams,
presentations, readings with due dates.

Rules:
- Use the school term/year context in the syllabus to resolve dates to a full
  YYYY-MM-DD. If a line says "Week 3: Quiz 1" with no explicit date, set date to
  null rather than guessing.
- Set "confident" to false when: the date had to be inferred, the year is
  unclear, or the item might not be a real graded deadline (e.g. "Office hours",
  "Reading: Chapter 4" with no due date).
- Do NOT invent items. Do NOT include recurring lecture times or office hours as
  deadlines.
- Prefer the exact wording from the syllabus for each title, kept short.
"""


def _build_client(api_key: str | None) -> genai.Client:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise GeminiError(
            "GEMINI_API_KEY is not set. Put it in your .env file "
            "(see .env.example)."
        )
    return genai.Client(api_key=key)


def extract_items(text: str, *, api_key: str | None = None,
                  model: str = DEFAULT_MODEL) -> list[ScheduleItem]:
    """Send syllabus text to Gemini and get structured items back."""
    client = _build_client(api_key)

    try:
        response = client.models.generate_content(
            model=model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                # low temperature keeps output consistent
                temperature=0.1,
            ),
        )
    except Exception as exc:
        raise GeminiError(f"Gemini API call failed: {exc}") from exc

    # .parsed is already a list of dicts when a response_schema is set
    raw = response.parsed
    if raw is None:
        raise GeminiError("Gemini returned no parseable content.")

    items: list[ScheduleItem] = []
    for entry in raw:
        items.append(
            ScheduleItem(
                title=str(entry.get("title", "")).strip(),
                date=entry.get("date") or None,
                confident=bool(entry.get("confident", False)),
            )
        )
    return items
