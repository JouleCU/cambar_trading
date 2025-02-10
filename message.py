import os
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv() 

def enviar_alerta_telegram(mensaje):
    telegram_bot_token = os.getenv('TELEGRAM_BOT_ID')
    CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')


    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': mensaje}
    requests.post(url, data=payload)
    logger.info("Mensaje a telegram enviado")

if __name__ == "__main__":
    enviar_alerta_telegram("Hola")