import os
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv() 

def enviar_alerta_telegram(mensaje):
    telegram_bot_token = os.getenv('TELEGRAM_BOT_ID')
    CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    chat_ids = CHAT_ID.split(",") 
    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    
    for id in chat_ids:
        payload = {'chat_id': id, 'text': mensaje}
        requests.post(url, data=payload)
    #logger.info("Mensajes a telegram enviados")

if __name__ == "__main__":
    enviar_alerta_telegram("Hola")