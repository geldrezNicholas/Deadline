"""List models the current API key can call. Does not consume generate quota."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from google import genai  # noqa: E402

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Models supporting generateContent:\n")
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or []
    if "generateContent" in actions:
        print(f"  {m.name}")
