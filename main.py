import os
import json
import time
import textwrap
import requests
import yfinance as yf
import telebot
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
from google import genai
from google.genai import types

# 1. API Keys & Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MY_CHAT_ID = os.getenv("MY_CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

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

# 3. Stock Watchlist Command
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

# 4. Automated Telugu 2D Cartoon Short Video (/ytvideo)
@bot.message_handler(commands=["ytvideo"])
def handle_ytvideo(message):
    topic = message.text.replace("/ytvideo", "").strip()
    if not topic:
        topic = "కొంటె కామయ్య పిసినారితనం కథ"

    bot.reply_to(
        message,
        f"🎬 *'{topic}'* కోసం 2D కార్టూన్ బొమ్మలు + తెలుగు వాయిస్‌తో MP4 వీడియో తయారు చేస్తున్నాను (20-30 సెకన్లు)...",
        parse_mode="Markdown"
    )

    try:
        story_prompt = (
            f"Write a very funny 4-scene Telugu moral comedy short story for YouTube Shorts on the topic: '{topic}'. "
            "Return ONLY valid JSON array of 4 objects, no markdown, no extra text. "
            "Each object must have keys: 'telugu_narration' (2 short funny Telugu sentences) and "
            "'image_prompt' (vivid 2D colorful Indian village cartoon illustration description in English)."
        )
        raw = ask_ai(story_prompt)
        start_idx = raw.find("[")
        end_idx = raw.rfind("]") + 1
        scenes = json.loads(raw[start_idx:end_idx])

        clips = []
        temp_files = []

        for idx, scene in enumerate(scenes[:4]):
            narration = scene["telugu_narration"]
            img_prompt = requests.utils.quote(scene["image_prompt"] + ", 2d cartoon animation style, vibrant colors")
            img_url = f"https://image.pollinations.ai/prompt/{img_prompt}?width=540&height=960&nologo=true&seed={idx+10}"

            img_path = f"scene_{idx}.jpg"
            aud_path = f"voice_{idx}.mp3"
            temp_files.extend([img_path, aud_path])

            # Download Image (with solid color fallback if busy)
            try:
                r = requests.get(img_url, timeout=20)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(img_path, "wb") as f:
                        f.write(r.content)
                else:
                    raise ValueError("Fallback image")
            except Exception:
                colors = [(255, 220, 130), (180, 235, 255), (200, 255, 200), (255, 200, 220)]
                im = Image.new("RGB", (540, 960), colors[idx % 4])
                im.save(img_path)

            # Generate Telugu Voice
            tts = gTTS(text=narration, lang="te")
            tts.save(aud_path)

            audio_clip = AudioFileClip(aud_path)
            img_clip = ImageClip(img_path).with_duration(audio_clip.duration + 0.4).with_audio(audio_clip)
            clips.append(img_clip)

        final_video = concatenate_videoclips(clips, method="compose")
        out_path = "asn_toons_short.mp4"
        temp_files.append(out_path)
        final_video.write_videofile(out_path, fps=10, codec="libx264", audio_codec="aac", logger=None)

        with open(out_path, "rb") as vf:
            bot.send_video(message.chat.id, vf, caption=f"🎥 *ASN TOONS:* {topic}", parse_mode="Markdown")

        final_video.close()
        for c in clips:
            c.close()
        for tf in temp_files:
            if os.path.exists(tf):
                os.remove(tf)

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ వీడియో తయారీలో లోపం: {e}")

# 5. General Chat Handler
@bot.message_handler(func=lambda m: True)
def handle_all(message):
    try:
        reply = ask_ai(f"Reply in helpful, polite Telugu to: {message.text}")
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"సర్వర్ బిజీగా ఉంది: {e}")

if __name__ == "__main__":
    print("ASN TOONS & Zerodha Agent Started...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
