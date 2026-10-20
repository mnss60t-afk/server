from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from duckduckgo_search import DDGS
from urllib.parse import urlparse

app = FastAPI()

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
    # Очищаем запрос от случайных скобок и кавычек
    query = req.query.replace("[", "").replace("]", "").replace('"', '').strip()
    print(f"\n[ЗАПРОС ОТ НЕЙРОСЕТИ]: '{query}'")

    if not query:
        return {"context": "", "sources": []}

    try:
        sources = []
        snippets = []

        with DDGS() as ddgs:
            # 1. Пробуем найти актуальные результаты в регионе RU
            results = list(ddgs.text(query, region="ru-ru", max_results=5))
            # 2. Если на русском пусто, ищем глобально
            if not results:
                results = list(ddgs.text(query, max_results=5))

        for r in results:
            url = r.get("href", "")
            title = r.get("title", "")
            body = r.get("body", "")

            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace("www.", "")

            if domain and body:
                sources.append({
                    "title": title,
                    "url": url,
                    "domain": domain
                })
                snippets.append(f"[{domain}]: {title} — {body}")

        print(f"[НАЙДЕНО]: {len(sources)} источников.")
        context = "\n\n".join(snippets)

        return {
            "context": context,
            "sources": sources
        }

    except Exception as e:
        print(f"[ОШИБКА ПОИСКА]: {e}")
        return {"context": "", "sources": []}
