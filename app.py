from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from duckduckgo_search import DDGS
from urllib.parse import urlparse, quote
import urllib.request
import json
import re

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
    # Убираем паразитные слова, которые ломают поиск
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
    try:
        url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{quote(term)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode())
            if data.get('type') == 'standard' and 'extract' in data:
                return {
                    "title": data.get('title', term),
                    "url": data.get('content_urls', {}).get('desktop', {}).get('page', ''),
                    "domain": "ru.wikipedia.org",
                    "body": data.get('extract', '')
                }
    except Exception:
        pass
    return None

@app.get("/")
def read_root():
    return {"status": "ok"}

@app.post("/search")
def search(req: SearchRequest):
    raw_query = req.query.replace("[", "").replace("]", "").replace('"', '').strip()
    query = clean_query(raw_query)
    
    print(f"\n[ИСХОДНЫЙ ЗАПРОС]: '{raw_query}' -> [ОЧИЩЕННЫЙ]: '{query}'")
    if not query:
        return {"context": "", "sources": []}

    sources = []
    snippets = []

    # 1. Если это термин, пробуем Википедию
    wiki_res = check_wikipedia(query)
    if wiki_res:
        sources.append({
            "title": wiki_res["title"],
            "url": wiki_res["url"],
            "domain": wiki_res["domain"]
        })
        snippets.append(f"[{wiki_res['domain']}]: {wiki_res['title']} — {wiki_res['body']}")
        print(f"[WIKIPEDIA]: Найдена статья '{wiki_res['title']}'")

    # 2. Ищем в DuckDuckGo
    # Если есть английские буквы (например 'sayodevice'), отключаем ru-ru, чтобы не было бредовых замен
    has_latin = bool(re.search(r'[a-zA-Z]', query))
    search_region = None if has_latin else "ru-ru"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region=search_region, max_results=6))
            
            # Если с очищенным запросом пусто, пробуем точный поиск в кавычках
            if not results and has_latin:
                results = list(ddgs.text(f'"{query}"', max_results=5))

        for r in results:
            url = r.get("href", "")
            title = r.get("title", "")
            body = r.get("body", "")
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace("www.", "")

            # Фильтр мусора: если мы искали слово на латинице (например sayodevice), 
            # оно ОБЯЗАНО быть в заголовке или тексте сниппета!
            if has_latin:
                main_word = [w for w in query.split() if re.search(r'[a-zA-Z]', w)][0].lower()
                if main_word not in title.lower() and main_word not in body.lower():
                    print(f"[ОТБРОШЕН МУСОР]: {title}")
                    continue

            if domain and body:
                sources.append({
                    "title": title,
                    "url": url,
                    "domain": domain
                })
                snippets.append(f"[{domain}]: {title} — {body}")

        print(f"[УСПЕШНО НАЙДЕНО]: {len(sources)} релевантных источников")
        return {
            "context": "\n\n".join(snippets),
            "sources": sources
        }

    except Exception as e:
        print(f"[ОШИБКА DDG]: {e}")
        return {
            "context": "\n\n".join(snippets),
            "sources": sources
        }
