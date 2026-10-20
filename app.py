from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import urlparse, quote
import urllib.request
import urllib.error
import json
import re

# Поддерживаем и ddgs, и duckduckgo_search
try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

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

def clean_query(q: str) -> str:
    # Убираем только мусорные приставки вопросов
    stop_words = [
        r"^что такое\s+", r"^кто такой\s+", r"^что это\s+",
        r"^расскажи про\s+", r"^расскажи о\s+", r"^информация о\s+",
        r"^найди\s+", r"^поищи\s+"
    ]
    res = q.strip()
    for pattern in stop_words:
        res = re.sub(pattern, "", res, flags=re.IGNORECASE)
    return res.strip()

def check_wikipedia(term: str):
    """Аккуратная проверка Википедии без лишних ошибок в логах"""
    for lang in ["ru", "en"]:
        try:
            url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(term)}"
            req = urllib.request.Request(url, headers={'User-Agent': 'SoleMeBot/1.0'})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode())
                if data.get('type') == 'standard' and data.get('extract'):
                    return {
                        "title": data.get('title', term),
                        "url": data.get('content_urls', {}).get('desktop', {}).get('page', ''),
                        "domain": f"{lang}.wikipedia.org",
                        "body": data.get('extract', '')
                    }
        except Exception:
            continue
    return None

@app.get("/")
def read_root():
    return {"status": "ok"}

@app.post("/search")
def search(req: SearchRequest):
    raw_query = req.query.replace("[", "").replace("]", "").replace('"', '').strip()
    query = clean_query(raw_query)

    print(f"\n[ПОИСК]: '{raw_query}' -> '{query}'")
    if not query:
        return {"context": "", "sources": []}

    sources = []
    snippets = []

    # 1. Проверяем Википедию
    wiki = check_wikipedia(query)
    if wiki:
        sources.append({"title": wiki["title"], "url": wiki["url"], "domain": wiki["domain"]})
        snippets.append(f"[{wiki['domain']}]: {wiki['title']} — {wiki['body']}")
        print(f"[WIKIPEDIA]: Найдено: {wiki['title']}")

    # 2. Определяем язык: если есть английские буквы — глобальный поиск (wt-wt), иначе СНГ (ru-ru)
    has_latin = bool(re.search(r'[a-zA-Z]', query))
    primary_region = "wt-wt" if has_latin else "ru-ru"

    results = []
    try:
        with DDGS() as ddgs:
            # Основная попытка
            results = list(ddgs.text(query, region=primary_region, max_results=6))

            # Если ничего не нашло, пробуем противоположный регион
            if not results:
                fallback_region = "ru-ru" if primary_region == "wt-wt" else "wt-wt"
                results = list(ddgs.text(query, region=fallback_region, max_results=6))

    except Exception as e:
        print(f"[ОШИБКА DDG]: {e}")

    # 3. Добавляем результаты (НИЧЕГО НЕ ОТБРАСЫВАЕМ!)
    for r in results:
        url = r.get("href", "")
        title = r.get("title", "")
        body = r.get("body", "")
        
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.replace("www.", "")

        if domain and body:
            # Исключаем дубликаты
            if not any(s["url"] == url for s in sources):
                sources.append({
                    "title": title,
                    "url": url,
                    "domain": domain
                })
                snippets.append(f"[{domain}]: {title} — {body}")

    print(f"[УСПЕШНО]: Найдено {len(sources)} источников.")
    return {
        "context": "\n\n".join(snippets),
        "sources": sources
    }
