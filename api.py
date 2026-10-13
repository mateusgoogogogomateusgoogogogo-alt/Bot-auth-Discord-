import os
import json
import socket
import requests
from datetime import datetime, timezone
from flask import Flask, request, redirect, render_template
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="templates")

# ============================================================
# CONFIG
# ============================================================
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8001/callback")
GUILD_ID = os.getenv("GUILD_ID")
BOT_TOKEN = os.getenv("DISCORD_TOKEN")
APP_NAME = "AuthBot"

DISCORD_API = "https://discord.com/api/v10"


# ---- Mesma lógica de DATA_DIR do main.py ----
def _pick_data_dir() -> str:
    for p in ("/data", "./data", "."):
        try:
            os.makedirs(p, exist_ok=True)
            if os.access(p, os.W_OK):
                return p
        except Exception:
            continue
    return "."


DATA_DIR = _pick_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
TOKENS_FILE = os.path.join(DATA_DIR, "tokens.json")

print(f"📁 DATA_DIR: {DATA_DIR}")
print(f"📄 CONFIG_FILE: {CONFIG_FILE}")
print(f"📄 TOKENS_FILE: {TOKENS_FILE}", flush=True)


# ============================================================
# PERSISTÊNCIA
# ============================================================
def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_tokens() -> dict:
    if not os.path.exists(TOKENS_FILE):
        return {}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_token(user_id, access_token, refresh_token, expires_in):
    try:
        data = load_tokens()
        data[user_id] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": datetime.now(timezone.utc).timestamp() + expires_in if expires_in else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(TOKENS_FILE) or ".", exist_ok=True)
        with open(TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"💾 Token salvo: {user_id} → {TOKENS_FILE}", flush=True)
        return True
    except Exception as e:
        print(f"❌ Erro salvando token: {e}", flush=True)
        return False


# ============================================================
# ROTAS
# ============================================================
@app.route("/")
def home():
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=identify%20guilds.join"
        f"&prompt=consent"
    )
    return redirect(url)


@app.route("/callback")
def callback():
    config = load_config()
    verified_role_id = config.get("verified_role_id")
    unverified_role_id = config.get("unverified_role_id")
    log_channel_id = config.get("log_channel_id")
    embed_cfg = config.get("embed", {})

    print(f"📥 Callback chamado. Config: verif={verified_role_id}, nao_verif={unverified_role_id}, logs={log_channel_id}", flush=True)

    code = request.args.get("code")
    if not code:
        return render_template("erro.html", motivo="Nenhum código recebido.", app_name=APP_NAME)

    token_resp = requests.post(
        f"{DISCORD_API}/oauth2/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if token_resp.status_code != 200:
        print(f"❌ token: {token_resp.status_code} {token_resp.text}", flush=True)
        return render_template("erro.html", motivo="Falha ao obter token.", app_name=APP_NAME)

    td = token_resp.json()
    access_token = td.get("access_token")
    refresh_token = td.get("refresh_token")
    expires_in = td.get("expires_in", 0)

    if not access_token:
        return render_template("erro.html", motivo="Token inválido.", app_name=APP_NAME)

    user_resp = requests.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if user_resp.status_code != 200:
        return render_template("erro.html", motivo="Falha ao obter usuário.", app_name=APP_NAME)

    user = user_resp.json()
    user_id = user["id"]
    username = user.get("global_name") or user["username"]
    avatar_hash = user.get("avatar")

    # 💾 Salva o token SEMPRE
    save_token(user_id, access_token, refresh_token, expires_in)

    bot_headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    # ---- Cargos ----
    if unverified_role_id:
        r = requests.delete(
            f"{DISCORD_API}/guilds/{GUILD_ID}/members/{user_id}/roles/{unverified_role_id}",
            headers=bot_headers,
        )
        print(f"🔻 Remove não-verif ({unverified_role_id}): HTTP {r.status_code}", flush=True)

    if verified_role_id:
        r = requests.put(
            f"{DISCORD_API}/guilds/{GUILD_ID}/members/{user_id}/roles/{verified_role_id}",
            headers=bot_headers,
        )
        print(f"🔺 Adiciona verif ({verified_role_id}): HTTP {r.status_code}", flush=True)
        if r.status_code not in (200, 204):
            print(f"   ⚠️ Resposta: {r.text[:200]}", flush=True)
    else:
        print(f"⚠️ verified_role_id não configurado!", flush=True)

    # ---- Dados do servidor ----
    guild_resp = requests.get(f"{DISCORD_API}/guilds/{GUILD_ID}", headers=bot_headers)
    guild_name = "Servidor"
    guild_icon = None
    if guild_resp.status_code == 200:
        g = guild_resp.json()
        guild_name = g.get("name", "Servidor")
        if g.get("icon"):
            guild_icon = f"https://cdn.discordapp.com/icons/{GUILD_ID}/{g['icon']}.png?size=256"

    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=256"
        if avatar_hash else
        f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    )

    # ---- Link de convite ----
    guild_url = f"https://discord.com/channels/{GUILD_ID}"
    try:
        ch_resp = requests.get(f"{DISCORD_API}/guilds/{GUILD_ID}/channels", headers=bot_headers, timeout=10)
        invite_ch_id = None
        if ch_resp.status_code == 200:
            for ch in ch_resp.json():
                if ch["type"] == 0:
                    invite_ch_id = ch["id"]
                    break
        if invite_ch_id:
            inv = requests.post(
                f"{DISCORD_API}/channels/{invite_ch_id}/invites",
                headers=bot_headers,
                json={"max_age": 3600, "max_uses": 1, "unique": True},
                timeout=10,
            )
            if inv.status_code in (200, 201):
                guild_url = f"https://discord.gg/{inv.json()['code']}"
    except Exception as e:
        print(f"⚠️ convite: {e}", flush=True)

    # ---- Log ----
    if log_channel_id:
        try:
            log_resp = requests.post(
                f"{DISCORD_API}/channels/{log_channel_id}/messages",
                headers=bot_headers,
                json={"embeds": [{
                    "description": f"✅ **{username}** (`{user_id}`) se verificou!",
                    "color": 0x23a55a,
                    "thumbnail": {"url": avatar_url},
                }]},
                timeout=10,
            )
            print(f"📝 Log: HTTP {log_resp.status_code}", flush=True)
        except Exception as e:
            print(f"❌ Erro log: {e}", flush=True)
    else:
        print("⚠️ log_channel_id não configurado!", flush=True)

    timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")

    return render_template(
        "sucesso.html",
        username=username,
        avatar=avatar_url,
        guild_name=guild_name,
        guild_icon=guild_icon,
        guild_banner=embed_cfg.get("image_url"),
        guild_url=guild_url,
        guild_id=GUILD_ID,
        timestamp=timestamp,
        app_name=APP_NAME,
    )


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/debug_config")
def debug_config():
    return {
        "DATA_DIR": DATA_DIR,
        "CONFIG_FILE": CONFIG_FILE,
        "TOKENS_FILE": TOKENS_FILE,
        "config_existe": os.path.exists(CONFIG_FILE),
        "config_conteudo": load_config(),
        "tokens_existe": os.path.exists(TOKENS_FILE),
        "tokens_count": len(load_tokens()),
        "GUILD_ID": GUILD_ID,
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET_set": bool(CLIENT_SECRET),
        "BOT_TOKEN_set": bool(BOT_TOKEN),
    }


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.errorhandler(404)
def not_found(e):
    return render_template("erro.html", motivo="Página não encontrada.", app_name=APP_NAME), 404


# ============================================================
# AUTO-PORT local
# ============================================================
def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def find_free_port(start: int, max_tries: int = 50) -> int:
    for port in range(start, start + max_tries):
        if is_port_free(port):
            return port
    raise RuntimeError("❌ Nenhuma porta livre")


if __name__ == "__main__":
    start = int(os.getenv("FLASK_PORT", 8001))
    chosen = start if is_port_free(start) else find_free_port(start + 1)
    print(f"🌐 Flask em http://localhost:{chosen}", flush=True)
    app.run(host="0.0.0.0", port=chosen, debug=False)
