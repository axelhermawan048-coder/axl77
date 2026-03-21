import os
import asyncio
from datetime import datetime
from pyrogram import Client, filters
import zipfile

queue = asyncio.Queue()
MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500 MB
FORWARD_RETRIES = 5

ACCOUNTS = [
    {
        "name": "Exporter",
        "session": os.environ.get("SESSION_2"),
        "api_id": int(os.environ.get("API_ID2", 0)),
        "api_hash": os.environ.get("API_HASH2")
    }
]

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

                await asyncio.sleep(1800)  # jeda 30 menit per batch

        await process_queue()
    except Exception as e:
        print(f"❌ Exporter crash: {e}")
        await asyncio.sleep(10)
        await exporter_task(account)

async def main():
    await asyncio.gather(
        exporter_task(ACCOUNTS[0]),
        return_exceptions=True
    )

if __name__ == "__main__":
    print("Menjalankan Exporter Telegram → ZIP → Saved Messages setiap batch maksimal 500 MB")
    asyncio.run(main())
