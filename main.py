import threading
from flask import Flask
import bot  # This imports and runs your bot.py file

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=10000)

# Run the web server in a separate thread so it doesn't block the bot
threading.Thread(target=run).start()
