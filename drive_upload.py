"""
Google Drive upload helper.

Uses the same token.pickle / credentials.json already in the project
(sheets.py already requests Drive scope, so no re-auth needed).

Usage:
    from drive_upload import upload_video
    link = upload_video("/path/to/output.mp4", "video5")
    # → https://drive.google.com/file/d/.../view
"""
import os
import pickle

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_FOLDER_CACHE: dict = {}
DRIVE_FOLDER_NAME = "AI Influencer Outputs"


def _get_drive_service():
    token_file = os.path.join(_BASE_DIR, "token.pickle")
    with open(token_file, "rb") as f:
        creds = pickle.load(f)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "wb") as f:
                pickle.dump(creds, f)
    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, name: str) -> str:
    if name in _FOLDER_CACHE:
        return _FOLDER_CACHE[name]
    res = service.files().list(
        q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces="drive",
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    if files:
        folder_id = files[0]["id"]
    else:
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        folder_id = service.files().create(body=meta, fields="id").execute()["id"]
    _FOLDER_CACHE[name] = folder_id
    return folder_id


def upload_video(file_path: str, video_name: str) -> str:
    """Upload video to Drive, make it publicly readable, return shareable link."""
    service = _get_drive_service()
    folder_id = _get_or_create_folder(service, DRIVE_FOLDER_NAME)

    file_metadata = {"name": f"{video_name}.mp4", "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)
    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id,webViewLink",
    ).execute()

    service.permissions().create(
        fileId=uploaded["id"],
        body={"type": "anyone", "role": "reader"},
    ).execute()

    return (
        uploaded.get("webViewLink")
        or f"https://drive.google.com/file/d/{uploaded['id']}/view"
    )
