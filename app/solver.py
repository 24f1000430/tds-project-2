import os
import re
import json
import asyncio
import httpx
import io
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
from playwright.async_api import async_playwright

from .llm import llm_json

# ============================================================
#                    URL NORMALIZATION
# ============================================================

def normalize_url(base: str, raw: str):
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    try:
        return urljoin(base, raw)
    except:
        return None

async def find_submit(html: str, links: list, base_url: str):
    """
    Find submit URL in links or by scanning HTML for form actions.
    """
    # 1. Check specific link text
    for link in links:
        if "submit" in link.lower():
            return normalize_url(base_url, link)
            
    # 2. Regex scan for form actions
    matches = re.findall(r"action=[\"'](.*?)[\"']", html)
    for m in matches:
        if "submit" in m:
            return normalize_url(base_url, m)
            
    # 3. Regex catch-all
    matches = re.findall(r"([A-Za-z0-9\.\-:/\?\&_=%]+submit[^\s\"']*)", html)
    if matches:
        return normalize_url(base_url, matches[0])
        
    return None

# ============================================================
#                     NETWORK HELPERS
# ============================================================

async def render_page(url: str, timeout=60):
    print(f"[DEBUG] Rendering page: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"], headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(url, timeout=timeout * 1000)
            await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
        except Exception as e:
            print(f"[WARN] Page load warning: {e}")

        # CLEANUP: Remove scripts, styles, and SVGs to save tokens
        # but KEEP the HTML structure so we see attributes/comments.
        await page.evaluate("""
            document.querySelectorAll('script, style, svg, link[rel="stylesheet"]').forEach(e => e.remove());
        """)

        html = await page.content()
        text = await page.inner_text("body")
        
        # Extract all links
        anchors = await page.query_selector_all("a")
        links = []
        for a in anchors:
            href = await a.get_attribute("href")
            if href:
                links.append(href)
        
        await browser.close()
        return html, text, links

async def download(url: str):
    print(f"[DEBUG] Downloading: {url}")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content

# ============================================================
#                DATA EXTRACTION HELPERS
# ============================================================

def extract_pdf_text(pdf_bytes: bytes):
    """Extract text and tables from all pages of a PDF."""
    text_content = ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text_content += (page.extract_text() or "") + "\n"
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        text_content += " | ".join([str(x) for x in row if x]) + "\n"
    except Exception as e:
        text_content += f"\n[Error reading PDF: {e}]"
    return text_content

async def fetch_linked_resources(base_url, links):
    resource_text = ""
    extensions = {".csv", ".txt", ".json", ".log", ".xml", ".md"}
    
    targets = []
    for link in links:
        full_url = normalize_url(base_url, link)
        if not full_url: continue
        path = full_url.split("?")[0].lower()
        if any(path.endswith(ext) for ext in extensions):
            targets.append(full_url)

    for url in set(targets):
        try:
            content = await download(url)
            text = content.decode("utf-8", errors="replace")
            snippet = text[:15000] 
            resource_text += f"\n\n--- CONTENT OF LINKED FILE: {url} ---\n{snippet}\n"
            if len(text) > 15000:
                resource_text += "... [Content Truncated] ...\n"
        except Exception as e:
            print(f"[WARN] Failed to fetch resource {url}: {e}")
            
    return resource_text

# ============================================================
#                    SOLVE SINGLE TASK
# ============================================================

async def solve_single(email: str, secret: str, quiz_url: str):
    print(f"\n========== Solving Quiz: {quiz_url} ==========")

    # 1. Gather raw data (HTML + Text + Links)
    html, text, links = await render_page(quiz_url)
    
    # 2. Gather External Context (CSV/PDF/Logs)
    context_data = await fetch_linked_resources(quiz_url, links)
    
    pdf_links = [l for l in links if l.lower().endswith(".pdf")]
    for pl in pdf_links:
        try:
            purl = normalize_url(quiz_url, pl)
            pbytes = await download(purl)
            ptext = extract_pdf_text(pbytes)
            context_data += f"\n\n--- CONTENT OF PDF {purl} ---\n{ptext}\n"
        except Exception as e:
            print(f"[WARN] PDF fetch failed: {e}")

    # ============================================================
    #                 AGENT 1: THE PLANNER
    # ============================================================
    # This agent looks at the "World" (HTML/Files) and decides "How" to solve it.
    
    planner_prompt = f"""
You are the PLANNER Agent.
Your goal is to understand the quiz question and create a step-by-step plan for the Solver.

PAGE HTML (Truncated):
{html[:50000]}

PAGE LINKS:
{json.dumps(links)}

Return JSON:
{{
  "question_summary": "Briefly state what must be answered",
  "data_source": "Where is the data? (e.g., 'In the CSV', 'Hidden in <div id=secret>', 'In the visible text')",
  "plan_steps": [
     "Step 1: Locate the CSV link and parse it.",
     "Step 2: Filter for rows where city='Paris'.",
     "Step 3: Sum the 'sales' column."
  ]
}}
"""
    print("[DEBUG] Calling Planner Agent...")
    plan_info = await llm_json(planner_prompt)
    print(f"[DEBUG] Plan: {json.dumps(plan_info, indent=2)}")

    # ============================================================
    #                 AGENT 2: THE EXECUTOR
    # ============================================================
    # This agent takes the PLAN and the DATA and computes the final JSON.
    
    executor_prompt = f"""
You are the EXECUTOR Agent. Follow the plan below to solve the problem.

PLAN:
{json.dumps(plan_info)}

PAGE HTML SOURCE:
{html[:50000]}

DOWNLOADED FILE CONTENTS:
{context_data}

INSTRUCTIONS:
1. Execute the `plan_steps` using the provided HTML and FILE CONTENTS.
2. If the plan says "find hidden value", look in the HTML attributes.
3. If the plan says "calculate", perform the math accurately.
4. Construct the final JSON payload.

Return JSON:
{{
  "answer": <the_final_calculated_value>,
  "reasoning": "Brief explanation of how you followed the plan",
  "submit_payload": {{
     "email": "{email}",
     "secret": "{secret}",
     "url": "{quiz_url}",
     "answer": <the_final_calculated_value>
     // Include other fields if the page explicitly requires them
  }}
}}
"""
    print("[DEBUG] Calling Executor Agent...")
    result = await llm_json(executor_prompt)
    print(f"[DEBUG] Executor Result: {result.get('answer')}")

    # ============================================================
    #                      SUBMIT ANSWER
    # ============================================================
    submit_url = await find_submit(html, links, quiz_url)
    
    if submit_url and "submit_payload" in result:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                r = await client.post(submit_url, json=result["submit_payload"])
                # We return the response even if it's an error code, because the quiz 
                # often returns 400/500 with the "Next URL" in the body.
                try:
                    resp = r.json()
                    return {"submitted": True, "response": resp, "answer": result["answer"]}
                except:
                    return {"submitted": True, "response": r.text, "answer": result["answer"]}
            except Exception as e:
                return {"submitted": True, "error": str(e), "answer": result["answer"]}

    return {"submitted": False, "result": result}


# ============================================================
#                QUIZ CHAIN RUNNER
# ============================================================

async def solve_quiz_chain(email, secret, url, owner_email):
    steps = []
    current = url

    for i in range(12): 
        print(f"\n--- STEP {i+1}: {current} ---")
        try:
            step = await solve_single(email, secret, current)
        except Exception as e:
            print(f"[ERROR] Step failed: {e}")
            step = {"error": str(e)}
            
        steps.append({"url": current, "result": step})

        next_url = None
        if "response" in step and isinstance(step["response"], dict):
            next_url = step["response"].get("url")
            
            # Stop if the server explicitly says correct=False and gives no next URL
            if step["response"].get("correct") is False and not next_url:
                print("[STOP] Answer incorrect and no continuation URL.")
                break
        
        if not next_url:
            break
        current = next_url

    return steps