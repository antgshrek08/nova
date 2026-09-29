"""Universal Syllabus Parser for N.O.V.A.
Extracts course metadata, grading policies, and schedule/deadlines
from uploaded syllabus PDFs, documents, or raw text.
Populates courses and assignments directly into N.O.V.A.'s Universal Academic Hub.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime
from typing import Any

from . import db, providers

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extracts raw text from a PDF file using pypdf."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages_text = []
    for page in reader.pages:
        txt = page.extract_text()
        if txt:
            pages_text.append(txt)
    return "\n\n".join(pages_text)


_PARSE_PROMPT = """You are an expert academic assistant parsing a university or high school course syllabus.
Analyze the following syllabus text and extract structured JSON with the following schema:

{
  "course_code": "e.g. MAC 2311 or CS 101",
  "course_name": "e.g. Calculus I with Analytic Geometry",
  "instructor": "Professor or teacher name",
  "instructor_email": "email if found",
  "office_hours": "office hours if listed",
  "schedule": "e.g. MWF 10:00 AM - 10:50 AM",
  "grade_breakdown": [
    {"category": "Homework", "weight_percent": 20},
    {"category": "Exams", "weight_percent": 50},
    {"category": "Final Project", "weight_percent": 30}
  ],
  "assignments": [
    {
      "title": "Assignment or Exam Name",
      "due_date": "YYYY-MM-DD or e.g. Week 4 / Oct 12 if year unspecified",
      "points": 100,
      "type": "homework | quiz | exam | project | reading"
    }
  ]
}

Return ONLY valid JSON matching this schema, no markdown code fences, no extra commentary.
Syllabus text:
"""


async def parse_syllabus_text(text: str) -> dict[str, Any]:
    """Uses LLM (or regex fallback) to extract structured course and assignment data."""
    if not text.strip():
        return {
            "course_code": "Course",
            "course_name": "New Course",
            "instructor": "",
            "assignments": [],
        }

    # Truncate if gigantic to avoid token limits
    sample = text[:25000]

    try:
        # Prompt LLM through providers
        prompt = _PARSE_PROMPT + sample
        messages = [{"role": "user", "content": prompt}]
        # Use quick or default model
        resp_text = ""
        async for chunk in providers.stream_category("quick", messages):
            if chunk.get("type") == "delta":
                resp_text += chunk.get("text", "")
            elif chunk.get("type") == "full":
                resp_text = chunk.get("text", "")

        # Clean JSON fences if model outputted them
        cleaned_json = re.sub(r"^```json\s*", "", resp_text.strip(), flags=re.MULTILINE)
        cleaned_json = re.sub(r"^```\s*", "", cleaned_json, flags=re.MULTILINE)
        cleaned_json = cleaned_json.strip()

        data = json.loads(cleaned_json)
        return data
    except Exception as exc:
        logger.warning("LLM syllabus parsing failed (%s), using regex fallback", exc)
        return _regex_fallback_parse(text)


def _regex_fallback_parse(text: str) -> dict[str, Any]:
    """Lightweight regex extractor when no LLM is configured."""
    code_match = re.search(r"\b([A-Z]{2,4}\s*\d{3,4}[A-Z]?)\b", text)
    course_code = code_match.group(1) if code_match else "Course"

    # Instructor pattern
    prof_match = re.search(r"(?:Professor|Instructor|Teacher|Dr\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text)
    instructor = prof_match.group(1) if prof_match else ""

    # Email pattern
    email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    email = email_match.group(0) if email_match else ""

    return {
        "course_code": course_code,
        "course_name": f"{course_code} Course",
        "instructor": instructor,
        "instructor_email": email,
        "assignments": [],
    }


async def import_parsed_syllabus(parsed: dict[str, Any], raw_text: str = "", filename: str = "syllabus.pdf") -> dict[str, Any]:
    """Creates the course in the database and imports extracted assignments."""
    code = parsed.get("course_code") or "COURSE"
    name = parsed.get("course_name") or "New Course"
    instructor = parsed.get("instructor") or ""
    schedule = parsed.get("schedule") or ""

    course = await db.create_course(
        code=code,
        name=name,
        instructor=instructor,
        schedule=schedule,
        portal_type="syllabus",
        color="#3b82f6",
    )
    course_id = course["id"]

    # Save syllabus record
    await db.add_syllabus(
        course_id=course_id,
        filename=filename,
        raw_text=raw_text,
        parsed_json=json.dumps(parsed),
    )

    # Insert assignments into canvas_assignments (unified assignments table)
    conn = await db.get_connection()
    imported_assignments = []
    for item in parsed.get("assignments", []):
        title = item.get("title", "Assignment")
        due_at = item.get("due_date", "")
        points = float(item.get("points") or 100.0)
        canvas_id = f"syllabus-{course_id}-{abs(hash(title)) % 1000000}"

        try:
            await conn.execute(
                """
                INSERT INTO canvas_assignments (
                    canvas_id, course_id, course_name, title, due_at, points, url, submitted, source, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'syllabus', ?)
                ON CONFLICT(canvas_id) DO UPDATE SET
                    title = excluded.title,
                    due_at = excluded.due_at,
                    points = excluded.points
                """,
                (canvas_id, str(course_id), name, title, due_at, points, "", f"Type: {item.get('type', 'homework')}")
            )
            imported_assignments.append({"title": title, "due_at": due_at, "points": points})
        except Exception as exc:
            logger.warning("Failed to insert syllabus assignment %s: %s", title, exc)

    await conn.commit()

    return {
        "course": course,
        "assignments_count": len(imported_assignments),
        "assignments": imported_assignments,
    }
