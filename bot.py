#test line
import os
import json
import logging
from datetime import time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from openai import OpenAI
from dotenv import load_dotenv


# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== CONFIG ==================
TOPIC_FILE = "topic_store.json"
SUBSCRIBERS_FILE = "subscribers.json"
TIMEZONE = pytz.timezone('Asia/Kolkata')


load_dotenv()
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')



# Create OpenRouter client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# ================== UTILS ==================
def load_topics():
    """Load user topics from file safely."""
    try:
        with open(TOPIC_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except FileNotFoundError:
        return {}

def save_topics(topics):
    """Save user topics to file."""
    with open(TOPIC_FILE, "w") as f:
        json.dump(topics, f)

def generate_question(topic):
    """Use OpenRouter to generate a quiz question with strict format."""
    prompt = f"""Generate a multiple-choice question about {topic}. 

IMPORTANT: Follow this EXACT format (no extra text, no markdown, no additional formatting):

Question: [Your question here]
A) [Option A]
B) [Option B] 
C) [Option C]
D) [Option D]
Correct Answer: [A/B/C/D]
Explanation: [Brief explanation why this answer is correct]

Make sure:
- Question is clear and specific about {topic}
- All 4 options are plausible
- Only one option is clearly correct
- Explanation is concise but informative
- Use exactly "A)", "B)", "C)", "D)" format for options
- Use exactly "Correct Answer: X" format"""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error generating question: {str(e)}"

def parse_question(question_text):
    """Parse the generated question to extract components."""
    try:
        lines = question_text.split('\n')
        question = ""
        options = {}
        correct_answer = ""
        explanation = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith("Question:"):
                question = line.replace("Question:", "").strip()
            elif line.startswith("A)"):
                options["A"] = line.replace("A)", "").strip()
            elif line.startswith("B)"):
                options["B"] = line.replace("B)", "").strip()
            elif line.startswith("C)"):
                options["C"] = line.replace("C)", "").strip()
            elif line.startswith("D)"):
                options["D"] = line.replace("D)", "").strip()
            elif line.startswith("Correct Answer:"):
                correct_answer = line.replace("Correct Answer:", "").strip()
            elif line.startswith("Explanation:"):
                explanation = line.replace("Explanation:", "").strip()
        
        return {
            "question": question,
            "options": options,
            "correct_answer": correct_answer,
            "explanation": explanation
        }
    except Exception as e:
        return None

def generate_detailed_explanation(topic, question, correct_option, explanation):
    """Generate detailed explanation with real-world examples."""
    prompt = f"""Topic: {topic}
Question: {question}
Correct Answer: {correct_option}
Basic Explanation: {explanation}

Provide a detailed explanation that includes:
1. Why this answer is correct
2. Real-world applications and use cases
3. Common mistakes people make with this concept
4. Practical examples from actual projects

Keep it concise but informative (max 300 words)."""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Basic explanation: {explanation}"

# ================== TELEGRAM HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎓 Welcome to the Quiz Bot!\n\n"
        "Commands:\n"
        "• /quiz - Start a quiz\n"
        "• /modify - Change your topic\n"
        "• /mytopic - See current topic"
    )

async def modify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Enter the topic you want to learn:\n"
        "(e.g., Python, JavaScript, Machine Learning, Data Structures, etc.)"
    )
    context.user_data["awaiting_topic"] = True

async def mytopic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    topics = load_topics()
    topic = topics.get(user_id, "C++")
    await update.message.reply_text(f"📚 Your current topic: {topic}")

async def handle_topic_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle topic setting when user sends a message."""
    if context.user_data.get("awaiting_topic"):
        user_id = str(update.message.from_user.id)
        topic = update.message.text.strip()
        
        # Basic validation
        if len(topic) < 2 or len(topic) > 100:
            await update.message.reply_text("❌ Topic should be between 2-100 characters. Try again:")
            return
            
        topics = load_topics()
        topics[user_id] = topic
        save_topics(topics)
        context.user_data["awaiting_topic"] = False
        
        await update.message.reply_text(
            f"✅ Topic saved successfully!\n"
            f"📚 Your topic: {topic}\n\n"
            f"Use /quiz to start practicing!"
        )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    topics = load_topics()
    topic = topics.get(user_id, "C++")

    await update.message.reply_text("🤔 Generating question, please wait...")
    
    question_text = generate_question(topic)
    parsed = parse_question(question_text)
    
    if not parsed or not all([parsed["question"], parsed["options"], parsed["correct_answer"]]):
        await update.message.reply_text(
            "❌ Error generating question. Please try again with /quiz"
        )
        return
    
    # Store question data for answer checking
    context.user_data["current_quiz"] = parsed
    context.user_data["topic"] = topic
    
    # Format question message
    question_msg = f"❓ Question about {topic}:\n\n"
    question_msg += f"{parsed['question']}\n\n"
    
    for letter, option in parsed["options"].items():
        question_msg += f"{letter}) {option}\n"
    
    # Create inline keyboard
    keyboard = [
        [InlineKeyboardButton("A", callback_data="answer_A"),
         InlineKeyboardButton("B", callback_data="answer_B")],
        [InlineKeyboardButton("C", callback_data="answer_C"),
         InlineKeyboardButton("D", callback_data="answer_D")],
        [InlineKeyboardButton("🤷‍♂️ No Idea / Explain", callback_data="explain")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(question_msg, reply_markup=reply_markup)

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    current_quiz = context.user_data.get("current_quiz")
    topic = context.user_data.get("topic", "Unknown")
    
    if not current_quiz:
        await query.message.reply_text("❌ No active quiz found. Use /quiz to start a new one.")
        return
    
    if query.data == "explain":
        # Generate detailed explanation
        explanation = generate_detailed_explanation(
            topic,
            current_quiz["question"],
            f"{current_quiz['correct_answer']}) {current_quiz['options'][current_quiz['correct_answer']]}",
            current_quiz["explanation"]
        )
        
        response = f"💡 Detailed Explanation:\n\n"
        response += f"Correct Answer: {current_quiz['correct_answer']}) {current_quiz['options'][current_quiz['correct_answer']]}\n\n"
        response += f"{explanation}\n\n"
        response += "Use /quiz for another question! 🎯"
        
        # Send as NEW message, don't edit the question
        await query.message.reply_text(response)
        
    else:
        # Handle answer selection
        selected = query.data.replace("answer_", "")
        correct = current_quiz["correct_answer"]
        
        if selected == correct:
            response = f"🎉 Correct! \n\n"
            response += f"✅ {selected}) {current_quiz['options'][selected]}\n\n"
            response += f"💭 {current_quiz['explanation']}\n\n"
            response += "Great job! Use /quiz for another question! 🎯"
        else:
            response = f"❌ Incorrect \n\n"
            response += f"Your answer: {selected}) {current_quiz['options'][selected]}\n"
            response += f"Correct answer: {correct}) {current_quiz['options'][correct]}\n\n"
            response += f"💭 {current_quiz['explanation']}\n\n"
            response += "Don't worry, keep practicing! Use /quiz for another question! 💪"
        
        # Send as NEW message, don't edit the question
        await query.message.reply_text(response)
    
    # Clear quiz data
    context.user_data.pop("current_quiz", None)

def load_subscribers():
    """Load subscriber list from file."""
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except FileNotFoundError:
        return []

def save_subscribers(subscribers):
    """Save subscriber list to file."""
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subscribers, f, indent=2)

async def subscribe_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe user to daily quizzes."""
    user_id = update.message.from_user.id
    subscribers = load_subscribers()
    
    if user_id not in subscribers:
        subscribers.append(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text(
            "✅ **Subscribed to daily quizzes!**\n\n"
            "🕘 You'll receive a quiz every day at 9:30 AM (IST)\n"
            "Use /unsubscribe to stop daily quizzes",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("ℹ️ You're already subscribed to daily quizzes!")

async def unsubscribe_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe user from daily quizzes."""
    user_id = update.message.from_user.id
    subscribers = load_subscribers()
    
    if user_id in subscribers:
        subscribers.remove(user_id)
        save_subscribers(subscribers)
        await update.message.reply_text("❌ **Unsubscribed from daily quizzes!**", parse_mode='Markdown')
    else:
        await update.message.reply_text("ℹ️ You weren't subscribed to daily quizzes.")

async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get user's Telegram ID."""
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "No username"
    first_name = update.message.from_user.first_name or "No name"
    
    await update.message.reply_text(
        f"👤 **Your Account Info:**\n\n"
        f"🆔 **User ID:** `{user_id}`\n"
        f"👤 **Name:** {first_name}\n"
        f"📝 **Username:** @{username}\n\n"
        f"Copy the User ID number above ☝️",
        parse_mode='Markdown'
    )

async def send_daily_quiz(context: ContextTypes.DEFAULT_TYPE):
    """Send daily quiz to subscribed users."""
    try:
        subscribers = load_subscribers()
        topics = load_topics()
        
        logger.info(f"Sending daily quiz to {len(subscribers)} subscribers")
        
        if not subscribers:
            logger.info("No subscribers found for daily quiz")
            return
        
        for user_id in subscribers:
            try:
                topic = topics.get(str(user_id), "C++")
                
                # Generate question
                question_text = generate_question(topic)
                parsed = parse_question(question_text)
                
                if not parsed or not all([parsed["question"], parsed["options"], parsed["correct_answer"]]):
                    logger.error(f"Failed to generate valid question for user {user_id}")
                    continue
                
                # Format message
                message = f"🌅 **Good Morning! Daily Quiz Time!** 🌅\n\n"
                message += f"❓ **Question about {topic}:**\n\n"
                message += f"{parsed['question']}\n\n"
                
                for letter, option in parsed["options"].items():
                    message += f"{letter}) {option}\n"
                
                message += f"\nThink you know the answer? 🤔"
                
                # Create keyboard
                keyboard = [
                    [InlineKeyboardButton("A", callback_data="answer_A"),
                     InlineKeyboardButton("B", callback_data="answer_B")],
                    [InlineKeyboardButton("C", callback_data="answer_C"),
                     InlineKeyboardButton("D", callback_data="answer_D")],
                    [InlineKeyboardButton("🤷‍♂️ No Idea / Explain", callback_data="explain")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                logger.info(f"Daily quiz sent successfully to user {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to send daily quiz to user {user_id}: {e}")
                # Remove user from subscribers if they blocked the bot
                if "bot was blocked" in str(e).lower():
                    subscribers.remove(user_id)
                    save_subscribers(subscribers)
                    logger.info(f"Removed user {user_id} from subscribers (bot blocked)")
                
    except Exception as e:
        logger.error(f"Error in daily quiz job: {e}")

# ================== MAIN BOT ==================
def main():
    """Run the bot using the simpler run_polling method."""
    try:
        print("🤖 Creating Quiz Bot application...")
        
        # Create the Application
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        
        print("✅ Application created successfully!")
        
        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("modify", modify))
        app.add_handler(CommandHandler("mytopic", mytopic))
        app.add_handler(CommandHandler("quiz", quiz))
        app.add_handler(CommandHandler("subscribe", subscribe_daily))
        app.add_handler(CommandHandler("unsubscribe", unsubscribe_daily))
        app.add_handler(CommandHandler("myid", get_my_id))
        app.add_handler(CallbackQueryHandler(handle_answer))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic_message))
        
        # Set up daily job for 9:30 AM IST
        job_queue = app.job_queue
        job_queue.run_daily(
            send_daily_quiz,
            time=time(hour=9, minute=30, tzinfo=TIMEZONE),
            name="daily_quiz"
        )
        
        # Keep alive job (ping every 10 minutes to prevent sleeping)
        async def keep_alive(context):
            logger.info("Keep alive ping")
        
        job_queue.run_repeating(
            keep_alive,
            interval=600,  # 10 minutes
            name="keep_alive"
        )
        
        print("📝 Handlers registered successfully!")
        print("⏰ Daily quiz scheduled for 9:30 AM IST")
        print("🚀 Starting the bot...")
        print("Press Ctrl+C to stop")
        
        # Run the bot
        app.run_polling(drop_pending_updates=True)
        
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()