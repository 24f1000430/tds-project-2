---
title: Tds Project 2
emoji: 🏃
colorFrom: green
colorTo: pink
sdk: docker
pinned: false
license: mit
short_description: tds project 2
---


FastAPI-based solver that accepts quiz requests, visits JS-rendered quiz pages with Playwright, uses heuristics + an LLM (GPT-5 via AIPipe) to compute answers, and submits them to the target submit endpoints.

## Files
- `app/main.py` - FastAPI server with `/quiz` endpoint.
- `app/solver.py` - Page rendering + solving logic using Playwright.
- `app/llm.py` - Generic AIPipe wrapper (reads `AIPIPE` env var).
- `Dockerfile` - Docker image suitable for Hugging Face Spaces (with Playwright).
- `requirements.txt` - Python deps.

## Environment variables
Set these in your deployment or `.env`:
- `AIPIPE` - **Required.** The AIPipe endpoint URL or token. Adjust `app/llm.py` if your AIPipe expects different payload shapes.
- `QUIZ_SECRET` - The secret string you provided on the Google Form (default `SEC437`).
- `QUIZ_EMAIL` - The email you provided (default `24f1000430@ds.study.iitm.ac.in`).
- `PORT` - Port to run uvicorn on (Hugging Face sets this automatically).

## Quick local run (development)
1. Install Python 3.11 and Docker (or run directly with Playwright installed).
2. Optionally, create `.env` file:
