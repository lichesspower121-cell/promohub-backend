import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
TARGET_CHAT = os.environ.get("TARGET_CHAT", "@giveawayforall2").strip()
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*").strip()

CORS(
    app,
    resources={r"/api/*": {"origins": FRONTEND_ORIGIN}},
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
    methods=["POST", "OPTIONS"],
)

# Simple in-memory cooldown. For a larger app, use Redis/database storage.
LAST_POST = {}
POST_COOLDOWN_SECONDS = 60


def verify_telegram_init_data(init_data: str):
    if not BOT_TOKEN or not init_data:
        return None

    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", None)

        if not received_hash:
            return None

        auth_date = int(values.get("auth_date", "0"))

        # Reject old Mini App authentication data.
        if abs(int(time.time()) - auth_date) > 3600:
            return None

        data_check_string = "\n".join(
            f"{key}={values[key]}" for key in sorted(values)
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user_json = values.get("user")

        if not user_json:
            return None

        return json.loads(user_json)

    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def valid_telegram_link(link: str):
    return (
        link.startswith("https://t.me/")
        or link.startswith("https://telegram.me/")
    )


@app.get("/")
def home():
    return jsonify(
        {
            "status": "online",
            "message": "PromoHub API is running",
        }
    )


@app.post("/api/promote/group")
def promote_group():
    if not BOT_TOKEN:
        return jsonify(
            {
                "success": False,
                "error": "BOT_TOKEN is not configured on the server",
            }
        ), 500

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data)

    if not user:
        return jsonify(
            {
                "success": False,
                "error": "Invalid or expired Telegram Mini App session",
            }
        ), 401

    user_id = str(user.get("id", ""))

    now = int(time.time())
    last_post = LAST_POST.get(user_id, 0)
    remaining = POST_COOLDOWN_SECONDS - (now - last_post)

    if remaining > 0:
        return jsonify(
            {
                "success": False,
                "error": f"Wait {remaining} seconds before posting again",
            }
        ), 429

    data = request.get_json(silent=True) or {}
    link = str(data.get("link", "")).strip()

    if not valid_telegram_link(link):
        return jsonify(
            {
                "success": False,
                "error": "Enter a valid Telegram link",
            }
        ), 400

    text = (
        "🚀 <b>NEW PROMOTION</b>\n\n"
        "📢 Check out this Telegram community!\n\n"
        f"🔗 {link}\n\n"
        "🔥 Join and explore now!"
    )

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TARGET_CHAT,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )

        telegram_data = response.json()

    except requests.RequestException:
        return jsonify(
            {
                "success": False,
                "error": "Could not connect to Telegram",
            }
        ), 502
    except ValueError:
        return jsonify(
            {
                "success": False,
                "error": "Telegram returned an invalid response",
            }
        ), 502

    if not response.ok or not telegram_data.get("ok"):
        return jsonify(
            {
                "success": False,
                "error": telegram_data.get(
                    "description",
                    "Telegram rejected the message",
                ),
            }
        ), 400

    LAST_POST[user_id] = now

    return jsonify(
        {
            "success": True,
            "message": f"Promotion posted to {TARGET_CHAT}",
            "destination": TARGET_CHAT,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
