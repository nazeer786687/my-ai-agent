import os
import time
import json
import asyncio
import threading
import urllib.parse
import requests
import pytz
import yfinance as yf
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from gtts import gTTS
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from http.server import HTTPServer, BaseHTTPRequestHandler
from apscheduler.schedulers.background import BackgroundScheduler
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Kodad AI Video & Zerodha Watchlist Agent is Alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_CHAT_ID = os.getenv("MY_CHAT_ID")

client = genai.Client(api_key=GEMINI_API_KEY)

USER_WATCHLIST = [
    "TCS", "INFY", "HDFCBANK", "ICICIBANK", "RELIANCE",
    "ITC", "LT", "SUNPHARMA", "TITAN", "HINDUNILVR"
]

def ask_gemini(prompt: str, use_search: bool = False) -> str:
    config = types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    ) if use_search else None

    last_error = ""
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=config,
            )
            return response.text
        except Exception as e:
            last_error = str(e)
            time.sleep(2)
    raise RuntimeError(last_error)

def get_gold_silver_text() -> str:
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            f_inr = executor.submit(lambda: yf.Ticker("INR=X").history(period="2d")["Close"].iloc[-1])
            f_gold = executor.submit(lambda: yf.Ticker("GC=F").history(period="2d")["Close"].iloc[-1])
            f_silver = executor.submit(lambda: yf.Ticker("SI=F").history(period="2d")["Close"].iloc[-1])
            usdinr = f_inr.result()
            gold_oz = f_gold.result()
            silver_oz = f_silver.result()

        gold_24k = int(round((gold_oz / 31.1035) * 10 * usdinr * 1.06, 0))
        gold_22k = int(round(gold_24k * 0.916, 0))
        silver_1kg = int(round((silver_oz / 31.1035) * 1000 * usdinr * 1.06, 0))

        return (
            "🟡 *ఈరోజు బంగారం & వెండి ధరలు (భారత మార్కెట్ అంచనా):*\n"
            f"• *24K బంగారం (10 గ్రాములు):* ₹{gold_24k:,}\n"
            f"• *22K బంగారం (10 గ్రాములు):* ₹{gold_22k:,}\n"
            f"• *వెండి (1 కిలో):* ₹{silver_1kg:,}"
        )
    except Exception:
        return "🟡 *బంగారం & వెండి:* ప్రస్తుతం లైవ్ ఫీడ్ బిజీగా ఉంది, కాసేపట్లో ప్రయత్నించండి."

def analyze_watchlist_stock(sym: str):
    try:
        hist = yf.Ticker(f"{sym}.NS").history(period="1y")
        if not hist.empty:
            cmp = round(hist["Close"].iloc[-1], 2)
            high_1y = round(hist["High"].max(), 2)
            dma200 = round(hist["Close"].tail(200).mean(), 2) if len(hist) >= 200 else cmp
            discount_pct = round(((high_1y - cmp) / high_1y) * 100, 1)

            if discount_pct >= 12 and cmp >= dma200 * 0.95:
                status = f"🎯 బెస్ట్ డిస్కౌంట్ (-{discount_pct}%)"
            elif cmp > dma200:
                status = f"✅ సేఫ్ ట్రెండ్ (-{discount_pct}%)"
            else:
                status = f"⚠️ 200-DMA కింద (-{discount_pct}%)"

            return (discount_pct, sym, cmp, dma200, status)
    except Exception:
        pass
    return None

def build_watchlist_report() -> str:
    if not USER_WATCHLIST:
        return "మీ వాచ్‌లిస్ట్ ఖాళీగా ఉంది. `/addstock TCS` ద్వారా స్టాక్స్ జత చేయండి."

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(analyze_watchlist_stock, USER_WATCHLIST))

    valid = [r for r in results if r is not None]
    valid.sort(reverse=True)

    lines = ""
    for disc, sym, cmp, dma200, status in valid:
        lines += f"• *{sym}*: ₹{cmp} | 200-DMA: ₹{dma200} | {status}\n"

    return (
        "📋 *మీ Zerodha లాంగ్-టర్మ్ సేఫ్టీ వాచ్‌లిస్ట్*\n"
        "_(52-వారాల గరిష్టం నుండి ఎక్కువ డిస్కౌంట్ ఉన్నవి పైన చూపబడ్డాయి)_\n\n"
        f"{lines}\n"
        "➕ కొత్త స్టాక్ యాడ్ చేయడానికి: `/addstock సింబల్`\n"
        "➖ తీసేయడానికి: `/delstock సింబల్`"
    )

def build_market_report() -> str:
    bullion_block = get_gold_silver_text()
    watchlist_block = build_watchlist_report()
    return (
        "📈 *డైలీ మార్కెట్ & Zerodha అలర్ట్ నివేదిక*\n\n"
        f"{bullion_block}\n\n"
        f"{watchlist_block}\n\n"
        "💡 _Zerodha లాంగ్-టర్మ్ క్యాపిటల్ సేఫ్టీ ఫిల్టర్ ఆధారంగా రూపొందించబడింది._"
    )

def generate_full_mp4_video(topic: str, chat_id: int) -> tuple:
    prompt = (
        f"Create a 4-scene Telugu YouTube Shorts moral comedy story for 'ASN TOONS' on the topic: '{topic}'. "
        f"Keep each Telugu narration sentence short and punchy (10-15 words per scene). "
        f"Return ONLY valid JSON without markdown backticks:\n"
        f'{{"title": "Catchy Telugu Title", "scenes": ['
        f'{{"narration": "Telugu sentence 1", "image_prompt": "2D colorful Indian village cartoon illustration, bright colors, scene 1"}}, '
        f'{{"narration": "Telugu sentence 2", "image_prompt": "2D colorful Indian village cartoon illustration, bright colors, scene 2"}}, '
        f'{{"narration": "Telugu sentence 3", "image_prompt": "2D colorful Indian village cartoon illustration, bright colors, scene 3"}}, '
        f'{{"narration": "Telugu sentence 4 moral", "image_prompt": "2D colorful Indian village cartoon illustration, bright colors, scene 4"}}'
        f']}}'
    )

    raw = ask_gemini(prompt, use_search=False).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())

    title = data.get("title", topic)
    scenes = data.get("scenes", [])[:4]

    temp_files = []
    clips = []

    try:
        for idx, sc in enumerate(scenes):
            narration = sc["narration"]
            img_prompt = sc["image_prompt"]

            aud_path = f"sc_{chat_id}_{idx}.mp3"
            tts = gTTS(text=narration, lang="te", slow=False)
            tts.save(aud_path)
            temp_files.append(aud_path)

            audio_clip = AudioFileClip(aud_path)
            duration = max(audio_clip.duration + 0.2, 2.5)

            img_path = f"sc_{chat_id}_{idx}.jpg"
            encoded_prompt = urllib.parse.quote(img_prompt)
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=540&height=960&nologo=true&seed={idx+20}"

            try:
                resp = requests.get(img_url, timeout=15)
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                img = img.resize((540, 960), Image.Resampling.LANCZOS)
            except Exception:
                colors = [(255, 220, 150), (180, 230, 255), (200, 255, 200), (255, 200, 220)]
                img = Image.new("RGB", (540, 960), colors[idx % 4])

            img.save(img_path, quality=80)
            temp_files.append(img_path)

            img_clip = ImageClip(img_path).set_duration(duration).set_audio(audio_clip)
            clips.append(img_clip)

        final_video = concatenate_videoclips(clips, method="compose")
        out_mp4 = f"asn_toons_{chat_id}.mp4"
        final_video.write_videofile(
            out_mp4,
            fps=10,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=1,
            logger=None
        )

        final_video.close()
        for c in clips:
            c.close()

        return out_mp4, title
    finally:
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "నమస్కారం నజీర్ గారు! మీ *కోదాడ AI వీడియో & Zerodha అసిస్టెంట్* సిద్ధంగా ఉంది.\n\n"
        "🎬 *YouTube ఆటో వీడియో మేకర్:*\n"
        "• `/ytvideo <టాపిక్>` — బొమ్మలు + తెలుగు వాయిస్‌తో పూర్తి **MP4 YouTube Short** (15 సెకన్లలో!)\n"
        "• `/yt <టాపిక్>` — పెద్ద వీడియోల కోసం స్క్రిప్ట్, ప్రాంప్ట్‌లు & MP3 ఆడియో\n\n"
        "📊 *Zerodha వాచ్‌లిస్ట్ & మార్కెట్:*\n"
        "• `/watchlist` — మీ వాచ్‌లిస్ట్ స్టాక్స్ డిస్కౌంట్ & సేఫ్టీ స్థితి\n"
        "• `/addstock <సింబల్>` — వాచ్‌లిస్ట్‌లో కొత్త స్టాక్ చేర్చడం\n"
        "• `/delstock <సింబల్>` — వాచ్‌లిస్ట్ నుండి స్టాక్ తీసేయడం\n"
        "• `/gold` — బంగారం & వెండి ధరలు (2 సెకన్లలో)\n"
        "• `/market` — పూర్తి మార్కెట్ & వాచ్‌లిస్ట్ రిపోర్ట్"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    report = await asyncio.to_thread(build_watchlist_report)
    await update.message.reply_text(report, parse_mode="Markdown")

async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ఉదాహరణ: `/addstock TATAMOTORS`", parse_mode="Markdown")
        return
    sym = context.args[0].upper().replace(".NS", "")
    if sym in USER_WATCHLIST:
        await update.message.reply_text(f"*{sym}* ఇప్పటికే మీ వాచ్‌లిస్ట్‌లో ఉంది పప్పా!", parse_mode="Markdown")
        return
    USER_WATCHLIST.append(sym)
    await update.message.reply_text(f"✅ *{sym}* మీ Zerodha వాచ్‌లిస్ట్‌లో చేర్చబడింది! `/watchlist` నొక్కి చూడండి.", parse_mode="Markdown")

async def delstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ఉదాహరణ: `/delstock SBIN`", parse_mode="Markdown")
        return
    sym = context.args[0].upper().replace(".NS", "")
    if sym in USER_WATCHLIST:
        USER_WATCHLIST.remove(sym)
        await update.message.reply_text(f"🗑️ *{sym}* మీ వాచ్‌లిస్ట్ నుండి తొలగించబడింది.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"*{sym}* మీ వాచ్‌లిస్ట్‌లో లేదు.", parse_mode="Markdown")

async def ytvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ఉదాహరణ:\n`/ytvideo కొంటె కామయ్య పిసినారితనం కథ`", parse_mode="Markdown")
        return

    topic = " ".join(context.args)
    await update.message.reply_text(
        f"🎥 *'{topic}'* కోసం 2D కార్టూన్ బొమ్మలు + తెలుగు వాయిస్‌తో **MP4 వీడియో** తయారు చేస్తున్నాను (15–20 సెకన్లు)...",
        parse_mode="Markdown"
    )

    try:
        mp4_path, title = await asyncio.to_thread(generate_full_mp4_video, topic, update.effective_chat.id)
        with open(mp4_path, "rb") as vid:
            await update.message.reply_video(
                video=vid,
                caption=f"🎬 *{title}*\n\nమీ ASN TOONS YouTube Short వీడియో సిద్ధంగా ఉంది!",
                parse_mode="Markdown",
                supports_streaming=True
            )
        if os.path.exists(mp4_path):
            os.remove(mp4_path)
    except Exception as e:
        await update.message.reply_text(f"వీడియో తయారీలో లోపం తలెత్తింది: {e}")

async def gold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    res = await asyncio.to_thread(get_gold_silver_text)
    await update.message.reply_text(res, parse_mode="Markdown")

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    report = await asyncio.to_thread(build_market_report)
    await update.message.reply_text(report, parse_mode="Markdown")

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ఉదాహరణ: `/stock RELIANCE`", parse_mode="Markdown")
        return

    symbol = context.args[0].upper()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        hist = await asyncio.to_thread(lambda: yf.Ticker(f"{symbol}.NS").history(period="1y"))
        if not hist.empty:
            cmp = round(hist["Close"].iloc[-1], 2)
            high_1y = round(hist["High"].max(), 2)
            low_1y = round(hist["Low"].min(), 2)
            dma200 = round(hist["Close"].tail(200).mean(), 2) if len(hist) >= 200 else cmp
            trend = "బుల్లిష్ (200-DMA పైన ఉంది ✅)" if cmp > dma200 else "బేరిష్ (200-DMA కింద ఉంది ⚠️)"

            res = (
                f"📊 *{symbol} (NSE) విశ్లేషణ*\n\n"
                f"• ప్రస్తుత ధర (CMP): ₹{cmp}\n"
                f"• 52-వారాల గరిష్టం: ₹{high_1y}\n"
                f"• 52-వారాల కనిష్టం: ₹{low_1y}\n"
                f"• 200-Day Average: ₹{dma200}\n"
                f"• ట్రెండ్ స్థితి: {trend}"
            )
            await update.message.reply_text(res, parse_mode="Markdown")
        else:
            await update.message.reply_text("ఆ స్టాక్ సింబల్ దొరకలేదు.")
    except Exception as e:
        await update.message.reply_text(f"లోపం: {e}")

async def youtube_creator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ఉదాహరణ: `/yt కొంటె కామయ్య పిసినారితనం కథ`", parse_mode="Markdown")
        return

    topic = " ".join(context.args)
    await update.message.reply_text(f"🎬 *'{topic}'* కోసం స్క్రిప్ట్, ప్రాంప్ట్‌లు & MP3 ఆడియో సిద్ధం చేస్తున్నాను...", parse_mode="Markdown")

    prompt = (
        f"You are an expert Telugu YouTube content creator for 'ASN TOONS' (2D cartoon moral comedy stories). "
        f"Create a YouTube video package for: '{topic}'.\n"
        f"1. CATCHY TELUGU TITLES (3 options)\n"
        f"2. SCENE-BY-SCENE STORYBOARD & AI IMAGE PROMPTS (4-5 scenes)\n"
        f"3. CLEAN VOICEOVER SCRIPT ONLY (Pure Telugu spoken dialogues only, no scene numbers or English words)."
    )

    try:
        full_output = await asyncio.to_thread(ask_gemini, prompt, False)
        for i in range(0, len(full_output), 4000):
            await update.message.reply_text(full_output[i:i+4000])

        vo_text = full_output.split("3.")[-1] if "3." in full_output else full_output
        clean_vo = vo_text.replace("*", "").replace("#", "").strip()[:2500]

        if clean_vo:
            audio_path = f"yt_voice_{update.effective_chat.id}.mp3"
            tts = gTTS(text=clean_vo, lang="te", slow=False)
            await asyncio.to_thread(tts.save, audio_path)

            with open(audio_path, "rb") as audio_file:
                await update.message.reply_audio(
                    audio=audio_file,
                    title=f"ASN_TOONS_{topic[:20]}",
                    caption="🎙️ తెలుగు వాయిస్ ఓవర్ (MP3) సిద్ధం!"
                )
            if os.path.exists(audio_path):
                os.remove(audio_path)
    except Exception as e:
        await update.message.reply_text(f"కంటెంట్ తయారీలో లోపం: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    lower_text = user_text.lower()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    if "watchlist" in lower_text:
        res = await asyncio.to_thread(build_watchlist_report)
        await update.message.reply_text(res, parse_mode="Markdown")
        return

    if ("gold" in lower_text or "silver" in lower_text) and "stock" not in lower_text:
        res = await asyncio.to_thread(get_gold_silver_text)
        await update.message.reply_text(res, parse_mode="Markdown")
        return

    if ("best stock" in lower_text or ("gold" in lower_text and "stock" in lower_text)):
        res = await asyncio.to_thread(build_market_report)
        await update.message.reply_text(res, parse_mode="Markdown")
        return

    try:
        reply_text = await asyncio.to_thread(ask_gemini, user_text, True)
        for i in range(0, len(reply_text), 4000):
            await update.message.reply_text(reply_text[i:i+4000])
    except Exception as e:
        await update.message.reply_text(f"సర్వర్ బిజీగా ఉంది, ఒక్క నిమిషం తర్వాత ప్రయత్నించండి. ({e})")

def scheduled_morning_alert(app, loop):
    if not MY_CHAT_ID:
        return
    try:
        report = build_market_report()
        asyncio.run_coroutine_threadsafe(
            app.bot.send_message(chat_id=int(MY_CHAT_ID), text=f"☀️ *శుభోదయం నజీర్ గారు!*\n\n{report}", parse_mode="Markdown"),
            loop
        )
    except Exception as e:
        print(f"Scheduled alert error: {e}")

def main():
    threading.Thread(target=run_health_server, daemon=True).start()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("watchlist", watchlist))
    app.add_handler(CommandHandler("addstock", addstock))
    app.add_handler(CommandHandler("delstock", delstock))
    app.add_handler(CommandHandler("ytvideo", ytvideo))
    app.add_handler(CommandHandler("yt", youtube_creator))
    app.add_handler(CommandHandler("gold", gold))
    app.add_handler(CommandHandler("silver", gold))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("beststocks", market))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    ist = pytz.timezone("Asia/Kolkata")
    scheduler = BackgroundScheduler(timezone=ist)
    scheduler.add_job(scheduled_morning_alert, "cron", hour=9, minute=0, args=[app, loop])
    scheduler.start()

    print("Kodad AI Auto Video & Zerodha Watchlist Agent is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
