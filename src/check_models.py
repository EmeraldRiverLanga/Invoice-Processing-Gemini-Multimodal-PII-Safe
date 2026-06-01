"""Temporary diagnostic: list Gemini models available through OpenRouter."""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ["OPENROUTER_API_KEY"]
response = requests.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=30,
)

print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    gemini_models = [
        m["id"] for m in data.get("data", []) if "gemini" in m["id"].lower()
    ]
    print(f"Found {len(gemini_models)} Gemini models:")
    for m in gemini_models:
        print(f"  {m}")
else:
    print(f"Response body: {response.text[:500]}")
