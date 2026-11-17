import os
import json
import asyncio
import threading
import requests
import yfinance as yf
import telebot
import edge_tts
from flask import Flask, request
from PIL import Image
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
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

async def _voice_async(text: str, out: str, voice: str = "te-IN-MohanNeural"):
    comm = edge_tts.Communicate(text, voice, rate="+5%")
    await comm.save(out)

def make_telugu_voice(text: str, out: str):
    asyncio.run(_voice_async(text, out))

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

def create_video_task(chat_id: int, topic: str):
    try:
        story_prompt = (
            f"Write a funny 4-scene Telugu comedy moral story for YouTube Shorts on: '{topic}'. "
            "Return ONLY a valid JSON array of 4 objects (no markdown). "
            "Keys: 'telugu_narration' (2 expressive spoken Telugu sentences) and "
            "'image_prompt' (vivid Disney 2D Indian village cartoon illustration in English)."
        )
        raw = ask_ai(story_prompt)
        s_idx = raw.find("[")
        e_idx = raw.rfind("]") + 1
        scenes = json.loads(raw[s_idx:e_idx])

        clips = []
        temp_files = []

        for idx, scene in enumerate(scenes[:4]):
            narration = scene["telugu_narration"]
            suffix = ", Disney 2D cartoon illustration, expressive faces, vibrant colors"
            q_prompt = requests.utils.quote(scene["image_prompt"] + suffix)
            img_url = f"https://image.pollinations.ai/prompt/{q_prompt}?width=600&height=1066&model=flux&nologo=true&seed={idx+42}"

            img_path = f"scene_{idx}.jpg"
            aud_path = f"voice_{idx}.mp3"
            temp_files.extend([img_path, aud_path])

            try:
                r = requests.get(img_url, timeout=25)
                ok = (r.status_code == 200) and (len(r.content) > 2000)
                if ok:
                    with open(img_path, "wb") as f:
                        f.write(r.content)
                else:
                    raise ValueError("Fallback")
            except Exception:
                colors = [(255, 220, 130), (180, 235, 255), (200, 255, 200), (255, 200, 220)]
                im = Image.new("RGB", (600, 1066), colors[idx % 4])
                im.save(img_path)

            make_telugu_voice(narration, aud_path)

            audio_clip = AudioFileClip(aud_path)
            img_clip = ImageClip(img_path).with_duration(audio_clip.duration + 0.3).with_audio(audio_clip)
            clips.append(img_clip)

        final_video = concatenate_videoclips(clips, method="compose")
        out_path = "asn_toons_hd.mp4"
        temp_files.append(out_path)
        final_video.write_videofile(
            out_path,
            fps=12,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            logger=None
        )

        with open(out_path, "rb") as vf:
            bot.send_video(chat_id, vf, caption=f"🎥 *ASN TOONS:* {topic}", parse_mode="Markdown")

        final_video.close()
        for c in clips:
            c.close()
        for tf in temp_files:
            if os.path.exists(tf):
                os.remove(tf)

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ వీడియో తయారీలో లోపం: {e}")

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
    threading.Thread(target=create_video_task, args=(message.chat.id, topic), daemon=True).start()

@bot.message_handler(func=lambda m: True)
def handle_all(message):
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
