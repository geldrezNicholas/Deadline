"""Live end-to-end check of the text -> Gemini -> items step.

Uses your real key from .env. Run:
    venv\Scripts\python.exe tests\live_gemini.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from syllabus.gemini_client import extract_items  # noqa: E402

SAMPLE = """\
CS 301 - Algorithms, Fall 2025

Homework 1 due Friday, September 12, 2025.
Midterm exam: October 20, 2025 in class.
Final project proposal due week 10 (date TBD).
Office hours: Tuesdays 2-4pm.
Final exam during finals week, December 2025.
"""

print("Calling Gemini...\n")
items = extract_items(SAMPLE)
for it in items:
    flag = "" if it.confident else "  <-- low confidence"
    print(f"  {str(it.date):<12} {it.title}{flag}")
print(f"\nExtracted {len(items)} item(s). Live pipeline works.")
