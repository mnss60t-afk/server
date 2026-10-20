import os
import warnings
warnings.filterwarnings("ignore")

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import urllib.parse
import concurrent.futures

app = Flask(__name__)
CORS(app)

# Список исключений (оставляем ваш без изменений)
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
        # Устанавливаем качественный User-Agent, чтобы конечные сайты не блокировали Render при скрапинге статьи
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=3.0)
        if res.status_code == 200: 
            full_text = extract_text(res.text)
    except Exception: 
        pass
    
    # Если сайт не отдал текст (защита от парсинга), отдаем нейросети хотя бы его сниппет из выдачи
    final_text = full_text if len(full_text) > 100 else site_data['snippet']
    return {"title": site_data['title'], "url": url, "domain": site_data['domain'], "snippet": site_data['snippet'], "text": final_text}

def get_clean_search_results(query):
    results = []
    seen_domains = set()
    
    # Список надежных публичных шлюзов SearXNG, которые игнорируют блокировки дата-центров
    instances = [
        "https://mdcnet.de",
        "https://searx.be",
        "https://priv.au"
    ]
    
    for base_url in instances:
        try:
            print(f"🔄 Пробуем пробить интернет через шлюз: {base_url}")
            params = {
                'q': query,
                'format': 'json',
                'language': 'ru-RU'
            }
            # Делаем запрос к API, который возвращает чистый JSON вместо верстки
            response = requests.get(base_url, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                search_entries = data.get('results', [])
                
                for r in search_entries:
                    href = r.get('url', '')
                    if not href: continue
                    
                    domain = urllib.parse.urlparse(href).netloc.lower()
                    if domain in seen_domains or any(bad in domain for bad in BAD_DOMAINS): 
                        continue
                    
                    seen_domains.add(domain)
                    results.append({
                        "title": r.get('title', '').strip(),
                        "url": href,
                        "domain": domain,
                        "snippet": r.get('content', '').strip()
                    })
                    
                    if len(results) >= 5: 
                        return results
                        
                if results: 
                    return results
        except Exception as e:
            print(f"⚠️ Шлюз {base_url} выдал ошибку, переключаемся...")
            continue
            
    return results

@app.route('/search', methods=['POST'])
def search():
    data = request.get_json(silent=True) or {}
    query = data.get('query')
    
    if not query: 
        return jsonify({"error": "Empty query"}), 400

    try:
        print(f"\n🔍 ВХОДЯЩИЙ ЗАПРОС НЕЙРОСЕТИ: {query}")
        top_sites = get_clean_search_results(query)

        valid_sites = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_site, s) for s in top_sites]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res: 
                    valid_sites.append(res)

        final_context = "".join([f"--- ИСТОЧНИК: {s['title']} ({s['domain']}) ---\n{s['text']}\n\n" for s in valid_sites])
        sources = [{"title": s['title'], "url": s['url'], "domain": s['domain'], "snippet": s['snippet']} for s in valid_sites]

        print(f"✅ Успешно прочитано сайтов для нейросети: {len(valid_sites)}\n")
        return jsonify({"context": final_context, "sources": sources})
        
    except Exception as e:
        print(f"💥 Критический сбой API: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
