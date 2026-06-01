#!/usr/bin/env python3
"""Upload dubbed video to YouTube using OAuth2."""

import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--tags", default="donghua,vietnamese dubbed,animation review")
    parser.add_argument("--category", default="24")  # Entertainment
    parser.add_argument("--privacy", default="public", choices=["public", "private", "unlisted"])
    args = parser.parse_args()

    client_id = os.getenv("YT_CLIENT_ID")
    client_secret = os.getenv("YT_CLIENT_SECRET")
    refresh_token = os.getenv("YT_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print("ERROR: Missing YouTube OAuth2 credentials (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN)")
        sys.exit(1)

    # Get access token
    import requests
    token_resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    token_resp.raise_for_status()
    access_token = token_resp.json()["access_token"]

    # Upload via resumable upload
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(os.path.getsize(args.video)),
    }

    metadata = {
        "snippet": {
            "title": args.title,
            "description": args.description,
            "tags": args.tags.split(","),
            "categoryId": args.category,
        },
        "status": {
            "privacyStatus": args.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    # Initialize resumable upload
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers=headers,
        json=metadata,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    # Upload video
    with open(args.video, "rb") as f:
        upload_resp = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4"},
            data=f,
            timeout=3600,
        )
        upload_resp.raise_for_status()
        result = upload_resp.json()

    video_id = result["id"]
    print(f"✅ Uploaded: https://youtube.com/watch?v={video_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
