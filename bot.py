import os
import asyncio
from datetime import datetime
from pyrogram import Client, filters
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# ==========================
# Load env variables
# ==========================
load_dotenv()

# ==========================
# CONFIG AKUN TELEGRAM
# ==========================
ACCOUNTS = [
    {
        "name": "Forwarder",
        "session": os.getenv("SESSION_1"),
        "api_id": int(os.getenv("API_ID1", 0)),
        "api_hash": os.getenv("API_HASH1"),
        "target_chat": os.getenv("TARGET_CHAT")
    },
    {
        "name": "Exporter",
        "session": os.getenv("SESSION_2"),
        "api_id": int(os.getenv("API_ID2", 0)),
        "api_hash": os.getenv("API_HASH2")
    }
]

# Validasi credentials
for acc in ACCOUNTS:
    if not all([acc.get("session"), acc.get("api_id"), acc.get("api_hash")]):
        raise ValueError(f"Creds akun {acc['name']} tidak lengkap!")

# ==========================
# GOOGLE DRIVE SETUP
# ==========================
SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ['https://www.googleapis.com/auth/drive.file']

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=credentials)

# ==========================
# QUEUE GLOBAL
# ==========================
queue = asyncio.Queue()  # Forwarder → Exporter
MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500 MB

# ==========================
# HELPERS GOOGLE DRIVE
# ==========================
async def create_daily_folder():
    today_str = datetime.now().strftime("%Y-%m-%d")
    results = drive_service.files().list(
        q=f"name='{today_str}' and mimeType='application/vnd.google-apps.folder'",
        spaces='drive',
        fields='files(id, name)'
    ).execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    folder = drive_service.files().create(
        body={'name': today_str, 'mimeType': 'application/vnd.google-apps.folder'},
        fields='id'
    ).execute()
    return folder['id']

async def upload_to_drive(file_path, folder_id, retries=3):
    for attempt in range(retries):
        try:
            media = MediaFileUpload(file_path, resumable=True)
            file = drive_service.files().create(
                body={'name': os.path.basename(file_path), 'parents': [folder_id]},
                media_body=media, fields='id'
            ).execute()
            print(f"✅ {file_path} uploaded, ID: {file['id']}")
            os.remove(file_path)
            return file['id']
        except Exception as e:
            print(f"⚠️ Upload gagal (attempt {attempt+1}/{retries}): {e}")
            await asyncio.sleep(5)
    print(f"❌ Upload gagal: {file_path}")

# ==========================
# FORWARDER CLIENT
# ==========================
async def forwarder_task(account):
    app = Client(
        f"{account['name']}_session",
        api_id=account["api_id"],
        api_hash=account["api_hash"],
        session_string=account["session"],
        in_memory=True
    )
    await app.start()

    # Tambahkan log akun yang digunakan
    me = await app.get_me()
    print(f"Forwarder pakai akun: {me.id} | {me.first_name}")

    print(f"{account['name']} Forwarder siap")

    @app.on_message(filters.private)
    async def forward_message(client, message):
        try:
            forwarded_msg = await message.forward(account["target_chat"])
            print(f"Forwarded message {forwarded_msg.id}")
            await queue.put(forwarded_msg)
        except Exception as e:
            print(f"❌ Gagal forward: {e}")

    await asyncio.Event().wait()  # supaya forwarder tetap hidup

# ==========================
# EXPORTER CLIENT
# ==========================
async def exporter_task(account):
    app = Client(
        f"{account['name']}_session",
        api_id=account["api_id"],
        api_hash=account["api_hash"],
        session_string=account["session"],
        in_memory=True
    )
    await app.start()

    # Tambahkan log akun yang digunakan
    me = await app.get_me()
    print(f"Exporter pakai akun: {me.id} | {me.first_name}")

    print(f"{account['name']} Exporter siap")

    async def process_queue():
        while True:
            batch = []
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

                size = os.path.getsize(file_path)
                batch_size += size
                batch.append(file_path)

            if batch:
                folder_id = await create_daily_folder()
                for file_path in batch:
                    await upload_to_drive(file_path, folder_id)

            await asyncio.sleep(1800)  # 30 menit

    await process_queue()

# ==========================
# MAIN
# ==========================
async def main():
    await asyncio.gather(
        forwarder_task(ACCOUNTS[0]),
        exporter_task(ACCOUNTS[1])
    )

if __name__ == "__main__":
    print("Menjalankan Forwarder + Exporter + upload ke Google Drive setiap 30 menit / batch maksimal 500 MB")
    asyncio.run(main())
