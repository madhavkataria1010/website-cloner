from fastapi import FastAPI, HTTPException
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
import os
from openai import AsyncOpenAI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Browser
import base64
from contextlib import asynccontextmanager

# Load environment variables from .env file at the very start
load_dotenv()

# --- PERFORMANCE OPTIMIZATION START ---
playwright_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager to launch a persistent Playwright browser instance on app startup
    and gracefully close it on shutdown.
    """
    async with async_playwright() as p:
        print("Launching persistent browser instance...")
        browser = await p.chromium.launch(headless=True)
        playwright_state["browser"] = browser
        yield
        print("Closing persistent browser instance...")
        await browser.close()

app = FastAPI(lifespan=lifespan)
# --- PERFORMANCE OPTIMIZATION END ---

# Configure CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello World"}

async def scrape_website(url: str) -> Optional[Dict[str, Any]]:
    """
    Asynchronously scrape a website using the PERSISTENT Playwright browser instance
    to get both the HTML content and a screenshot.
    """
    browser: Browser = playwright_state.get("browser")
    if not browser:
        print("Browser not available!")
        return None

    page = await browser.new_page()
    try:
        print(f"Scraping {url} with Playwright...")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        
        html_content = await page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        screenshot_bytes = await page.screenshot(full_page=True)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        print("Scraping successful.")
        return {
            "html": soup.prettify(),
            "screenshot": screenshot_base64
        }
    except Exception as e:
        print(f"Scraping failed with Playwright: {e}")
        return None
    finally:
        if not page.is_closed():
            await page.close()

async def clone_with_llm(data: Dict[str, Any]) -> Optional[str]:
    """Use an OpenAI multimodal model to generate a static page from HTML and a screenshot."""
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        
        client = AsyncOpenAI(api_key=api_key)
        
        html_content = data["html"]
        screenshot_base64 = data.get("screenshot")

        # --- UPDATED PROMPT TO DEMAND HIGH FIDELITY ---
        system_prompt = (
            "You are an automated frontend assistant. Your task is to generate a single, static HTML file that is a HIGH-FIDELITY visual reproduction of a provided screenshot. "
            "A low-fidelity or simplified version is considered a failure. "
            "This is for a design-to-code exercise. Do not replicate the page's functionality, only its static visual design. "
            "The screenshot is the source of truth for all visual styles. The provided HTML is only a structural guide. "
            "RULES: "
            "1. The entire output must be a single, self-contained HTML file. "
            "2. All CSS must be in a single `<style>` tag in the `<head>`. "
            "3. ALL `<img>` tags MUST use this exact placeholder: `<img src='https://placehold.co/600x400/EEE/31343C?text=Image'>`. "
            "4. Do NOT include any `<script>` tags or JavaScript. "
            "5. Your response MUST contain ONLY the raw HTML code. Do not add any '```', comments, or explanations."
        )
        
        # --- RESTRUCTURED USER MESSAGE TO FOCUS AI ON THE IMAGE ---
        user_content = [
            {
                "type": "text",
                "text": "Analyze this screenshot and the provided HTML. Your task is to create a high-fidelity static HTML recreation of the visual design shown in the screenshot. Pay close attention to all details, including layout, typography, and colors."
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{screenshot_base64}",
                    "detail": "high"
                },
            },
            {
                "type": "text",
                "text": f"Here is the original HTML for structural reference:\n\n{html_content}"
            }
        ]


        response = await client.chat.completions.create(
            model="gpt-4.1-2025-04-14",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            max_tokens=10000,
        )
        
        if response.choices and response.choices[0].message.content:
            generated_html = response.choices[0].message.content.strip()
            if generated_html.startswith("```html"):
                generated_html = generated_html[7:]
            if generated_html.endswith("```"):
                generated_html = generated_html[:-3]
            return generated_html.strip()
        else:
            reason = response.choices[0].finish_reason if response.choices else "No choices returned"
            print(f"!!! AI response was empty or invalid. Finish Reason: {reason}")
            if reason == 'content_filter':
                return "The request was blocked by the content filter."
            return None

    except Exception as e:
        print(f"An error occurred in clone_with_llm: {e}")
        return None

class CloneRequest(BaseModel):
    url: str

@app.post("/api/clone")
async def clone_website_endpoint(request: CloneRequest):
    scraped_data = await scrape_website(request.url)
    if scraped_data is None:
        raise HTTPException(status_code=500, detail="Failed to scrape the target website.")
        
    generated_html = await clone_with_llm(scraped_data)
    if generated_html is None:
        raise HTTPException(status_code=500, detail="AI model failed to generate the HTML content.")
    if "The request was blocked by the content filter." in generated_html:
        raise HTTPException(status_code=400, detail="AI content filter blocked the request. Try a different URL.")
        
    return {"html_content": generated_html}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)