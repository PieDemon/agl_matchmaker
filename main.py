import threading
import os
from flask import Flask
import bot  # <--- This should only IMPORT the code, NOT run it!

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def start_bot_safely():
    # Call your bot's startup command INSIDE the background thread
    print("Starting bot in background thread...")
    bot.run_my_bot() 

if __name__ == "__main__":
    # 1. Start the bot on a background daemon thread
    bot_thread = threading.Thread(target=start_bot_safely, daemon=True)
    bot_thread.start()

    # 2. Start Flask instantly on the main thread
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting Flask on port {port}...")
    app.run(host='0.0.0.0', port=port)
