import os
import asyncio
import threading
import pytz
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
from gtts import gTTS
from http.server import HTTPServer, BaseHTTPRequestHandler
from apscheduler.schedulers.background import BackgroundScheduler
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Kodad AI Production Agent is Alive!")

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

def ask_gemini(prompt: str) -> str:
    models_to_try = ["gemini-3.8-flash", "gemini-3.8-flash-lite"]
    last_error = ""
    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            last_error = str(e)
            continue
    raise RuntimeError(last_error)

# కేవలం 2 సెకన్లలో బంగారం & వెండి ధరలు తెచ్చే ఫంక్షన్
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

# Parallel స్కానింగ్‌తో 3 సెకన్లలో పూర్తి మార్కెట్ రిపోర్ట్
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
        stock_lines = "• ప్రస్తుతం అన్ని ప్రధాన స్టాక్స్ కన్సాలిడేషన్‌లో ఉన్నాయి.\n"

    return (
        "📈 *డైలీ మార్కెట్ & సేఫ్ స్టాక్స్ నివేదిక*\n\n"
        f"{bullion_block}\n\n"
        "🛡️ *లాంగ్-టర్మ్ సేఫ్టీ వాచ్‌లిస్ట్ (200-DMA పైన ఉన్నవి):*\n"
        f"{stock_lines}\n"
        "💡 _Zerodha లాంగ్-టర్మ్ సేఫ్టీ ఫిల్టర్ ఆధారంగా చూపబడినవి._"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "నమస్కారం నజీర్ గారు! మీ *కోదాడ AI ప్రొడక్షన్ & మార్కెట్ అసిస్టెంట్* సిద్ధంగా ఉంది.\n\n"
        "• `/gold` — బంగారం & వెండి ధరలు (2 సెకన్లలో!)\n"
        "• `/market` — బెస్ట్ సేఫ్ స్టాక్స్ + గోల్డ్ & సిల్వర్ పూర్తి రిపోర్ట్\n"
        "• `/stock <సింబల్>` — ఏదైనా NSE స్టాక్ విశ్లేషణ (ఉదా: `/stock TCS`)\n"
        "• `/yt <టాపిక్>` — ASN TOONS స్క్రిప్ట్, AI ఇమేజ్ ప్రాంప్ట్‌లు & తెలుగు MP3 ఆడియో"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

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
        await update.message.reply_text("ఉదాహరణకు ఇలా పంపండి: `/stock RELIANCE`", parse_mode="Markdown")
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
        await update.message.reply_text("ఉదాహరణ: `/yt కొంటె కామయ్య పిసినారితనం కామెడీ కథ`", parse_mode="Markdown")
        return

    topic = " ".join(context.args)
    await update.message.reply_text(f"🎬 *'{topic}'* కోసం స్క్రిప్ట్, ప్రాంప్ట్‌లు & ఆడియో సిద్ధం చేస్తున్నాను...", parse_mode="Markdown")

    prompt = (
        f"You are an expert Telugu YouTube content creator for 'ASN TOONS' (2D cartoon moral comedy stories & motivational videos). "
        f"Create a complete YouTube video package for: '{topic}'.\n\n"
        f"Structure:\n"
        f"1. CATCHY TELUGU TITLES (3 options) & THUMBNAIL TEXT\n"
        f"2. SCENE-BY-SCENE STORYBOARD & AI IMAGE PROMPTS (4-5 scenes: Telugu narration + detailed English 2D cartoon prompt for Leonardo/Ideogram)\n"
        f"3. CLEAN VOICEOVER SCRIPT ONLY (Pure Telugu spoken dialogues only, no scene numbers, brackets, or English words)."
    )

    try:
        full_output = await asyncio.to_thread(ask_gemini, prompt)
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
                    caption="🎙️ మీ YouTube వీడియో తెలుగు వాయిస్ ఓవర్ (MP3) సిద్ధం!"
                )
            if os.path.exists(audio_path):
                os.remove(audio_path)
    except Exception as e:
        await update.message.reply_text(f"కంటెంట్ తయారీలో లోపం: {e}")

# సాధారణ మెసేజ్‌లో gold/silver/stocks అడిగినా నేరుగా లైవ్ డేటా ఇచ్చే స్మార్ట్ హ్యాండ్లర్
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
        reply_text = await asyncio.to_thread(ask_gemini, user_text)
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
    app.add_handler(CommandHandler("gold", gold))
    app.add_handler(CommandHandler("silver", gold))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("beststocks", market))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("yt", youtube_creator))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    ist = pytz.timezone("Asia/Kolkata")
    scheduler = BackgroundScheduler(timezone=ist)
    scheduler.add_job(scheduled_morning_alert, "cron", hour=9, minute=0, args=[app, loop])
    scheduler.start()

    print("Kodad AI Production & Stock Agent is running fast...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
