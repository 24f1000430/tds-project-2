import os
import json
import httpx
import re
import asyncio
from dotenv import load_dotenv

load_dotenv()

AIPIPE_URL = os.environ.get("AIPIPE_URL")
AIPIPE_TOKEN = os.environ.get("AIPIPE_TOKEN")

if not AIPIPE_URL:
    raise RuntimeError("AIPIPE_URL must be set.")

if not AIPIPE_TOKEN:
    raise RuntimeError("AIPIPE_TOKEN must be set.")


async def call_aipipe_api(payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {AIPIPE_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(3):
            try:
                r = await client.post(AIPIPE_URL, json=payload, headers=headers)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)

# ------------------------------
# LLM JSON Repair Utilities
# ------------------------------
def try_extract_json(text: str):
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    return None

def repair_json_string(text: str):
    fixed = text.strip()
    fixed = re.sub(r"[\x00-\x1F]+", "", fixed)
    fixed = re.sub(r",\s*}", "}", fixed)
    fixed = re.sub(r",\s*]", "]", fixed)
    fixed = re.sub(r'(\{|,)\s*([A-Za-z0-9_]+)\s*:', r'\1 "\2":', fixed)
    try:
        return json.loads(fixed)
    except:
        return None

async def ask_llm_for_answer(prompt: str) -> str:
    # CHANGED: Use a standard model name
    body = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "When asked for JSON, ALWAYS return valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1500,
        "temperature": 0
    }

    for attempt in range(3):
        try:
            resp = await call_aipipe_api(body)
            # Handle OpenAI standard format
            if "choices" in resp:
                out = resp["choices"][0]["message"]["content"]
            else:
                out = json.dumps(resp)

            if out.strip():
                return out
        except Exception as e:
            print(f"[LLM Error] {e}")

        body["messages"].append({"role": "user", "content": "Return JSON now."})

    return "{}"

async def llm_json(prompt: str) -> dict:
    text = await ask_llm_for_answer(prompt)
    
    try:
        return json.loads(text)
    except:
        pass

    extracted = try_extract_json(text)
    if extracted:
        return extracted

    repaired = repair_json_string(text)
    if repaired:
        return repaired
        
    # Return empty dict instead of crashing
    return {}