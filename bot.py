from pyrogram import Client, filters
import os
import asyncio

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH") 
SESSION = os.getenv("SESSION_STRING")

if not API_ID or not API_HASH or not SESSION:
    raise ValueError("ENV Variables API_ID, API_HASH, atau SESSION_STRING belum diisi!")

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION)

TARGET_CHAT = 7312531596  # ganti id pribadi
FORWARD_ENABLED = True
FORWARD_DELAY = 5  # jeda forwarding dalam detik

# Forward semua pesan pribadi + hapus pesan asli
@app.on_message(filters.private)
async def forward_private(client, message):
    global FORWARD_ENABLED
    if not FORWARD_ENABLED:
        return
    await asyncio.sleep(FORWARD_DELAY)  # delay sebelum forward
    await message.forward(TARGET_CHAT)   # forward ke grup
    await message.delete()               # hapus pesan asli di akun pribadi

# Command /pause dan /resume dari Saved Messages
@app.on_message(filters.chat("me") & filters.text)
async def pause_resume(client, message):
    global FORWARD_ENABLED
    text = message.text.lower()
    if text == "/pause":
        FORWARD_ENABLED = False
        await message.reply_text("✅ Forward bot paused!")
    elif text == "/resume":
        FORWARD_ENABLED = True
        await message.reply_text("✅ Forward bot resumed!")

print("✅ Userbot siap forward semua pesan pribadi + media dengan delay dan hapus pesan asli.")
print(f"⏱ Delay setiap forward: {FORWARD_DELAY} detik")
print("Gunakan /pause dan /resume dari Saved Messages untuk kontrol.")
app.run()
