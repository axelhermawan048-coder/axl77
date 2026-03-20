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
SERVICE_ACCOUNT_FILE = "service_account.json"  # letakkan file ini di folder project
SCOPES = ['https://www.googleapis.com/auth/drive.file']

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
drive_service = build('drive', 'v3', credentials=credentials)

# ==========================
# QUEUE GLOBAL
# ==========================
queue = asyncio.Queue()  # Forwarder → Exporter
MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500 MB maksimal batch

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
        "forwarder_session",                 # nama session file aman
        api_id=account["api_id"],
        api_hash=account["api_hash"],
        session_string=account["session"],
        in_memory=True                        # headless, tidak buat file fisik
    )
    await app.start()
    print(f"{account['name']} Forwarder siap")

    @app.on_message(filters.private)
    async def forward_message(client, message):
        forwarded_msg = await message.forward(account["target_chat"])
        print(f"Forwarded message {forwarded_msg.id}")
        await queue.put(message)

# ==========================
# EXPORTER CLIENT
# ==========================
async def exporter_task(account):
    app = Client(
        "exporter_session",                 # nama session file berbeda
        api_id=account["api_id"],
        api_hash=account["api_hash"],
        session_string=account["session"],
        in_memory=True
    )
    await app.start()
    print(f"{account['name']} Exporter siap")

    async def process_queue():
        while True:
            batch = []
            batch_size = 0

            while not queue.empty() and batch_size < MAX_BATCH_SIZE:
                msg = await queue.get()
                file_path = await msg.download() if msg.media else f"{datetime.now().strftime('%H%M%S')}_text.txt"
                if not msg.media:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(msg.text or "")
                size = os.path.getsize(file_path)
                batch_size += size
                batch.append(file_path)

            if batch:
                folder_id = await create_daily_folder()
                for file_path in batch:
                    await upload_to_drive(file_path, folder_id)

            await asyncio.sleep(1800)  # 30 menit interval

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
