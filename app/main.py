import os
import re
import json
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from .solver import solve_quiz_chain
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="LLM Analysis Quiz Solver")

# Config - read from environment, default to the values you provided
QUIZ_SECRET = os.environ.get("QUIZ_SECRET")
QUIZ_EMAIL = os.environ.get("QUIZ_EMAIL")
TIMEOUT_SECONDS = int(os.environ.get("SOLVE_TIMEOUT_S", "170"))
  # must finish within 3 minutes (180s) HTTP to allow

class QuizPayload(BaseModel):
    email: str
    secret: str
    url: str

@app.post("/quiz")
async def quiz_endpoint(payload: QuizPayload, request: Request):
    # Validate secret
    if payload.secret != QUIZ_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # Basic check: URL present
    if not payload.url:
        raise HTTPException(status_code=400, detail="Missing url field")

    # Launch solver and return quickly with a success JSON.
    # The requirement: Respond with HTTP200 JSON if secret matches.
    # We'll also run the solver and include status in the response body.
    # But evaluation expects that we actually visit & solve the quiz and submit an answer.
    # We'll run the solver but not block too long: await with timeout.
    try:
        result = await asyncio.wait_for(
            solve_quiz_chain(payload.email, payload.secret, payload.url, QUIZ_EMAIL),
            timeout=TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        # Return 200 but indicate we timed out in solver. (You can change to 500 if you want)
        return JSONResponse(status_code=200, content={"status": "timeout", "detail": "Solver timed out"})
    except Exception as e:
        return JSONResponse(status_code=200, content={"status": "error", "detail": str(e)})

    return JSONResponse(status_code=200, content={"status": "ok", "result": result})

@app.get("/")
def root():
    return {"message": "LLM Analysis Quiz Solver. POST /quiz with JSON {email, secret, url}"}
