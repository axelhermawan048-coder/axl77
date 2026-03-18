import os
from pyrogram import Client, filters

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION_STRING")

if not API_ID or not API_HASH or not SESSION:
    raise ValueError("API_ID, API_HASH, atau SESSION_STRING belum diisi!")

app = Client(SESSION, api_id=API_ID, api_hash=API_HASH)

@app.on_message(filters.private & filters.text)
async def echo(client, message):
    await message.reply_text(f"Kamu bilang: {message.text}")

print("Userbot Pyrogram jalan...")

app.run()
