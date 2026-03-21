import os
import asyncio
import json
import uuid
import logging
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.errors import FloodWait

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ==========================
# LOGGING
# ==========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==========================
# CONFIG TELEGRAM
# ==========================
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

for acc in ACCOUNTS:
    if not all([acc.get("session"), acc.get("api_id"), acc.get("api_hash")]):
        raise ValueError(f"Creds akun {acc['name']} tidak lengkap!")

# ==========================
# GOOGLE DRIVE
# ==========================
SCOPES = ['https://www.googleapis.com/auth/drive.file']
service_account_info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])

credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=SCOPES
)

drive_service = build('drive', 'v3', credentials=credentials)

# ==========================
# GLOBAL QUEUE
# ==========================
queue = asyncio.Queue(maxsize=1000)

MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500MB
UPLOAD_RETRIES = 5

# ==========================
# GOOGLE DRIVE HELPERS
# ==========================
async def create_daily_folder():
    today = datetime.now().strftime("%Y-%m-%d")

    loop = asyncio.get_event_loop()

    def _create():
        results = drive_service.files().list(
            q=f"name='{today}' and mimeType='application/vnd.google-apps.folder' and 'root' in parents",
            fields='files(id)'
        ).execute()

        files = results.get('files', [])
        if files:
            return files[0]['id']

        folder = drive_service.files().create(
            body={
                'name': today,
                'mimeType': 'application/vnd.google-apps.folder'
            },
            fields='id'
        ).execute()

        return folder['id']

    try:
        return await loop.run_in_executor(None, _create)
    except Exception as e:
        logging.error(f"Gagal create folder: {e}")
        return None


async def upload_to_drive(file_path, folder_id):
    loop = asyncio.get_event_loop()

    for attempt in range(UPLOAD_RETRIES):
        try:
            def _upload():
                media = MediaFileUpload(file_path, resumable=True)
                file = drive_service.files().create(
                    body={
                        'name': os.path.basename(file_path),
                        'parents': [folder_id]
                    },
                    media_body=media,
                    fields='id'
                ).execute()
                return file['id']

            file_id = await loop.run_in_executor(None, _upload)

            logging.info(f"Uploaded: {file_path} | ID: {file_id}")
            os.remove(file_path)
            return

        except Exception as e:
            logging.warning(f"Upload gagal ({attempt+1}): {e}")
            await asyncio.sleep(5)

    logging.error(f"Upload gagal permanen: {file_path}")

# ==========================
# FORWARDER
# ==========================
async def forwarder_task(account):
    while True:
        try:
            app = Client(
                f"{account['name']}",
                api_id=account["api_id"],
                api_hash=account["api_hash"],
                session_string=account["session"],
                in_memory=True
            )

            await app.start()
            logging.info("Forwarder started")

            @app.on_message(filters.private)
            async def handler(client, message):
                for attempt in range(5):
                    try:
                        forwarded = await message.forward(account["target_chat"])

                        await queue.put({
                            "chat_id": forwarded.chat.id,
                            "message_id": forwarded.id
                        })

                        logging.info(f"Forwarded: {forwarded.id}")
                        break

                    except FloodWait as e:
                        logging.warning(f"FloodWait {e.value}s")
                        await asyncio.sleep(e.value)

                    except Exception as e:
                        logging.warning(f"Forward gagal: {e}")
                        await asyncio.sleep(3)

            await asyncio.Event().wait()

        except Exception as e:
            logging.error(f"Forwarder crash: {e}")
            await asyncio.sleep(5)

# ==========================
# EXPORTER
# ==========================
async def exporter_task(account):
    while True:
        try:
            app = Client(
                f"{account['name']}",
                api_id=account["api_id"],
                api_hash=account["api_hash"],
                session_string=account["session"],
                in_memory=True
            )

            await app.start()
            logging.info("Exporter started")

            while True:
                batch = []
                batch_size = 0

                while batch_size < MAX_BATCH_SIZE:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=10)
                    except asyncio.TimeoutError:
                        break

                    try:
                        msg = await app.get_messages(item["chat_id"], item["message_id"])

                        if msg.media:
                            file_path = await msg.download()
                        else:
                            file_path = f"{uuid.uuid4()}.txt"
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(msg.text or "")

                        size = os.path.getsize(file_path)
                        batch.append(file_path)
                        batch_size += size

                        logging.info(f"Added to batch: {file_path}")

                    except Exception as e:
                        logging.warning(f"Download gagal: {e}")

                if batch:
                    logging.info(f"Upload batch: {len(batch)} file")

                    folder_id = await create_daily_folder()

                    if folder_id:
                        tasks = [upload_to_drive(f, folder_id) for f in batch]
                        await asyncio.gather(*tasks)

                await asyncio.sleep(5)

        except Exception as e:
            logging.error(f"Exporter crash: {e}")
            await asyncio.sleep(5)

# ==========================
# MAIN
# ==========================
async def main():
    await asyncio.gather(
        forwarder_task(ACCOUNTS[0]),
        exporter_task(ACCOUNTS[1])
    )

if __name__ == "__main__":
    logging.info("START BOT")
    asyncio.run(main())
