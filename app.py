from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from duckduckgo_search import DDGS
from urllib.parse import urlparse

app = FastAPI()

# Включаем CORS, чтобы сайт (Netlify или localhost) мог отправлять запросы
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    query: str

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Search server is running"}

@app.post("/search")
def search(req: SearchRequest):
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    try:
        sources = []
        snippets = []

        # Поиск актуальных данных через DuckDuckGo
        with DDGS() as ddgs:
            # Ищем 5 самых релевантных результатов
            results = list(ddgs.text(query, region="ru-ru", max_results=5))

        for r in results:
            url = r.get("href", "")
            title = r.get("title", "")
            body = r.get("body", "")
            
            # Извлекаем домен (например: wikipedia.org)
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace("www.", "")

            if domain:
                sources.append({
                    "title": title,
                    "url": url,
                    "domain": domain
                })
                snippets.append(f"[{domain}]: {title} — {body}")

        # Склеиваем весь найденный контекст для нейросети
        context = "\n\n".join(snippets)

        return {
            "context": context,
            "sources": sources
        }

    except Exception as e:
        print(f"Ошибка при поиске: {e}")
        # Если поиск ничего не нашел или временно заблокирован
        return {
            "context": "",
            "sources": []
        }
