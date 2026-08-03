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

BAD_DOMAINS = ['microsoft.com', 'otvet.mail.ru', 'znanija.com', 'qna.center', 'reddit.com', 'quora.com', 'translate.', 'dictionary.', 'reverso.', 'aliexpress.', 'youtube.com', 'tiktok.com', 'wiktionary.org', 'yandex.', 'google.', 'yahoo.', 'bing.', 'duckduckgo.', 'rutube.ru', 'baidu.com', 'zhihu.com', 'bilibili.com', 'weibo.com', '.cn', '.jp']
CAPTCHA_PHRASES = ["Just a moment", "Checking your browser", "Enable JavaScript", "Cloudflare", "DDoS-Guard"]

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup(["script", "style", "nav", "footer", "header", "noscript", "aside", "form"]):
        element.extract()
    main_content = soup.find('article') or soup.find('main') or soup.find(id='content') or soup.body
    if not main_content: return ""
    texts = [element.get_text(strip=True) for element in main_content.find_all(['p', 'h1', 'h2', 'h3', 'li']) if len(element.get_text(strip=True)) > 30]
    final_string = '\n'.join(texts)[:1500]
    if any(captcha in final_string for captcha in CAPTCHA_PHRASES): return ""
    return final_string

def process_site(site_data):
    url = site_data['url']
    full_text = ""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
        res = requests.get(url, headers=headers, timeout=2.0)
        if res.status_code == 200: full_text = extract_text(res.text)
    except Exception: pass
    final_text = full_text if len(full_text) > 100 else site_data['snippet']
    return {"title": site_data['title'], "url": url, "domain": site_data['domain'], "snippet": site_data['snippet'], "text": final_text}

def get_clean_search_results(query):
    url = "https://html.duckduckgo.com/html/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://html.duckduckgo.com/'
    }
    try:
        response = requests.post(
            url,
            data={'q': query, 'kl': 'ru-ru', 'l': 'ru-ru'},
            headers=headers,
            timeout=5
        )
        soup = BeautifulSoup(response.text, 'html.parser')
        results, seen_domains = [], set()
        for result in soup.find_all('div', class_='result'):
            a_tag = result.find('a', class_='result__url')
            if not a_tag: continue
            href = urllib.parse.unquote(a_tag.get('href', '').split('uddg=')[1].split('&')[0]) if 'uddg=' in a_tag.get('href', '') else a_tag.get('href', '')
            domain = urllib.parse.urlparse(href).netloc.lower()
            if domain in seen_domains or any(bad in domain for bad in BAD_DOMAINS): continue
            title_tag = result.find('h2', class_='result__title')
            snippet_tag = result.find('a', class_='result__snippet')
            if title_tag and snippet_tag:
                seen_domains.add(domain)
                results.append({"title": title_tag.text.strip(), "url": href, "domain": domain, "snippet": snippet_tag.text.strip()})
            if len(results) >= 5: break
        return results
    except: return []

@app.route('/search', methods=['POST'])
def search():
    query = request.json.get('query')
    if not query: return jsonify({"error": "Empty"}), 400

    try:
        print(f"\n🔍 ЗАПРОС: {query}")
        top_sites = get_clean_search_results(query)

        valid_sites = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_site, s) for s in top_sites]
            for future in concurrent.futures.as_completed(futures):
                if future.result(): valid_sites.append(future.result())

        final_context = "".join([f"--- ИСТОЧНИК: {s['title']} ({s['domain']}) ---\n{s['text']}\n\n" for s in valid_sites])
        sources = [{"title": s['title'], "url": s['url'], "domain": s['domain'], "snippet": s['snippet']} for s in valid_sites]

        print(f"✅ Успешно прочитано сайтов: {len(valid_sites)}\n")
        return jsonify({"context": final_context, "sources": sources})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':

    app.run(host='0.0.0.0',port=5000, debug=True)
