import os
from pyrogram import Client, filters

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH"))
SESSION = os.getenv("SESSION_STRING")

# Pakai nama file session pendek, misal "userbot"
app = Client(
    "userbot77",           # <--- ini nama file .session, pendek saja
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION  # <--- tetap session string panjang
)

@app.on_message(filters.private & filters.text)
async def echo(client, message):
    await message.reply_text(f"Kamu bilang: {message.text}")

print("Userbot Pyrogram jalan...")

app.run()
