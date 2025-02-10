import os
import requests
from dotenv import load_dotenv

load_dotenv() 

TOKEN = os.getenv('TELEGRAM_BOT_ID')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')


MESSAGE = "Method"

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
data = {"chat_id": CHAT_ID, "text": MESSAGE}

response = requests.post(url, data=data)
print(response.json())  # Check the response from Telegram
