import requests
import json

url = "https://gamma-api.polymarket.com/markets?active=true&limit=100&order=volume&ascending=false"

resp = requests.get(url)
data = resp.json()

print("Top 5 raw markets:")
for m in data[:5]:
    print(f" - {m.get('question', 'No question')} | ID: {m.get('id', 'No ID')[:12]}... | Slug: {m.get('slug', 'No slug')}")

print("\nSearching for BTC/meme short-term:")
for m in data:
    q = (m.get("question") or "").lower()
    s = (m.get("slug") or "").lower()
    if any(kw in q or kw in s for kw in ["bitcoin", "btc", "pepe", "doge", "shib", "minute", "min", "5m", "15m", "up", "down", "price"]):
        print(f"Match: {m.get('question')} | ID: {m.get('id')[:12]}...")
