import os
import json
import time
import asyncio
import threading
import subprocess
import requests
import yfinance as yf
import telebot
import edge_tts
import imageio_ffmpeg
from flask import Flask, request
from PIL import Image, ImageOps
from google import genai
from google.genai import types

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://nazeer-ai-bot.onrender.com")

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
client = genai.Client(api_key=GEMINI_API_KEY)
app = Flask(__name__)

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

def ask_ai(prompt: str, use_search: bool = False) -> str:
    cfg = types.GenerateContentConfig(tools=[{"google_search": {}}]) if use_search else None
    try:
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=cfg,
        )
        if res and res.text:
            return res.text
    except Exception:
        pass

    if not GROQ_API_KEY:
        raise RuntimeError("Gemini quota reached and GROQ_API_KEY is missing.")

    models = ["llama-3.1-8b-instant", "openai/gpt-oss-120b", "qwen/qwen3-32b"]
    last_err = ""
    for m in models:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": m,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            last_err = f"{m} ({r.status_code})"
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(f"AI Error: {last_err}")

def get_live_gold_report() -> str:
    try:
        gold_hist = yf.Ticker("GC=F").history(period="2d")
        usd_inr_hist = yf.Ticker("INR=X").history(period="2d")
        if gold_hist.empty or usd_inr_hist.empty:
            raise ValueError("Market feed temporarily unavailable")

        oz_usd = float(gold_hist["Close"].iloc[-1])
        usd_inr = float(usd_inr_hist["Close"].iloc[-1])
        base_10g_inr = (oz_usd / 31.1034768) * usd_inr * 10
        retail_24k = round(base_10g_inr * 1.0918)
        retail_22k = round(retail_24k * 0.916)
        retail_18k = round(retail_24k * 0.750)

        return (
            "🪙 *లైవ్ ఇండియా / హైదరాబాద్ & కోదాడ స్పాట్ బంగారం ధరలు (10 గ్రాములు)*\n\n"
            f"• *24K (999 స్వచ్ఛమైనది):* ₹{retail_24k:,}\n"
            f"• *22K (916 ఆభరణాలు):* ₹{retail_22k:,}\n"
            f"• *18K బంగారం:* ₹{retail_18k:,}\n\n"
            f"📊 _అంతర్జాతీయ స్పాట్: ${oz_usd:,.2f}/oz | USD/INR: ₹{usd_inr:.2f}_"
        )
    except Exception as e:
        return f"⚠️ లైవ్ బంగారం ధర లోడ్ కాలేదు: {e}"

@bot.message_handler(commands=["gold"])
def handle_gold_cmd(message):
    bot.reply_to(message, get_live_gold_report(), parse_mode="Markdown")

async def _voice_async(text: str, out: str, voice: str = "te-IN-MohanNeural"):
    comm = edge_tts.Communicate(text, voice, rate="+6%")
    await comm.save(out)

def make_telugu_voice(text: str, out: str):
    asyncio.run(_voice_async(text, out))

# NEW: Google Flow Pro Director Command (/flow)
@bot.message_handler(commands=["flow"])
def handle_google_flow(message):
    topic = message.text.replace("/flow", "").strip()
    if not topic:
        topic = "కొంటె కామయ్య పిసినారితనం కథ"

    bot.reply_to(
        message,
        f"🎬 *Google Flow Pro* కోసం *'{topic}'* స్క్రిప్ట్, 4 సినిమాటిక్ వీడియో ప్రాంప్ట్‌లు & నేచురల్ తెలుగు వాయిస్ MP3 సిద్ధం చేస్తున్నాను...",
        parse_mode="Markdown"
    )

    try:
        prompt = (
            f"Create a 4-scene Telugu comedy moral story for YouTube Shorts on: '{topic}'. "
            "Return ONLY a valid JSON object (no markdown) with keys: "
            "'character_sheet' (exact consistent visual description of main character in English: clothes, age, hair, face), "
            "'scenes' (array of 4 objects, each having 'telugu_voice' - 2 natural expressive spoken Telugu sentences, "
            "and 'flow_prompt' - detailed 3D Pixar-style animated video prompt for Google Veo/Flow including camera movement, character action, Indian village lighting, 9:16 vertical)."
        )
        raw = ask_ai(prompt)
        s_idx = raw.find("{")
        e_idx = raw.rfind("}") + 1
        data = json.loads(raw[s_idx:e_idx])

        char_desc = data.get("character_sheet", "")
        scenes = data.get("scenes", [])[:4]

        full_telugu_script = " ".join([s["telugu_voice"] for s in scenes])
        audio_path = "asn_flow_voiceover.mp3"
        make_telugu_voice(full_telugu_script, audio_path)

        msg_lines = [f"🎥 *GOOGLE FLOW PRO STUDIO PACK: {topic}*\n"]
        msg_lines.append(f"👤 *Character Style:* `{char_desc}`\n")

        for i, sc in enumerate(scenes, 1):
            msg_lines.append(f"*Scene {i} (8 sec):*")
            msg_lines.append(f"🗣️ _{sc['telugu_voice']}_")
            msg_lines.append(f"📋 Copy Prompt:\n`{char_desc}. {sc['flow_prompt']}, 3D Pixar animation style, vibrant colors, smooth camera motion`\n")

        bot.send_message(message.chat.id, "\n".join(msg_lines), parse_mode="Markdown")

        with open(audio_path, "rb") as af:
            bot.send_audio(
                message.chat.id,
                af,
                title=f"ASN TOONS - {topic}",
                performer="ASN TOONS Telugu",
                caption="🎙️ *పూర్తి కథ నేచురల్ తెలుగు వాయిస్ ఓవర్ (MP3)* — Google Flow వీడియో క్లిప్‌లకు నేరుగా యాడ్ చేయండి!"
            )

        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ లోపం: {e}")

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

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    text_lower = message.text.lower()
    if any(k in text_lower for k in ["gold", "బంగారం", "bangaram", "22k", "24k"]):
        bot.reply_to(message, get_live_gold_report(), parse_mode="Markdown")
        return

    try:
        reply = ask_ai(f"Reply in helpful, polite Telugu to: {message.text}")
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"సర్వర్ బిజీగా ఉంది: {e}")

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def health_check():
    webhook_url = f"{RENDER_URL}/{TELEGRAM_TOKEN}"
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}", timeout=10)
    except Exception:
        pass
    return "ASN TOONS & Zerodha Bot Webhook Active!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    webhook_url = f"{RENDER_URL}/{TELEGRAM_TOKEN}"
    try:
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}", timeout=10)
        print("Webhook set successfully!")
    except Exception as e:
        print(f"Webhook setup error: {e}")
    app.run(host="0.0.0.0", port=port)
