import threading
from flask import Flask
import os
import bot  # Ensure this only defines the bot, rather than blocking the script

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_bot():
    # If your bot blocks execution, start it here
    # Example: bot.client.run(os.getenv('TOKEN'))
    pass

if __name__ == "__main__":
    # 1. Run the bot in a separate background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # 2. Run Flask on the main thread using Render's dynamic port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
