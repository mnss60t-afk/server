import os
import warnings
warnings.filterwarnings("ignore")

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import urllib.parse
import concurrent.futures

# Импортируем официальную библиотеку DuckDuckGo, которая умеет обходить защиту
from duckduckgo_search import DDGS

app = Flask(__name__)
CORS(app)

BAD_DOMAINS = [
    'microsoft.com', 'otvet.mail.ru', 'znanija.com', 'qna.center', 
    'reddit.com', 'quora.com', 'translate.', 'dictionary.', 'reverso.', 
    'aliexpress.', 'youtube.com', 'tiktok.com', 'wiktionary.org', 
    'yandex.', 'google.', 'yahoo.', 'bing.', 'duckduckgo.', 'rutube.ru', 
    'baidu.com', 'zhihu.com', 'bilibili.com', 'weibo.com', '.cn', '.jp'
]
CAPTCHA_PHRASES = ["Just a moment", "Checking your browser", "Enable JavaScript", "Cloudflare", "DDoS-Guard"]

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form"]):
        element.extract()
    main_content = soup.find('article') or soup.find('main') or soup.find(id='content') or soup.body
    if not main_content: 
        return ""
    texts = [element.get_text(strip=True) for element in main_content.find_all(['p', 'h1', 'h2', 'h3', 'li']) if len(element.get_text(strip=True)) > 30]
    final_string = '\n'.join(texts)[:1500]
    if any(captcha in final_string for captcha in CAPTCHA_PHRASES): 
        return ""
    return final_string

def process_site(site_data):
    url = site_data['url']
    full_text = ""
    try:
        # Используем современный User-Agent, чтобы сайты не блокировали сам Render при чтении содержимого
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=3.0)
        if res.status_code == 200: 
            full_text = extract_text(res.text)
    except Exception: 
        pass
    final_text = full_text if len(full_text) > 100 else site_data['snippet']
    return {"title": site_data['title'], "url": url, "domain": site_data['domain'], "snippet": site_data['snippet'], "text": final_text}

def get_clean_search_results(query):
    results = []
    seen_domains = set()
    
    try:
        # Инициализируем парсер через официальный API библиотеки
        with DDGS() as ddgs:
            # Ищем по региону ru-ru. Метод text() автоматически подбирает рабочие шлюзы
            ddgs_gen = ddgs.text(query, region="ru-ru", safesearch="off")
            
            for r in ddgs_gen:
                href = r.get('href', '')
                if not href:
                    continue
                    
                domain = urllib.parse.urlparse(href).netloc.lower()
                
                # Фильтруем плохие домены и дубликаты
                if domain in seen_domains or any(bad in domain for bad in BAD_DOMAINS):
                    continue
                    
                seen_domains.add(domain)
                results.append({
                    "title": r.get('title', '').strip(),
                    "url": href,
                    "domain": domain,
                    "snippet": r.get('body', '').strip()
                })
                
                if len(results) >= 5:
                    break
    except Exception as e:
        print(f"❌ Ошибка DDGS API: {e}. Пробуем альтернативный метод...")
        # Резервный вариант, если основной шлюз временно упал
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, region="ru-ru", backend="lite"):
                    href = r.get('href', '')
                    domain = urllib.parse.urlparse(href).netloc.lower()
                    if domain in seen_domains or any(bad in domain for bad in BAD_DOMAINS):
                        continue
                    seen_domains.add(domain)
                    results.append({
                        "title": r.get('title', ''),
                        "url": href,
                        "domain": domain,
                        "snippet": r.get('body', '')
                    })
                    if len(results) >= 5:
                        break
        except Exception as critical_e:
            print(f"❌ Критическая ошибка поиска: {critical_e}")
            
    return results

@app.route('/search', methods=['POST'])
def search():
    # Защита на случай, если клиент прислал пустой JSON или не тот Content-Type
    data = request.get_json(silent=True) or {}
    query = data.get('query')
    
    if not query: 
        return jsonify({"error": "Empty query"}), 400

    try:
        print(f"\n🔍 ЗАПРОС: {query}")
        top_sites = get_clean_search_results(query)

        valid_sites = []
        # Распараллеливаем чтение контента сайтов (максимум 5 потоков)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_site, s) for s in top_sites]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res: 
                    valid_sites.append(res)

        final_context = "".join([f"--- ИСТОЧНИК: {s['title']} ({s['domain']}) ---\n{s['text']}\n\n" for s in valid_sites])
        sources = [{"title": s['title'], "url": s['url'], "domain": s['domain'], "snippet": s['snippet']} for s in valid_sites]

        print(f"✅ Успешно прочитано сайтов: {len(valid_sites)}\n")
        return jsonify({"context": final_context, "sources": sources})
        
    except Exception as e:
        print(f"💥 Ошибка в обработчике /search: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Render автоматически передает нужный порт в переменную окружения PORT. 
    # Этот фикс не позволит приложению упасть со статус-кодом 502/504 на хостинге.
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
