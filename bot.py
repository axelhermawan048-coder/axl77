import os
import asyncio
from datetime import datetime
from pyrogram import Client, filters
import zipfile

ACCOUNTS = [
    {
        "name": "Forwarder",
        "session": os.environ.get("SESSION_1"),
        "api_id": int(os.environ.get("API_ID1", 0)),
        "api_hash": os.environ.get("API_HASH1"),
        "target_chat": os.environ.get("TARGET_CHAT")
    },
    {
        "name": "Exporter",
        "session": os.environ.get("SESSION_2"),
        "api_id": int(os.environ.get("API_ID2", 0)),
        "api_hash": os.environ.get("API_HASH2")
    }
]

# Validasi credentials
for acc in ACCOUNTS:
    if not all([acc.get("session"), acc.get("api_id"), acc.get("api_hash")]):
        raise ValueError(f"Creds akun {acc['name']} tidak lengkap!")

# ==========================
# QUEUE GLOBAL
# ==========================
queue = asyncio.Queue()
MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500 MB
FORWARD_RETRIES = 5

# ==========================
# FORWARDER CLIENT
# ==========================
async def forwarder_task(account):
    try:
        app = Client(
            f"{account['name']}_session",
            api_id=account["api_id"],
            api_hash=account["api_hash"],
            session_string=account["session"],
            in_memory=True
        )
        await app.start()
        me = await app.get_me()
        print(f"Forwarder pakai akun: {me.id} | {me.first_name}")
        print(f"{account['name']} Forwarder siap")

        @app.on_message(filters.private)
        async def forward_message(client, message):
            for attempt in range(FORWARD_RETRIES):
                try:
                    forwarded_msg = await message.forward(account["target_chat"])
                    print(f"Forwarded message {forwarded_msg.id}")
                    await queue.put(forwarded_msg)
                    break
                except Exception as e:
                    print(f"⚠️ Forward gagal (attempt {attempt+1}/{FORWARD_RETRIES}): {e}")
                    await asyncio.sleep(5)

        await asyncio.Event().wait()
    except Exception as e:
        print(f"❌ Forwarder crash: {e}")
        await asyncio.sleep(10)
        await forwarder_task(account)

# ==========================
# EXPORTER CLIENT
# ==========================

async def exporter_task(account):
    try:
        app = Client(
            f"{account['name']}_session",
            api_id=account["api_id"],
            api_hash=account["api_hash"],
            session_string=account["session"],
            in_memory=True
        )
        await app.start()
        me = await app.get_me()
        print(f"Exporter pakai akun: {me.id} | {me.first_name}")

        async def process_queue():
            while True:
                batch_files = []
                batch_size = 0

                while batch_size < MAX_BATCH_SIZE:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=10)
                    except asyncio.TimeoutError:
                        break

                    try:
                        if msg.media:
                            file_path = await msg.download()
                        else:
                            file_path = f"{datetime.now().strftime('%H%M%S_%f')}_text.txt"
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(msg.text or "")
                    except Exception as e:
                        print(f"⚠️ Gagal download pesan: {e}")
                        continue

                    batch_size += os.path.getsize(file_path)
                    batch_files.append(file_path)

                if batch_files:
                    # Buat ZIP per batch
                    zip_name = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.zip"
                    with zipfile.ZipFile(zip_name, 'w') as zipf:
                        for f in batch_files:
                            zipf.write(f, os.path.basename(f))
                            os.remove(f)

                    # Kirim ke Saved Messages
                    for attempt in range(FORWARD_RETRIES):
                        try:
                            await app.send_document("me", zip_name)
                            print(f"✅ Batch dikirim ke Saved Messages: {zip_name}")
                            os.remove(zip_name)
                            break
                        except Exception as e:
                            print(f"⚠️ Gagal kirim ZIP (attempt {attempt+1}/{FORWARD_RETRIES}): {e}")
                            await asyncio.sleep(5)

                await asyncio.sleep(21600)  # jeda 30 menit per batch

        await process_queue()
    except Exception as e:
        print(f"❌ Exporter crash: {e}")
        await asyncio.sleep(10)
        await exporter_task(account)
# ==========================
# MAIN
# ==========================
async def main():
    await asyncio.gather(
        forwarder_task(ACCOUNTS[0]),
        exporter_task(ACCOUNTS[1]),
        return_exceptions=True
    )

if __name__ == "__main__":
    print("Menjalankan Exporter Telegram → ZIP → Saved Messages setiap batch maksimal 500 MB")
    asyncio.run(main())
