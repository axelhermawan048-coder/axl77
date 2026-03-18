from pyrogram import Client
import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION_STRING")

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION)

with app:
    for dialog in app.get_dialogs():
        chat = dialog.chat
        if chat.type == "supergroup" and chat.title == "backup":
            print(f"{chat.title} | ID: {chat.id}")