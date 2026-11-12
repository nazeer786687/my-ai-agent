import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yfinance as yf
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Render & UptimeRobot కోసం Dummy HTTP Server (GET & HEAD సపోర్ట్‌తో)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Kodad AI Agent is Alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # అనవసరమైన లాగ్స్ రాకుండా ఆపుతుంది

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Official Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY)

# Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "నమస్కారం! నేను మన కోదాడ AI అసిస్టెంట్ ఏజెంట్‌ని.\n\n"
        "నేను మీకు ఈ క్రింది పనులలో సహాయం చేయగలను:\n"
        "1. స్టాక్ మార్కెట్ వివరాలు (ఉదా: /stock TATAMOTORS)\n"
        "2. కంటెంట్ క్రియేషన్, వ్యాపార ఆలోచనలు & స్క్రిప్ట్స్\n"
        "3. సాధారణ ప్రశ్నలు & సలహాలు\n\n"
        "మీకు కావాల్సిన సందేహాన్ని నేరుగా టైప్ చేసి పంపండి!"
    )
    await update.message.reply_text(welcome_msg)

# Stock Market Command
async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("దయచేసి స్టాక్ సింబల్ నమోదు చేయండి. ఉదాహరణకు: /stock RELIANCE")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"{symbol} వివరాలు సేకరిస్తున్నాను...")

    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        data = ticker.history(period="1d")
        
        if not data.empty:
            price = round(data['Close'].iloc[-1], 2)
            high = round(data['High'].iloc[-1], 2)
            low = round(data['Low'].iloc[-1], 2)
            
            res = (
                f"📊 *స్టాక్ మార్కెట్ నివేదిక ({symbol})*\n\n"
                f"• ప్రస్తుత ధర (CMP): ₹{price}\n"
                f"• గరిష్ట ధర (High): ₹{high}\n"
                f"• కనిష్ట ధర (Low): ₹{low}\n"
                f"• ఎక్స్ఛేంజ్: NSE India"
            )
            await update.message.reply_text(res, parse_mode="Markdown")
        else:
            await update.message.reply_text("క్షమించండి, ఆ స్టాక్ వివరాలు లభించలేదు. సింబల్ సరిగ్గా ఉందో లేదో చూడండి.")
    except Exception as e:
        await update.message.reply_text(f"సమాచారం పొందడంలో లోపం తలెత్తింది: {e}")

# Gemini AI Response
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=user_text,
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        await update.message.reply_text(f"AI స్పందించడంలో లోపం: {e}")

def main():
    # వెబ్ పోర్ట్‌ను బ్యాక్‌గ్రౌండ్‌లో స్టార్ట్ చేస్తుంది
    threading.Thread(target=run_health_server, daemon=True).start()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stock", stock))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("AI Master Agent is running successfully...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
