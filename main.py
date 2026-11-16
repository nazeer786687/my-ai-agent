import os
import json
import time
import asyncio
import threading
import requests
import yfinance as yf
import telebot
import edge_tts
from flask import Flask
from PIL import Image
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
from google import genai
from google.genai import types

# 1. API Keys & Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MY_CHAT_ID = os.getenv("MY_CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
client = genai.Client(api_key=GEMINI_API_KEY)

# Render Web Service Port Keeper
app = Flask(__name__)

@app.route("/")
def health_check():
    return "ASN TOONS & Zerodha Bot is Live!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

WATCHLIST_FILE = "watchlist.json"
DEFAULT_STOCKS = [
    "INFY.NS", "ITC.NS", "TCS.NS", "HDFCBANK.NS", "HINDUNILVR.NS",
    "RELIANCE.NS", "SUNPHARMA.NS", "TITAN.NS", "LT.NS", "ICICIBANK.NS"
]

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_STOCKS.copy()

def save_watchlist(stocks):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(stocks, f)

# 2. Gemini + Groq Auto-Fallback AI Function
def ask_ai(prompt: str, use_search: bool = False) -> str:
    config = types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    ) if use_search else None

    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=config,
        )
        if response and response.text:
            return response.text
    except Exception:
        pass

    if not GROQ_API_KEY:
        raise RuntimeError("Gemini quota reached and GROQ_API_KEY is missing.")

    groq_models = ["llama-3.1-8b-instant", "openai/gpt-oss-120b", "qwen/qwen3-32b"]
    last_err = ""
    for g_model in groq_models:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": g_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            last_err = f"{g_model} ({resp.status_code}): {resp.text[:150]}"
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(f"Groq Error: {last_err}")

# Natural Human-like Telugu Voice Generator (Microsoft Neural TTS)
async def _generate_voice_async(text: str, output_file: str, voice: str = "te-IN-MohanNeural"):
    communicate = edge_tts.Communicate(text, voice, rate="+5%")
    await communicate.save(output_file)

def make_telugu_voice(text: str, output_file: str):
    asyncio.run(_generate_voice_async(text, output_file))

# 3. Stock Watchlist Commands
@bot.message_handler(commands=["watchlist"])
def handle_watchlist(message):
    bot.reply_to(message, "📊 మీ Zerodha లాంగ్-టర్మ్ సేఫ్టీ వాచ్‌లిస్ట్ లోడ్ అవుతోంది...")
    stocks = load_watchlist()
    results = []
    for sym in stocks:
        try:
            hist = yf.Ticker(sym).history(period="1y")
            if hist.empty:
                continue
            cmp = round(hist["Close"].iloc[-1], 2)
            dma200 = round(hist["Close"].tail(200).mean(), 2)
            high52 = hist["High"].max()
            disc = round(((cmp - high52) / high52) * 100, 1)
            name = sym.replace(".NS", "")
            status = "🎯 బెస్ట్ డిస్కౌంట్" if (cmp >= dma200 and disc <= -15) else (
                "✅ సేఫ్ ట్రెండ్" if cmp >= dma200 else "⚠️ 200-DMA కింద"
            )
            results.append((disc, f"• *{name}*: ₹{cmp} | 200-DMA: ₹{dma200} | {status} ({disc}%)"))
        except Exception:
            continue

    results.sort(key=lambda x: x[0])
    msg = "📋 *మీ Zerodha లాంగ్-టర్మ్ సేఫ్టీ వాచ్‌లిస్ట్*\n\n" + "\n".join([r[1] for r in results])
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=["addstock"])
def add_stock(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "ఉదాహరణ: `/addstock TATAMOTORS`", parse_mode="Markdown")
        return
    sym = parts[1].upper()
    if not sym.endswith(".NS"):
        sym += ".NS"
    stocks = load_watchlist()
    if sym not in stocks:
        stocks.append(sym)
        save_watchlist(stocks)
    bot.reply_to(message, f"✅ {sym} మీ వాచ్‌లిస్ట్‌లో చేర్చబడింది!")

@bot.message_handler(commands=["delstock"])
def del_stock(message):
    parts = message.text.split()
    if len(parts) < 2:
        return
    sym = parts[1].upper()
    if not sym.endswith(".NS"):
        sym += ".NS"
    stocks = load_watchlist()
    if sym in stocks:
        stocks.remove(sym)
        save_watchlist(stocks)
    bot.reply_to(message, f"🗑️ {sym} తీసివేయబడింది.")

# 4. Fast & Low-Memory Telugu Cartoon Short Video (/ytvideo)
@bot.message_handler(commands=["ytvideo"])
def handle_ytvideo(message):
    topic = message.text.replace("/ytvideo", "").strip()
    if not topic:
        topic = "కొంటె కామయ్య పిసినారితనం కథ"

    bot.reply_to(
        message,
        f"🎬 *'{topic}'* కోసం కార్టూన్ బొమ్మలు + నేచురల్ తెలుగు వాయిస్‌తో వీడియో తయారు చేస్తున్నాను (15-20 సెకన్లు)...",
        parse_mode="Markdown"
    )

    try:
        story_prompt = (
            f"Write a funny 4-scene Telugu comedy moral story for YouTube Shorts on: '{topic}'. "
            "Return ONLY a valid JSON array of 4 objects (no markdown, no extra text). "
            "Each object must have: "
            "'telugu_narration' (2 expressive, natural spoken Telugu sentences with proper punctuation) and "
            "'image_prompt' (vivid Disney 2D Indian village cartoon illustration in English, expressive characters, bright colors)."
        )
        raw = ask_ai(story_prompt)
        start_idx = raw.find("[")
        end_idx = raw.rfind("]") + 1
        scenes = json.loads(raw[start_idx:end_idx])

        clips = []
        temp_files = []

        for idx, scene in enumerate(scenes[:4]):
            narration = scene["telugu_narration"]
            style_suffix = ", Disney 2D cartoon illustration, expressive faces, vibrant colors, clean digital art"
            img_prompt = requests.utils.quote(scene["image_prompt"] + style_suffix)
            img_url = f"https://image.pollinations.ai/prompt/{img_prompt}?width=600&height=1066&model=flux&nologo=true&seed={idx+42}"

            img_path = f"scene_{idx}.jpg"
            aud_path = f"voice_{idx}.mp3"
            temp_files.extend([img_path, aud_path])

            try:
                r = requests.get(img_url, timeout=25)
                if r.status_code == 200 and len(r.content
