# ==========================
# IMPORT STATEMENTS
# ==========================
import os
import asyncio
from datetime import datetime
from pyrogram import Client, filters
import requests

# ==========================
# CONFIG AKUN
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

# ==========================
# CREDENTIALS VALIDATION
# ==========================
for acc in ACCOUNTS:
    if not all([acc.get("session"), acc.get("api_id"), acc.get("api_hash")]):
        raise ValueError(f"Creds akun {acc['name']} tidak lengkap!")

# ==========================
# GLOBAL QUEUE
# ==========================
queue = asyncio.Queue()

# ==========================
# HELPER ONEDRIVE
# ==========================
def get_access_token():
    """GET ACCESS TOKEN FROM ENVIRONMENT. IF ACCESS TOKEN IS EXPIRED, 
    IT CAN USE REFRESH TOKEN TO GENERATE NEW ACCESS TOKEN"""
    token = os.environ.get("ONEDRIVE_ACCESS_TOKEN")
    if not token:
        raise ValueError("ONEDRIVE_ACCESS_TOKEN NOT FOUND!!!")
    return token

def refresh_access_token():
    """TAKE REFRESH TOKEN FROM ENVIRONMENT FOR GENERATE NEW TOKEN"""
    creds = {
        "client_id": os.environ.get("ONEDRIVE_CLIENT_ID"),
        "client_secret": os.environ.get("ONEDRIVE_CLIENT_SECRET"),
        "redirect_url": os.environ.get("ONEDRIVE_REDIRECT_URL")
    }
    refresh_token = os.environ.get("ONEDRIVE_REFRESH_TOKEN")

    data = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "offline_access Files.ReadWrite"
    }
    r = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/token", data=data)
    r.raise_for_status()
    token_data = r.json()
    
    # update env sementara untuk script ini
    os.environ["ONEDRIVE_ACCESS_TOKEN"] = token_data["access_token"]
    os.environ["ONEDRIVE_REFRESH_TOKEN"] = token_data.get("refresh_token", refresh_token)
    return token_data["access_token"]

def create_upload_session(access_token, remote_path):
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{remote_path}:/createUploadSession"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.post(url, headers=headers)
    if r.status_code == 401:
        #TOKEN EXPIRED, AUTOMATIC REFRESH
        access_token = refresh_access_token()
        headers["Authorization"] = f"Bearer {access_token}"
        r = requests.post(url, headers=headers)
    r.raise_for_status()
    return r.json()["uploadUrl"]

def upload_large_file(file_path, remote_path, max_retries=2):
    access_token = get_access_token()
    for attempt in range(max_retries):
        try:
            upload_url = create_upload_session(access_token, remote_path)
            chunk_size = 5 * 1024 * 1024
            with open(file_path, "rb") as f:
                file_size = os.path.getsize(file_path)
                start = 0
                while start < file_size:
                    end = min(start + chunk_size, file_size) - 1
                    f.seek(start)
                    data = f.read(chunk_size)
                    headers = {
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {start}-{end}/{file_size}"
                    }
                    res = requests.put(upload_url, headers=headers, data=data)
                    if res.status_code not in (200, 201, 202):
                        raise Exception(res.text)
                    start += chunk_size
            print(f"☁️ Uploaded: {remote_path}")
            break
        except Exception as e:
            print(f"⚠️ Upload gagal (attempt {attempt+1}/{max_retries}): {e}")
            asyncio.sleep(1)

# ==========================
# FORWARDER TASK
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
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    forwarded_msg = await message.forward(account["target_chat"])
                    print(f"Forwarded message {forwarded_msg.id}")
                    await queue.put(forwarded_msg)
                    break
                except Exception as e:
                    print(f"⚠️ Forward gagal (attempt {attempt+1}/{max_retries}): {e}")
                    await asyncio.sleep(1)

        @app.on_deleted_messages()
        async def deleted_message_handler(client, messages):
            for msg in messages:
                try:
                    sender_id = msg.from_user.id if msg.from_user else None
                    info = {
                        "type": "deleted",
                        "sender_id": sender_id,
                        "chat_id": msg.chat.id,
                        "message_id": msg.id,
                        "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    await queue.put(info)
                    print(f"⚠️ Pesan dihapus dari {sender_id} dikirim ke exporter")
                except Exception as e:
                    print(f"❌ Error deleted handler: {e}")

        await asyncio.Event().wait()

    except Exception as e:
        print(f"❌ Forwarder crash: {e}")
        await asyncio.sleep(10)
        await forwarder_task(account)

# ==========================
# EXPORTER TASK
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
        print(f"Exporter pakai akun: {me.id} | Real-time Active")

        async def process_queue():
            while True:
                today = datetime.now().strftime('%Y-%m-%d')
                base_folder = f"temp_{today}"
                os.makedirs(base_folder, exist_ok=True)
                log_path = os.path.join(base_folder, "log.txt")

                msg = await queue.get()  # real-time

                try:
                    # ==================== DELETED MESSAGE ====================
                    if isinstance(msg, dict) and msg.get("type") == "deleted":
                        log_entry = (
                            f"[{msg['date']}]\n"
                            f"Sender ID: {msg['sender_id']}\n"
                            f"Chat ID: {msg['chat_id']}\n"
                            f"Message ID: {msg['message_id']}\n"
                        )
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(log_entry)
                        upload_large_file(log_path, f"telegram_backup/{today}/log.txt", max_retries=2)
                        continue

                    sender = msg.from_user
                    name = sender.first_name if sender else "Unknown"
                    username = f"@{sender.username}" if sender and sender.username else "-"
                    msg_time = msg.date.strftime('%Y-%m-%d_%H-%M-%S')
                    time_str = msg.date.strftime('%Y-%m-%d %H:%M:%S')

                    log_entry = f"[{time_str}]\nNama: {name}\nUsername: {username}\n"

                    # TEXT
                    if msg.text:
                        log_entry += f"Text: {msg.text}\n"

                    # STICKER / PHOTO / VIDEO → forward only
                    elif msg.photo or msg.video or msg.sticker:
                        max_retries = 2
                        for attempt in range(max_retries):
                            try:
                                await msg.forward("me")
                                break
                            except Exception as e:
                                print(f"⚠️ Forward gagal (attempt {attempt+1}/{max_retries}): {e}")
                                await asyncio.sleep(1)
                        if msg.sticker:
                            log_entry += "Media: STICKER (forwarded to Saved Messages)\n"
                        elif msg.photo:
                            log_entry += "Media: PHOTO (forwarded to Saved Messages)\n"
                        elif msg.video:
                            log_entry += "Media: VIDEO (forwarded to Saved Messages)\n"
                        if msg.caption:
                            log_entry += f"Caption: {msg.caption}\n"

                    # VOICE / AUDIO / DOCUMENT → download + upload
                    elif msg.voice or msg.audio or msg.document:
                        if msg.voice:
                            ext = ".ogg"
                            prefix = "voice"
                        elif msg.audio:
                            ext = ".mp3"
                            prefix = "audio"
                        else:
                            ext = os.path.splitext(msg.document.file_name or "")[1] or ".bin"
                            prefix = "file"

                        filename = f"{prefix}_{msg_time}_{msg.id}{ext}"
                        file_path = await msg.download(file_name=os.path.join(base_folder, filename))
                        log_entry += f"Media: {filename}\n"
                        if msg.caption:
                            log_entry += f"Caption: {msg.caption}\n"

                        upload_large_file(file_path, f"telegram_backup/{today}/{filename}", max_retries=2)
                        os.remove(file_path)

                    else:
                        log_entry += "[UNKNOWN MESSAGE]\n"

                    log_entry += "\n-----------------\n\n"
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(log_entry)
                    upload_large_file(log_path, f"telegram_backup/{today}/log.txt", max_retries=2)

                except Exception as e:
                    print(f"⚠️ Error proses pesan: {e}")

        await process_queue()

    except Exception as e:
        print(f"❌ Exporter crash: {e}")
        await asyncio.sleep(5)
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
    print("Menjalankan Exporter Telegram → Forward media/sticker → Upload OneDrive (real-time, retry 2x)")
    asyncio.run(main())
