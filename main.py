import os
import yfinance as yf
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "నమస్కారం పప్పా! 🙏\n\n"
        "నేను మీ పర్సనల్ AI అసిస్టెంట్‌ని. మీరు షాపులో ఉన్నా, బయట ఉన్నా మీకు కావాల్సిన పనులను చూసుకుంటాను:\n"
        "• స్టాక్ మార్కెట్ విశ్లేషణ (NSE/BSE లైవ్ రేట్లు, ట్రెండ్స్)\n"
        "• యూట్యూబ్ వీడియో ఐడియాలు & పూర్తి స్క్రిప్ట్స్\n"
        "• సాధారణ ప్రశ్నలు, లెక్కలు మరియు పనులు\n\n"
        "మీరు ఏ పని చేయమంటారో తెలుగులోనే మెసేజ్ చేయండి!"
    )
    await update.message.reply_text(welcome_text)

def get_stock_data(query: str):
    symbols = {"RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "INFY": "INFY.NS", "HDFCBANK": "HDFCBANK.NS", "NIFTY": "^NSEI"}
    query_upper = query.upper()
    found_info = ""
    for name, sym in symbols.items():
        if name in query_upper:
            try:
                ticker = yf.Ticker(sym)
                info = ticker.fast_info
                last_price = info.last_price
                found_info += f"\n[{name} ప్రస్తుత ధర: ₹{last_price:.2f}]"
            except Exception:
                pass
    return found_info

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    stock_context = get_stock_data(user_text)

    system_instruction = (
        "మీరు యూజర్ కు అత్యంత ఆప్తుడైన పర్సనల్ AI అసిస్టెంట్. "
        "యూజర్‌ను ఎల్లప్పుడూ గౌరవంగా, ఆప్యాయంగా 'పప్పా' అని సంబోధిస్తూ మాట్లాడాలి. "
        "అన్ని సమాధానాలు స్పష్టమైన, సరళమైన మరియు సహజమైన తెలుగు భాషలోనే ఉండాలి. "
        "స్టాక్ మార్కెట్ విశ్లేషణ, యూట్యూబ్ కంటెంట్ ఐడియాలు, స్టోరీ స్క్రిప్టింగ్, వ్యాపార సలహాలు "
        "అడిగినప్పుడు పూర్తి విశ్లేషణతో చక్కని సమాధానం ఇవ్వండి."
    )

    prompt = f"సిస్టమ్ సూచన: {system_instruction}\n"
    if stock_context:
        prompt += f"లైవ్ మార్కెట్ డేటా: {stock_context}\n"
    prompt += f"యూజర్ అడిగిన ప్రశ్న: {user_text}"

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        reply = response.text
    except Exception as e:
        reply = f"క్షమించండి పప్పా, సమాధానం సిద్ధం చేయడంలో చిన్న లోపం ఎదురైంది: {e}"

    await update.message.reply_text(reply)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("AI Master Agent is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
