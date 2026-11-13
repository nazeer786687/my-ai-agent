import os
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
        self.wfile.write(b"Kodad AI Video & Stock Agent is Alive!")

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

def ask_gemini(prompt: str, use_search: bool = False) -> str:
    models_to_try = ["gemini-3.8-flash", "gemini-2.5-flash"]
    config = types.GenerateContentConfig(
        tools=[{"google_search": {}}]
    ) if use_search else None

    last_error = ""
    for attempt in range(3):
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e:
                last_error = str(e)
                continue
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

def check_single_stock(sym: str):
    try:
        hist = yf.Ticker(f"{sym}.NS").history(period="1y")
        if len(hist) >= 200:
            cmp = round(hist["Close"].iloc[-1], 2)
            prev = round(hist["Close"].iloc[-2], 2)
            dma200 = round(hist["Close"].tail(200).mean(), 2)
            dma50 = round(hist["Close"].tail(50).mean(), 2)
            chg_pct = round(((cmp - prev) / prev) * 100, 2)
            if cmp > dma200 and cmp <= dma50 * 1.08:
                return (chg_pct, sym, cmp, dma200)
    except Exception:
        pass
    return None

def build_market_report() -> str:
    bullion_block = get_gold_silver_text()
    safe_watchlist = [
        "TCS", "INFY", "HDFCBANK", "ICICIBANK", "RELIANCE",
        "ITC", "LT", "SUNPHARMA", "BHARTIARTL", "TITAN", "SBIN", "HINDUNILVR"
    ]
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(check_single_stock, safe_watchlist))

    picks = [r for r in results if r is not None]
    picks.sort(reverse=True)
    top_picks = picks[:5]

    stock_lines = ""
    if top_picks:
        for chg, sym, cmp, dma200 in top_picks:
            sign = "+" if chg >= 0 else ""
            stock_lines += f"• *{sym}*: ₹{cmp} ({sign}{chg}%) | 200-DMA: ₹{dma200}\n"
    else:
        stock_lines = "• ప్రస్తుతం ప్రధాన స్టాక్స్ కన్సాలిడేషన్‌లో ఉన్నాయి.\n"

    return (
        "📈 *డైలీ మార్కెట్ & సేఫ్ స్టాక్స్ నివేదిక*\n\n"
        f"{bullion_block}\n\n"
        "🛡️ *లాంగ్-టర్మ్ సేఫ్టీ వాచ్‌లిస్ట్ (200-DMA పైన ఉన్నవి):*\n"
        f"{stock_lines}\n"
        "💡 _Zerodha లాంగ్-టర్మ్ సేఫ్టీ ఫిల్టర్ ఆధారంగా చూపబడినవి._"
    )

def generate_full_mp4_video(topic: str, chat_id: int) -> tuple:
    prompt = (
        f"Create a 4-scene Telugu YouTube Shorts moral comedy story for 'ASN TOONS' on the topic: '{topic}'. "
        f"Return ONLY valid JSON without any markdown backticks, in this exact format:\n"
        f'{{"title": "Catchy Telugu Title", "scenes": ['
        f'{{"narration": "Telugu sentence 1", "image_prompt": "2D colorful Indian village cartoon style illustration, bright lighting, expressive characters, scene 1 description"}}, '
        f'{{"narration": "Telugu sentence 2", "image_prompt": "2D colorful Indian village cartoon style illustration, bright lighting, expressive characters, scene 2 description"}}, '
        f'{{"narration": "Telugu sentence 3", "image_prompt": "2D colorful Indian village cartoon style illustration, bright lighting, expressive characters, scene 3 description"}}, '
        f'{{"narration": "Telugu sentence 4 with moral", "image_prompt": "2D colorful Indian village cartoon style illustration, bright lighting, expressive characters, scene 4 description"}}'
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
            duration = max(audio_clip.duration + 0.3, 3.0)

            img_path = f"sc_{chat_id}_{idx}.jpg"
            encoded_prompt = urllib.parse.quote(img_prompt)
            img_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=720&height=1280&nologo=true&seed={idx+10}"

            resp = requests.get(img_url, timeout=30)
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img = img.resize((720, 1280), Image.Resampling.LANCZOS)
            img.save(img_path, quality=85)
            temp_files.append(img_path)

            img_clip = (
                ImageClip(img_path)
                .set_duration(duration)
                .resize(lambda t: 1 + 0.04 * (t / duration))
                .set_position("center")
                .set_audio(audio_clip)
            )
            clips.append(img_clip)

        final_video = concatenate_videoclips(clips, method="compose")
        out_mp4 = f"asn_toons_{chat_id}.mp4"
        final_video.write_videofile(
            out_mp4,
            fps=15,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=2,
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
        "నమస్కారం నజీర్ గారు! మీ *కోదాడ AI వీడియో & మార్కెట్ అసిస్టెంట్* సిద్ధంగా ఉంది.\n\n"
        "🎬 *YouTube ఆటో వీడియో మేకర్:*\n"
        "• `/ytvideo <టాపిక్>` — నేరుగా బొమ్మలు + తెలుగు వాయిస్‌తో **MP4 YouTube Short వీడియో** తయారు చేస్తుంది!\n"
        "• `/yt <టాపిక్>` — పెద్ద వీడియోల కోసం స్క్రిప్ట్, ప్రాంప్ట్‌లు & MP3 ఆడియో ఇస్తుంది\n\n"
        "📊 *స్టాక్ మార్కెట్ & బులియన్:*\n"
        "• `/gold` — బంగారం & వెండి ధరలు (2 సెకన్లలో)\n"
        "• `/market` — బెస్ట్ సేఫ్ స్టాక్స్ + గోల్డ్ & సిల్వర్ రిపోర్ట్\n"
        "• `/stock <సింబల్>` — ఏదైనా NSE స్టాక్ విశ్లేషణ"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def ytvideo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "ఉదాహరణకు ఇలా పంపండి:\n`/ytvideo కొంటె కామయ్య పిసినారితనం కథ`",
            parse_mode="Markdown"
        )
        return

    topic = " ".join(context.args)
    await update.message.reply_text(
        f"🎥 *'{topic}'* కోసం 2D కార్టూన్ బొమ్మలు + తెలుగు వాయిస్‌తో పూర్తి **MP4 వీడియో** తయారు చేస్తున్నాను...\n"
        "⏳ సుమారు 30–45 సెకన్లు వేచి ఉండండి పప్పా!",
        parse_mode="Markdown"
    )

    try:
        mp4_path, title = await asyncio.to_thread(generate_full_mp4_video, topic, update.effective_chat.id)
        with open(mp4_path, "rb") as vid:
            await update.message.reply_video(
                video=vid,
                caption=f"🎬 *{title}*\n\nమీ ASN TOONS YouTube Short వీడియో సిద్ధంగా ఉంది! నేరుగా అప్‌లోడ్ చేసుకోవచ్చు.",
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

    print("Kodad AI Auto Video & Stock Agent is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
