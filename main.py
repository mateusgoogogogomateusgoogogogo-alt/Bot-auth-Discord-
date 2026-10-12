import os
import json
import asyncio
import requests
from datetime import datetime, timezone
from typing import Optional
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIG
# ============================================================
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
GUILD_ID = int(os.getenv("GUILD_ID"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8001")
AUTH_URL = f"{BASE_URL}/"

DISCORD_API = "https://discord.com/api/v10"
CONFIG_FILE = "config.json"
TOKENS_FILE = "tokens.json"

DEFAULT_CONFIG = {
    "verified_role_id": None,
    "unverified_role_id": None,
    "log_channel_id": None,
    "verify_channel_id": None,
    "unverified_timeout_minutes": 15,
    "timeout_action": "kick",
    "embed": {
        "title": "🛡️ Sistema de Verificação",
        "description": (
            "Para acessar todos os canais do servidor, clique no botão abaixo "
            "e autorize com sua conta Discord.\n\n"
            "Você será verificado automaticamente em segundos."
        ),
        "color": "#5865F2",
        "footer": "Segurança do Servidor • Verificação Obrigatória",
        "thumbnail_url": None,
        "image_url": None,
        "button_label": "✅ Verificar Conta",
    },
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = json.loads(json.dumps(DEFAULT_CONFIG))
        merged.update(data)
        merged["embed"] = {**DEFAULT_CONFIG["embed"], **data.get("embed", {})}
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(data: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_tokens() -> dict:
    if not os.path.exists(TOKENS_FILE):
        return {}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_tokens(data: dict):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


config = load_config()


# ============================================================
# HELPERS
# ============================================================
def hex_to_color(hex_str: str) -> discord.Color:
    try:
        return discord.Color(int(hex_str.replace("#", ""), 16))
    except Exception:
        return discord.Color.blurple()


def refresh_access_token(refresh_token: str) -> Optional[dict]:
    try:
        r = requests.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"⚠️ Erro refresh: {e}")
    return None


# ============================================================
# BOT
# ============================================================
class AuthBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print(f"✅ Slash commands sincronizados para {self.user}")
        self.check_unverified_loop.start()

    @tasks.loop(minutes=1)
    async def check_unverified_loop(self):
        global config
        config = load_config()

        timeout_min = config.get("unverified_timeout_minutes", 15)
        action = config.get("timeout_action", "kick")
        unverified_role_id = config.get("unverified_role_id")

        if not unverified_role_id or action == "none" or timeout_min <= 0:
            return

        for guild in bot.guilds:
            role = guild.get_role(unverified_role_id)
            if not role:
                continue

            for member in role.members:
                if member.bot:
                    continue
                if member.joined_at is None:
                    continue

                delta = (datetime.now(timezone.utc) - member.joined_at).total_seconds() / 60
                if delta < timeout_min:
                    continue

                try:
                    reason = f"Não se verificou em {timeout_min} minutos"
                    if action == "ban":
                        await member.ban(reason=reason)
                        txt = f"🔨 Banido por não se verificar: **{member}** (`{member.id}`)"
                    else:
                        await member.kick(reason=reason)
                        txt = f"👢 Expulso por não se verificar: **{member}** (`{member.id}`)"
                    await log_action(guild, txt)
                except Exception as e:
                    print(f"⚠️ Erro punindo {member}: {e}")

    @check_unverified_loop.before_loop
    async def before_check(self):
        await self.wait_until_ready()


bot = AuthBot()


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.id == ADMIN_ID


async def log_action(guild: discord.Guild, message: str):
    channel_id = config.get("log_channel_id")
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    try:
        embed = discord.Embed(
            description=message,
            color=discord.Color.dark_gray(),
            timestamp=datetime.now(timezone.utc)
        )
        await channel.send(embed=embed)
    except Exception:
        pass


# ============================================================
# PAINEL ADM
# ============================================================
painel = app_commands.Group(name="painel_adm", description="⚙️ Painel de administração")


@painel.command(name="ver", description="Mostra todas as configurações atuais")
async def painel_ver(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    e = config["embed"]
    embed = discord.Embed(title="⚙️ Configuração Atual", color=discord.Color.blurple())
    embed.add_field(
        name="🎭 Cargos",
        value=(
            (f"✅ Verificado: <@&{config['verified_role_id']}>" if config.get("verified_role_id") else "✅ Verificado: `não definido`")
            + "\n" +
            (f"⏳ Não Verificado: <@&{config['unverified_role_id']}>" if config.get("unverified_role_id") else "⏳ Não Verificado: `não definido`")
        ),
        inline=False
    )
    embed.add_field(
        name="📺 Canais",
        value=(
            (f"Verificação: <#{config['verify_channel_id']}>" if config.get("verify_channel_id") else "Verificação: `não definido`")
            + "\n" +
            (f"Logs: <#{config['log_channel_id']}>" if config.get("log_channel_id") else "Logs: `não definido`")
        ),
        inline=False
    )
    embed.add_field(
        name="⏰ Timeout",
        value=f"Tempo: **{config['unverified_timeout_minutes']} min**\nAção: **{config['timeout_action']}**",
        inline=False
    )
    embed.add_field(
        name="🎨 Embed",
        value=f"**Título:** {e['title']}\n**Botão:** {e['button_label']}\n**Cor:** `{e['color']}`",
        inline=False
    )
    if e.get("thumbnail_url"):
        embed.set_thumbnail(url=e["thumbnail_url"])
    if e.get("image_url"):
        embed.set_image(url=e["image_url"])

    await interaction.response.send_message(embed=embed, ephemeral=True)


@painel.command(name="cargos", description="Define os cargos de verificado e não verificado")
async def painel_cargos(interaction: discord.Interaction, verificado: discord.Role, nao_verificado: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    config["verified_role_id"] = verificado.id
    config["unverified_role_id"] = nao_verificado.id
    save_config(config)

    await interaction.response.send_message(
        f"✅ **Cargos salvos!**\n"
        f"✔️ Verificado: {verificado.mention}\n"
        f"⏳ Não Verificado: {nao_verificado.mention}\n\n"
        f"Agora quem se verificar vai receber automaticamente esses cargos.",
        ephemeral=True
    )


@painel.command(name="canais", description="Define canal de verificação e canal de logs")
async def painel_canais(interaction: discord.Interaction, canal_verificacao: discord.TextChannel, canal_logs: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    config["verify_channel_id"] = canal_verificacao.id
    config["log_channel_id"] = canal_logs.id
    save_config(config)

    await interaction.response.send_message(
        f"✅ **Canais salvos!**\n"
        f"Verificação: {canal_verificacao.mention}\n"
        f"Logs: {canal_logs.mention}",
        ephemeral=True
    )


@painel.command(name="timeout", description="Configura o tempo para se verificar e a punição")
@app_commands.choices(acao=[
    app_commands.Choice(name="Kick (expulsar)", value="kick"),
    app_commands.Choice(name="Ban (banir)", value="ban"),
    app_commands.Choice(name="Nenhuma", value="none"),
])
async def painel_timeout(interaction: discord.Interaction, minutos: int, acao: app_commands.Choice[str]):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    config["unverified_timeout_minutes"] = minutos
    config["timeout_action"] = acao.value
    save_config(config)

    emoji = "🔨" if acao.value == "ban" else ("👢" if acao.value == "kick" else "🚫")
    await interaction.response.send_message(
        f"✅ **Configurado!**\n⏰ Tempo: **{minutos} min**\n{emoji} Ação: **{acao.name}**",
        ephemeral=True
    )


@painel.command(name="embed", description="Personaliza o embed de verificação")
async def painel_embed(
    interaction: discord.Interaction,
    titulo: Optional[str] = None,
    descricao: Optional[str] = None,
    cor: Optional[str] = None,
    footer: Optional[str] = None,
    botao: Optional[str] = None,
    thumbnail: Optional[str] = None,
    imagem: Optional[str] = None
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    e = config["embed"]
    if titulo is not None: e["title"] = titulo
    if descricao is not None: e["description"] = descricao
    if cor is not None: e["color"] = cor
    if footer is not None: e["footer"] = footer
    if botao is not None: e["button_label"] = botao
    if thumbnail is not None: e["thumbnail_url"] = thumbnail or None
    if imagem is not None: e["image_url"] = imagem or None

    save_config(config)

    preview = discord.Embed(title=e["title"], description=e["description"], color=hex_to_color(e["color"]))
    if e.get("footer"): preview.set_footer(text=e["footer"])
    if e.get("thumbnail_url"): preview.set_thumbnail(url=e["thumbnail_url"])
    if e.get("image_url"): preview.set_image(url=e["image_url"])

    await interaction.response.send_message(
        content=f"✅ Embed atualizado! Botão: **{e['button_label']}**\n\n*Preview:*",
        embed=preview,
        ephemeral=True
    )


@painel.command(name="resetar_embed", description="Reseta o embed para o padrão")
async def painel_resetar_embed(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return
    config["embed"] = json.loads(json.dumps(DEFAULT_CONFIG["embed"]))
    save_config(config)
    await interaction.response.send_message("✅ Embed resetado.", ephemeral=True)


@painel.command(name="enviar", description="Envia o painel de verificação no canal configurado")
async def painel_enviar(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    if not config.get("verify_channel_id"):
        await interaction.response.send_message("⚠️ Configure o canal com `/painel_adm canais`.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(config["verify_channel_id"])
    if not channel:
        await interaction.response.send_message("❌ Canal não encontrado.", ephemeral=True)
        return

    e = config["embed"]
    embed = discord.Embed(title=e["title"], description=e["description"], color=hex_to_color(e["color"]))
    if e.get("footer"): embed.set_footer(text=e["footer"])
    if e.get("thumbnail_url"): embed.set_thumbnail(url=e["thumbnail_url"])
    if e.get("image_url"): embed.set_image(url=e["image_url"])

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=e["button_label"], url=AUTH_URL, style=discord.ButtonStyle.link))

    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"✅ Painel enviado em {channel.mention}!", ephemeral=True)


bot.tree.add_command(painel)


# ============================================================
# PUXAR MEMBROS
# ============================================================
async def try_pull_one(target_guild_id: int, user_id: str, access_token: str) -> tuple[bool, str]:
    try:
        r = requests.put(
            f"{DISCORD_API}/guilds/{target_guild_id}/members/{user_id}",
            headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
            json={"access_token": access_token},
            timeout=10,
        )
        if r.status_code in (201, 204):
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, str(e)


@bot.tree.command(name="pull_count", description="Análise de tokens")
async def pull_count(interaction: discord.Interaction, servidor_destino: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    target_guild = bot.get_guild(int(servidor_destino.strip()))
    if not target_guild:
        await interaction.response.send_message("❌ Bot não está nesse servidor.", ephemeral=True)
        return

    tokens = load_tokens()
    source_guild = interaction.guild

    elegiveis = ja_no_destino = fora_origem = 0
    for uid in tokens.keys():
        m = source_guild.get_member(int(uid))
        if not m:
            fora_origem += 1
            continue
        if target_guild.get_member(int(uid)):
            ja_no_destino += 1
            continue
        elegiveis += 1

    await interaction.response.send_message(
        f"📊 **Análise**\n"
        f"🎯 Destino: **{target_guild.name}**\n"
        f"🔑 Tokens: **{len(tokens)}**\n"
        f"✅ Elegíveis: **{elegiveis}**\n"
        f"⏭️ Já no destino: **{ja_no_destino}**\n"
        f"👻 Fora da origem: **{fora_origem}**",
        ephemeral=True
    )


@bot.tree.command(name="pull_members", description="Puxa via API os membros que autorizaram")
@app_commands.describe(servidor_destino="ID do servidor destino", quantidade="Quantos puxar (0 = todos)")
async def pull_members(interaction: discord.Interaction, servidor_destino: str, quantidade: int = 0):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        return

    target_guild = bot.get_guild(int(servidor_destino.strip()))
    if not target_guild:
        await interaction.response.send_message("❌ Bot não está no destino.", ephemeral=True)
        return

    author = target_guild.get_member(interaction.user.id)
    if not author or not author.guild_permissions.administrator:
        await interaction.response.send_message("❌ Você precisa ser admin no destino.", ephemeral=True)
        return

    if not target_guild.me.guild_permissions.create_instant_invite:
        await interaction.response.send_message("❌ Bot precisa de **Criar Convite** no destino.", ephemeral=True)
        return

    tokens = load_tokens()
    source_guild = interaction.guild

    candidatos = []
    for uid, info in tokens.items():
        m = source_guild.get_member(int(uid))
        if not m or target_guild.get_member(int(uid)):
            continue
        candidatos.append((uid, info.get("access_token"), str(m), info.get("refresh_token")))

    if not candidatos:
        await interaction.response.send_message("ℹ️ Nenhum elegível.", ephemeral=True)
        return

    if quantidade > 0:
        candidatos = candidatos[:quantidade]

    total = len(candidatos)
    await interaction.response.send_message(f"🚀 Puxando **{total}** membro(s) para **{target_guild.name}**...", ephemeral=True)

    sucesso = falha = renovados = 0
    falhas_detalhe = []

    for uid, token, nome, refresh in candidatos:
        ok, motivo = await try_pull_one(target_guild.id, uid, token)

        if not ok and refresh:
            new = refresh_access_token(refresh)
            if new and new.get("access_token"):
                renovados += 1
                tokens[uid]["access_token"] = new["access_token"]
                tokens[uid]["refresh_token"] = new.get("refresh_token", refresh)
                tokens[uid]["expires_at"] = datetime.now(timezone.utc).timestamp() + new.get("expires_in", 0)
                save_tokens(tokens)
                ok, motivo = await try_pull_one(target_guild.id, uid, new["access_token"])

        if ok:
            sucesso += 1
        else:
            falha += 1
            falhas_detalhe.append(f"{nome} ({motivo})")
        await asyncio.sleep(0.6)

    embed = discord.Embed(title="📤 Resultado", color=discord.Color.green() if falha == 0 else discord.Color.orange())
    embed.add_field(name="🎯 Destino", value=target_guild.name, inline=False)
    embed.add_field(name="✅ Sucesso", value=str(sucesso), inline=True)
    embed.add_field(name="❌ Falhas", value=str(falha), inline=True)
    embed.add_field(name="🔄 Renovados", value=str(renovados), inline=True)
    if falhas_detalhe:
        embed.add_field(name="⚠️ Detalhes", value="\n".join(falhas_detalhe[:10])[:1000], inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ============================================================
# EVENTOS
# ============================================================
@bot.event
async def on_member_join(member: discord.Member):
    global config
    config = load_config()

    role_id = config.get("unverified_role_id")
    if role_id:
        role = member.guild.get_role(role_id)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                pass

    timeout = config.get("unverified_timeout_minutes", 15)
    action = config.get("timeout_action", "kick")
    if action != "none" and timeout > 0:
        try:
            embed = discord.Embed(
                title="⏰ Você precisa se verificar!",
                description=(
                    f"Você entrou em **{member.guild.name}** mas ainda não se verificou.\n\n"
                    f"Você tem **{timeout} minutos** para se verificar, ou será "
                    f"**{'banido' if action == 'ban' else 'expulso'}** automaticamente."
                ),
                color=discord.Color.orange()
            )
            if config.get("verify_channel_id"):
                embed.add_field(name="Como se verificar", value=f"Vá até <#{config['verify_channel_id']}> e clique no botão.", inline=False)
            await member.send(embed=embed)
        except discord.Forbidden:
            pass

    await log_action(member.guild, f"👋 **{member}** entrou.")


@bot.event
async def on_member_remove(member: discord.Member):
    await log_action(member.guild, f"👋 **{member}** saiu.")


@bot.event
async def on_ready():
    print(f"🤖 Bot conectado como {bot.user} (ID: {bot.user.id})")
    print(f"🌐 BASE_URL: {BASE_URL}")
    print(f"🔘 AUTH_URL: {AUTH_URL}")


bot.run(TOKEN)