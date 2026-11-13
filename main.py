import os
import asyncio
import threading
import pytz
import yfinance as yf
from gtts import gTTS
from http.server import HTTPServer, BaseHTTPRequestHandler
from apscheduler.schedulers.background import BackgroundScheduler
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Render & UptimeRobot కోసం Health Check Server
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

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_CHAT_ID = os.getenv("MY_CHAT_ID")

client = genai.Client(api_key=GEMINI_API_KEY)

# 503 ఎర్రర్ రాకుండా Auto-Fallback AI ఫంక్షన్
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

# లైవ్ స్టాక్స్ & గోల్డ్/సిల్వర్ రిపోర్ట్ తయారీ (Zerodha Long-Term Safety Focus)
def build_market_report() -> str:
    # 1. Gold & Silver (International Futures & USD-INR ఆధారంగా అంచనా + MCX/ETF)
    gold_text = "డేటా లభ్యం కాలేదు"
    silver_text = "డేటా లభ్యం కాలేదు"
    try:
        usdinr = yf.Ticker("INR=X").history(period="1d")["Close"].iloc[-1]
        gold_oz = yf.Ticker("GC=F").history(period="1d")["Close"].iloc[-1]
        silver_oz = yf.Ticker("SI=F").history(period="1d")["Close"].iloc[-1]
        # 1 Troy Ounce = 31.1035 grams
        gold_10g = round((gold_oz / 31.1035) * 10 * usdinr * 1.06, 0)  # 6% import duty/GST approx
        silver_1kg = round((silver_oz / 31.1035) * 1000 * usdinr * 1.06, 0)
        gold_text = f"₹{int(gold_10g):,} / 10 గ్రాములు (24K అంచనా)"
        silver_text = f"₹{int(silver_1kg):,} / 1 కిలో (అంచనా)"
    except Exception:
        pass

    # 2. బలమైన లార్జ్-క్యాప్ NSE స్టాక్స్ స్కాన్ (Capital Safety కోసం 200-DMA పైన ఉన్నవి)
    safe_watchlist = [
        "TCS", "INFY", "HDFCBANK", "ICICIBANK", "RELIANCE",
        "ITC", "LT", "SUNPHARMA", "BHARTIARTL", "TITAN", "SBIN", "HINDUNILVR"
    ]
    picks = []
    for sym in safe_watchlist:
        try:
            hist = yf.Ticker(f"{sym}.NS").history(period="1y")
            if len(hist) >= 200:
                cmp = round(hist["Close"].iloc[-1], 2)
                prev = round(hist["Close"].iloc[-2], 2)
                dma200 = round(hist["Close"].tail(200).mean(), 2)
                dma50 = round(hist["Close"].tail(50).mean(), 2)
                chg_pct = round(((cmp - prev) / prev) * 100, 2)
                # లాంగ్-టర్మ్ సేఫ్టీ: ధర 200-DMA కంటే పైన ఉండి, ఓవర్-హీట్ అవ్వనివి
                if cmp > dma200 and cmp <= dma50 * 1.08:
                    picks.append((chg_pct, sym, cmp, dma200))
        except Exception:
            continue

    picks.sort(reverse=True)
    top_picks = picks[:5]

    stock_lines = ""
    if top_picks:
        for chg, sym, cmp, dma200 in top_picks:
            sign = "+" if chg >= 0 else ""
            stock_lines += f"• *{sym}*: ₹{cmp} ({sign}{chg}%) | 200-DMA: ₹{dma200}\n"
    else:
        stock_lines = "• ప్రస్తుతం అన్ని ప్రధాన స్టాక్స్ కన్సాలిడేషన్‌లో ఉన్నాయి.\n"

    report = (
        "📈 *డైలీ మార్కెట్ & సేఫ్ స్టాక్స్ నివేదిక*\n\n"
        f"🟡 *బంగారం (Gold):* {gold_text}\n"
        f"⚪ *వెండి (Silver):* {silver_text}\n\n"
        "🛡️ *లాంగ్-టర్మ్ సేఫ్టీ వాచ్‌లిస్ట్ (200-DMA పైన ఉన్న బలమైన స్టాక్స్):*\n"
        f"{stock_lines}\n"
        "💡 _గమనిక: ఇవి Zerodha లాంగ్-టర్మ్ ఇన్వెస్ట్‌మెంట్ కోసం టెక్నికల్ సేఫ్టీ ఫిల్టర్ ఆధారంగా చూపబడినవి. కొనుగోలుకు ముందు ఫండమెంటల్స్ పరిశీలించండి._"
    )
    return report

# /start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "నమస్కారం నజీర్ గారు! మీ *కోదాడ AI ప్రొడక్షన్ & మార్కెట్ అసిస్టెంట్* సిద్ధంగా ఉంది.\n\n"
        "🎬 *YouTube ఆటో-కంటెంట్ ఫ్యాక్టరీ:*\n"
        "• `/yt <టాపిక్>` — తెలుగు స్క్రిప్ట్, AI ఇమేజ్ ప్రాంప్ట్‌లు & వాయిస్ ఓవర్ MP3 ఆడియో\n"
        "  _(ఉదా: /yt కోదాడలో అతిపిసినారి కామయ్య కథ)_\n\n"
        "📊 *స్టాక్ మార్కెట్ & బులియన్:*\n"
        "• `/market` — ఈరోజు బెస్ట్ సేఫ్ స్టాక్స్, బంగారం & వెండి ధరలు\n"
        "• `/stock <సింబల్>` — ఏదైనా NSE స్టాక్ పూర్తి విశ్లేషణ (ఉదా: `/stock TCS`)\n"
        "• ప్రతిరోజూ ఉదయం 9:00 AM కి ఆటోమేటిక్ మార్కెట్ అలర్ట్ వస్తుంది!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

# /market Command (Best Stocks + Gold & Silver)
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ లైవ్ స్టాక్స్, బంగారం & వెండి ధరలు సేకరిస్తున్నాను...")
    try:
        report = await asyncio.to_thread(build_market_report)
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"మార్కెట్ డేటా లోపం: {e}")

# /stock <SYMBOL> Command
async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("ఉదాహరణకు ఇలా పంపండి: `/stock RELIANCE`", parse_mode="Markdown")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 {symbol} పూర్తి విశ్లేషణ చేస్తున్నాను...")

    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(period="1y")
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
            await update.message.reply_text("ఆ స్టాక్ సింబల్ దొరకలేదు. NSE సింబల్ సరిగ్గా ఇవ్వండి.")
    except Exception as e:
        await update.message.reply_text(f"లోపం: {e}")

# /yt <TOPIC> Command (Script + AI Prompts + Telugu MP3 Voiceover)
async def youtube_creator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "మీకు ఏ టాపిక్ మీద YouTube వీడియో కావాలో రాయండి.\n"
            "ఉదాహరణ: `/yt కొంటె కామయ్య పిసినారితనం కామెడీ కథ`",
            parse_mode="Markdown"
        )
        return

    topic = " ".join(context.args)
    await update.message.reply_text(f"🎬 *'{topic}'* కోసం స్క్రిప్ట్, విజువల్ ప్రాంప్ట్‌లు & తెలుగు వాయిస్ ఓవర్ తయారు చేస్తున్నాను...", parse_mode="Markdown")

    prompt = (
        f"You are an expert Telugu YouTube content creator for the channel 'ASN TOONS' (famous for 2D cartoon moral comedy stories and engaging motivational/informative videos). "
        f"Create a complete YouTube video production package for the topic: '{topic}'.\n\n"
        f"Provide the output strictly in this structure:\n"
        f"1. CATCHY TELUGU TITLES (3 options) & THUMBNAIL TEXT\n"
        f"2. SCENE-BY-SCENE STORYBOARD & AI IMAGE PROMPTS (4 to 5 scenes: write the Telugu narration for each scene, followed by a detailed English 2D cartoon/illustration image prompt for Leonardo/Ideogram)\n"
        f"3. CLEAN VOICEOVER SCRIPT ONLY (Write ONLY the pure Telugu spoken dialogues/narration without any scene numbers, brackets, or English words so it can be directly converted to audio)."
    )

    try:
        full_output = await asyncio.to_thread(ask_gemini, prompt)

        # టెలిగ్రామ్ 4096 అక్షరాల పరిమితి దాటకుండా ముక్కలుగా పంపడం
        for i in range(0, len(full_output), 4000):
            await update.message.reply_text(full_output[i:i+4000])

        # వాయిస్ ఓవర్ ఆడియో (MP3) తయారీ
        vo_text = full_output
        if "3." in full_output:
            vo_text = full_output.split("3.")[-1]
        # ఆడియో కోసం శుభ్రమైన తెలుగు టెక్స్ట్ మాత్రమే ఉంచడం
        clean_vo = vo_text.replace("*", "").replace("#", "").strip()[:2500]

        if clean_vo:
            audio_path = f"yt_voice_{update.effective_chat.id}.mp3"
            tts = gTTS(text=clean_vo, lang="te", slow=False)
            await asyncio.to_thread(tts.save, audio_path)

            with open(audio_path, "rb") as audio_file:
                await update.message.reply_audio(
                    audio=audio_file,
                    title=f"ASN_TOONS_{topic[:20]}",
                    caption="🎙️ మీ YouTube వీడియో కోసం తెలుగు వాయిస్ ఓవర్ (MP3) సిద్ధంగా ఉంది!"
                )
            if os.path.exists(audio_path):
                os.remove(audio_path)

    except Exception as e:
        await update.message.reply_text(f"కంటెంట్ తయారీలో లోపం: {e}")

# సాధారణ చాట్ (Auto-Fallback AI తో)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    try:
        reply_text = await asyncio.to_thread(ask_gemini, user_text)
        for i in range(0, len(reply_text), 4000):
            await update.message.reply_text(reply_text[i:i+4000])
    except Exception as e:
        await update.message.reply_text(f"క్షమించండి, సర్వర్ ప్రస్తుతం చాలా బిజీగా ఉంది. ఒక్క నిమిషం తర్వాత మళ్లీ ప్రయత్నించండి. ({e})")

# ప్రతిరోజూ ఉదయం 9:00 AM IST కి ఆటోమేటిక్ స్టాక్ అలర్ట్
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
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("beststocks", market))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(CommandHandler("yt", youtube_creator))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ఉదయం 9:00 AM IST షెడ్యూలర్
    ist = pytz.timezone("Asia/Kolkata")
    scheduler = BackgroundScheduler(timezone=ist)
    scheduler.add_job(scheduled_morning_alert, "cron", hour=9, minute=0, args=[app, loop])
    scheduler.start()

    print("Kodad AI Production & Stock Agent is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
