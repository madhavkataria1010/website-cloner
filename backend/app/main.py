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
# A dictionary to hold the persistent browser instance, available for the app's entire lifespan.
playwright_state = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager to launch a persistent Playwright browser instance on app startup
    and gracefully close it on shutdown.
    """
    async with async_playwright() as p:
        print("Launching persistent browser instance...")
        browser = await p.chromium.launch()
        playwright_state["browser"] = browser
        yield
        # This block runs on app shutdown
        print("Closing persistent browser instance...")
        await browser.close()

# Pass the lifespan manager to the FastAPI app.
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
    to get both the HTML content and a screenshot for multimodal analysis.
    """
    browser: Browser = playwright_state.get("browser")
    if not browser:
        print("Browser not available!")
        return None

    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        
        # Get HTML content
        html_content = await page.content()
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Take screenshot and encode as base64
        screenshot_bytes = await page.screenshot(full_page=True)
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        return {
            "html": soup.prettify(),
            "screenshot": screenshot_base64
        }
    except Exception as e:
        print(f"Scraping failed with Playwright: {e}")
        return None
    finally:
        # Ensure the page is closed to free up resources
        await page.close()


async def clone_with_llm(data: Dict[str, Any]) -> Optional[str]:
    """Use an OpenAI multimodal model to clone a website from its HTML and a screenshot."""
    try:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("Error: OPENAI_API_KEY not found in environment.")
            raise RuntimeError("OPENAI_API_KEY not set")
        
        client = AsyncOpenAI(api_key=api_key)
        
        html_content = data["html"]
        screenshot_base64 = data["screenshot"]

        system_prompt = (
            "You are an expert web developer tasked with creating a high-fidelity clone of a webpage. "
            "You will be given a screenshot of the page for visual reference and the page's raw HTML for structural context. "
            "Your goal is to recreate the visual appearance of the page as closely as possible. "
            "Your output MUST be a single, self-contained HTML file. "
            "All CSS must be included within a single <style> tag in the <head>. "
            "For images, do NOT use external `src` URLs. Instead, use placeholder images from a service like 'https://placehold.co' that match the dimensions and general color scheme of the original images. For example: <img src='https://placehold.co/600x400/EEE/31343C?text=Product+Image'>. "
            "Do not include any JavaScript. "
            "Your response must contain ONLY the raw HTML code. Do not include '```html' or any other markdown formatting."
        )
        
        response = await client.chat.completions.create(
            model="chatgpt-4o-latest",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Here is the raw HTML of the page:\n\n{html_content}"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot_base64}"
                            },
                        },
                    ],
                }
            ],
            max_tokens=10056,
        )
        
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content.strip()
        else:
            print(f"!!! AI response was empty. Finish Reason: {response.choices[0].finish_details}")
            return None

    except Exception as e:
        print(f"An error occurred in clone_with_llm: {e}")
        return None


class CloneRequest(BaseModel):
    url: str

@app.post("/api/clone")
async def clone_website(request: CloneRequest):
    scraped_data = await scrape_website(request.url)
    if scraped_data is None:
        raise HTTPException(status_code=500, detail="Failed to scrape the target website.")
        
    cloned = await clone_with_llm(scraped_data)
    if cloned is None:
        raise HTTPException(status_code=500, detail="AI model failed to generate the clone.")
        
    return {"html_content": cloned}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

