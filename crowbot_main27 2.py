import discord
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio
import random
import json
import os
import re
import aiohttp
import importlib
import sys

import os
TOKEN = os.getenv("TOKEN")
PREFIX = "+"
OWNER_IDS = [368607314439176193]

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None, owner_ids=set(OWNER_IDS))

os.makedirs("data", exist_ok=True)

def db_load(f):
    p = os.path.join("data", f)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

def db_save(f, d):
    json.dump(d, open(os.path.join("data", f), "w", encoding="utf-8"), indent=2, ensure_ascii=False)

def get_guild(f, gid):
    return db_load(f).get(str(gid), {})

def set_guild(f, gid, d):
    data = db_load(f); data[str(gid)] = d; db_save(f, data)

def get_color(gid):
    """Retourne la couleur du theme configurée sur le serveur."""
    try:
        cfg = get_guild("modconfig.json", gid)
        return cfg.get("theme_color", 0x1a0a2e)
    except:
        return 0x1a0a2e

def get_member(f, gid, mid):
    return db_load(f).get(str(gid), {}).get(str(mid), {})

def set_member(f, gid, mid, d):
    data = db_load(f)
    data.setdefault(str(gid), {})[str(mid)] = d
    db_save(f, data)

def parse_dur(s):
    m = re.fullmatch(r"(\d+)([smhd])", s.lower())
    if not m: return None
    return timedelta(seconds=int(m[1]) * {"s":1,"m":60,"h":3600,"d":86400}[m[2]])

spam_cache   = defaultdict(lambda: defaultdict(list))
join_cache   = defaultdict(list)
snipe_cache  = {}
invite_cache = {}  # guild_id -> {code: uses}

async def send_log(guild, log_type, embed):
    try:
        cfg    = get_guild("logs.json", guild.id)
        cid    = cfg.get(log_type)
        nologs = cfg.get("nolog", [])
        if not cid: return
        ch = guild.get_channel(int(cid))
        if ch and str(ch.id) not in nologs:
            await ch.send(embed=embed)
    except Exception as ex:
        print(f"[send_log] Erreur ({log_type}): {ex}")

async def add_sanction(gid, mid, stype, reason, mod):
    s = get_member("sanctions.json", gid, mid)
    s.setdefault("list", []).append({"type": stype, "reason": reason, "mod": str(mod), "date": datetime.utcnow().isoformat()})
    set_member("sanctions.json", gid, mid, s)

LOG_CONFIG = {
    "warn":      {"icon": "⚠️",  "color": 0xffd700, "label": "Avertissement",       "log": "modlog"},
    "mute":      {"icon": "🔇",  "color": 0xff8c00, "label": "Mute",                 "log": "modlog"},
    "mute":      {"icon": "🔇",  "color": 0xff8c00, "label": "Mute",                 "log": "modlog"},
    "unmute":    {"icon": "🔊",  "color": 0x00bfff, "label": "Unmute",               "log": "modlog"},
    "cmute":     {"icon": "🔕",  "color": 0xff8c00, "label": "Mute salon",           "log": "modlog"},
    "uncmute":   {"icon": "🔔",  "color": 0x00bfff, "label": "Unmute salon",         "log": "modlog"},
    "kick":      {"icon": "👢",  "color": 0xff4500, "label": "Expulsion",            "log": "modlog"},
    "ban":       {"icon": "🔨",  "color": 0xff0000, "label": "Bannissement",         "log": "modlog"},
    "unban":     {"icon": "✅",  "color": 0x00ff00, "label": "Debannissement",       "log": "modlog"},
    "softban":   {"icon": "🔨",  "color": 0xff4500, "label": "Softban",              "log": "modlog"},
    "timeout":   {"icon": "⏱️", "color": 0xff8c00, "label": "Timeout",              "log": "modlog"},
    "untimeout": {"icon": "✅",  "color": 0x00bfff, "label": "Timeout leve",         "log": "modlog"},
    "addrole":   {"icon": "🏷️", "color": 0x00bfff, "label": "Ajout de role",        "log": "modlog"},
    "delrole":   {"icon": "🏷️", "color": 0xff8c00, "label": "Retrait de role",      "log": "modlog"},
    "derank":    {"icon": "⬇️", "color": 0xff4500, "label": "Derank",               "log": "modlog"},
    "clear":     {"icon": "🗑️", "color": 0x888888, "label": "Suppression messages", "log": "messagelog"},
    "lock":      {"icon": "🔒",  "color": 0xff4500, "label": "Verrouillage salon",   "log": "modlog"},
    "unlock":    {"icon": "🔓",  "color": 0x00ff00, "label": "Deverrouillage salon", "log": "modlog"},
    "hide":      {"icon": "🙈",  "color": 0xff8c00, "label": "Salon cache",          "log": "modlog"},
    "unhide":    {"icon": "👁️", "color": 0x00bfff, "label": "Salon affiche",        "log": "modlog"},
    "renew":     {"icon": "♻️",  "color": 0x888888, "label": "Salon recree",         "log": "modlog"},
    "slowmode":  {"icon": "🐢",  "color": 0x888888, "label": "Slowmode",             "log": "modlog"},
    "massban":   {"icon": "🔨",  "color": 0xff0000, "label": "Massban",              "log": "modlog"},
    "unhoist":   {"icon": "✂️",  "color": 0x888888, "label": "Unhoist",              "log": "modlog"},
}

async def log_mod(guild, action, member, mod, reason="Aucune raison", extra=None):
    cfg_action = LOG_CONFIG.get(action, {"icon": "🔧", "color": 0x888888, "label": action.upper(), "log": "modlog"})
    icon       = cfg_action["icon"]
    color      = cfg_action["color"]
    label      = cfg_action["label"]
    log_type   = cfg_action["log"]

    now  = discord.utils.utcnow()
    ts   = f"<t:{int(now.timestamp())}:T>"
    date = f"<t:{int(now.timestamp())}:F>"

    e = discord.Embed(color=color, timestamp=now)
    e.set_author(
        name=f"{icon} {label}",
        icon_url=member.display_avatar.url if hasattr(member, "display_avatar") else None
    )

    # Thumbnail = avatar du membre sanctionne
    if hasattr(member, "display_avatar"):
        e.set_thumbnail(url=member.display_avatar.url)

    # Champs principaux
    e.add_field(name="👤 Membre",      value=f"{member.mention}\n`{member}` • `{member.id}`", inline=True)
    e.add_field(name="🛡️ Modérateur", value=f"{mod.mention}\n`{mod}`", inline=True)
    e.add_field(name="⏰ Heure",        value=ts, inline=True)

    # Raison
    if reason and reason != "Aucune raison":
        e.add_field(name="📋 Raison", value=reason, inline=False)

    # Champs supplementaires selon l'action
    if extra:
        for k, v in extra.items():
            e.add_field(name=k, value=str(v), inline=True)

    # Compteur de sanctions
    try:
        sanctions = get_member("sanctions.json", guild.id, member.id).get("list", [])
        total     = len(sanctions)
        warns     = len([s for s in sanctions if s["type"] == "warn"])
        mutes     = len([s for s in sanctions if s["type"] in ("mute", "mute")])
        bans      = len([s for s in sanctions if s["type"] in ("ban", "softban")])
        e.add_field(
            name="📊 Historique",
            value=f"Total : `{total}` | ⚠️ `{warns}` | 🔇 `{mutes}` | 🔨 `{bans}`",
            inline=False
        )
    except: pass

    e.set_footer(text=f"ID membre : {member.id} • ID modérateur : {mod.id}")
    try:
        await send_log(guild, log_type, e)
    except Exception as ex:
        print(f"[log_mod] Erreur ({action}): {ex}")


async def get_mute_role(guild):
    cfg = get_guild("modconfig.json", guild.id)
    rid = cfg.get("muterole")
    r   = guild.get_role(int(rid)) if rid else None
    if not r: r = discord.utils.get(guild.roles, name="Muted")
    if not r:
        r = await guild.create_role(name="Muted")
        for ch in guild.channels:
            try: await ch.set_permissions(r, send_messages=False, speak=False, add_reactions=False)
            except: pass
    return r

async def do_punish(guild, member, ptype, reason, cfg=None):
    """
    ptype: delete | warn | mute | kick | ban | derank | timeout
    Si ptype == "timeout", cfg doit contenir "timeout_duration" en secondes.
    """
    try:
        if ptype == "delete":
            pass  # Le message est déjà supprimé avant l'appel
        elif ptype == "warn":
            await add_sanction(guild.id, member.id, "warn", reason, "AutoMod")
        elif ptype == "kick":
            await member.kick(reason=reason)
        elif ptype == "ban":
            await member.ban(reason=reason)
        elif ptype in ("mute", "muté"):
            r = await get_mute_role(guild)
            await member.add_roles(r, reason=reason)
        elif ptype == "derank":
            roles = [r for r in member.roles if r != guild.default_role and r.position < guild.me.top_role.position]
            await member.remove_roles(*roles, reason=reason)
        elif ptype == "timeout":
            duration = 600  # 10 min par defaut
            if cfg:
                duration = cfg.get("automod_timeout_duration", 600)
            until = discord.utils.utcnow() + __import__("datetime").timedelta(seconds=duration)
            await member.timeout(until, reason=reason)
        if ptype not in ("delete",):
            await add_sanction(guild.id, member.id, ptype, reason, "AutoMod")
    except Exception as ex:
        print(f"[do_punish] Erreur ({ptype}): {ex}")

@bot.event
async def on_ready():
    print(f"Pocoyo connecté : {bot.user} | Préfixe : {PREFIX} | Serveurs : {len(bot.guilds)}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="votre serveur"))
    # Charger le cache d'invitations
    for guild in bot.guilds:
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except: pass

@bot.command(name="reload")
async def reload_bot(ctx):
    if ctx.author.id not in OWNER_IDS:
        return
    msg = await ctx.send("🔄 Rechargement en cours...")
    try:
        # Recharge le fichier principal
        module_name = os.path.splitext(os.path.basename(__file__))[0]
        # Supprime et recharge toutes les commandes
        bot.remove_command("reload")
        new_commands = []
        for cmd in list(bot.commands):
            bot.remove_command(cmd.name)
        importlib.invalidate_caches()
        await msg.edit(content="✅ Rechargement impossible sans Cogs.\n💡 Utilise `+restart` pour redémarrer proprement le process.")
    except Exception as ex:
        await msg.edit(content=f"❌ Erreur : `{ex}`")

@bot.command(name="restart")
async def restart_bot(ctx):
    if ctx.author.id not in OWNER_IDS:
        return
    await ctx.send("🔄 Redémarrage du bot...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

class GuildJoinView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=None)
        self.guild = guild

    @discord.ui.button(label="Quitter le serveur", emoji="🚪", style=discord.ButtonStyle.danger, custom_id=f"gj_leave")
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        guild = bot.get_guild(self.guild.id)
        if not guild:
            return await interaction.response.edit_message(
                embed=discord.Embed(title="❌ Serveur introuvable", description="Le bot a peut-etre déjà quitté ce serveur.", color=0xff0000),
                view=None
            )
        # Confirmation
        confirm = GuildLeaveConfirmView(guild)
        e = discord.Embed(
            title="⚠️ Confirmer ?",
            description=f"Quitter **{guild.name}** (`{guild.id}`) ?",
            color=0xff4500
        )
        await interaction.response.edit_message(embed=e, view=confirm)

    @discord.ui.button(label="Rejoindre le serveur", emoji="🔗", style=discord.ButtonStyle.success, custom_id="gj_invite")
    async def invite_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        guild = bot.get_guild(self.guild.id)
        if not guild:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        try:
            channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).create_instant_invite), None)
            if not channel:
                return await interaction.response.send_message("Impossible de créer une invitation.", ephemeral=True)
            invite = await channel.create_invite(max_age=86400, max_uses=1, reason="Invite owner bot")
            await interaction.response.send_message(f"🔗 **Invitation :** {invite.url}\n*(Expire dans 24h, 1 utilisation)*", ephemeral=True)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

    @discord.ui.button(label="Envoyer un message", emoji="💬", style=discord.ButtonStyle.primary, custom_id="gj_msg")
    async def msg_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        guild = bot.get_guild(self.guild.id)
        if not guild:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        await interaction.response.send_modal(GuildMsgModal(guild))

    @discord.ui.button(label="Voir les infos", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="gj_info")
    async def info_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        guild = bot.get_guild(self.guild.id)
        if not guild:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        e = discord.Embed(title=f"📊 {guild.name}", color=get_color(guild.id), timestamp=datetime.utcnow())
        if guild.icon: e.set_thumbnail(url=guild.icon.url)
        e.add_field(name="🆔 ID",           value=str(guild.id), inline=True)
        e.add_field(name="👤 Owner",         value=f"{guild.owner}\n`{guild.owner_id}`", inline=True)
        e.add_field(name="👥 Membres",       value=str(guild.member_count), inline=True)
        bots   = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots
        e.add_field(name="🤖 Bots",          value=str(bots), inline=True)
        e.add_field(name="👨 Humains",        value=str(humans), inline=True)
        e.add_field(name="📌 Salons",         value=str(len(guild.channels)), inline=True)
        e.add_field(name="🏷️ Roles",          value=str(len(guild.roles)), inline=True)
        e.add_field(name="😀 Emojis",         value=str(len(guild.emojis)), inline=True)
        e.add_field(name="💎 Boosts",         value=f"{guild.premium_subscription_count} (Niv. {guild.premium_tier})", inline=True)
        e.add_field(name="📅 Créé le",        value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
        e.add_field(name="🔒 Vérification",   value=str(guild.vérification_level), inline=True)
        e.add_field(name="🌍 Langue",         value=str(guild.preferred_locale), inline=True)
        top_roles = [r.name for r in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not r.is_default()][:5]
        if top_roles: e.add_field(name="🏆 Top roles", value=", ".join(top_roles), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

class GuildLeaveConfirmView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=30)
        self.guild = guild

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        name = self.guild.name
        try:
            await self.guild.leave()
            e = discord.Embed(
                title="✅ Serveur quitté",
                description=f"Le bot a bien quitté **{name}**.",
                color=0x00ff00,
                timestamp=datetime.utcnow()
            )
            await interaction.response.edit_message(embed=e, view=None)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Annule.", ephemeral=True)
        self.stop()

class GuildMsgModal(discord.ui.Modal, title="Envoyer un message"):
    salon   = discord.ui.TextInput(label="ID du salon (laisser vidé = premier salon)", placeholder="123456789", required=False, max_length=20)
    message = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Votre message...", max_length=2000)

    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sid = str(self.salon).strip()
            if sid:
                channel = self.guild.get_channel(int(sid))
            else:
                channel = next((c for c in self.guild.text_channels if c.permissions_for(self.guild.me).send_messages), None)
            if not channel:
                return await interaction.response.send_message("Salon introuvable.", ephemeral=True)
            await channel.send(str(self.message))
            await interaction.response.send_message(f"✅ Message envoyé dans **#{channel.name}** sur **{self.guild.name}**.", ephemeral=True)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

def make_guild_join_embed(guild, joined=True):
    color = 0x00ff00 if joined else 0xff4500
    icon  = "📥" if joined else "📤"
    title = f"{icon} {'Nouveau serveur !' if joined else 'Serveur quitté'}"

    bots   = sum(1 for m in guild.members if m.bot)
    humans = guild.member_count - bots

    e = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    if guild.icon: e.set_thumbnail(url=guild.icon.url)
    if guild.banner: e.set_image(url=guild.banner.url)

    e.add_field(name="🏠 Serveur",      value=f"**{guild.name}**\n`{guild.id}`", inline=True)
    e.add_field(name="👤 Owner",         value=f"{guild.owner}\n`{guild.owner_id}`", inline=True)
    e.add_field(name="👥 Membres",       value=f"**{guild.member_count}** total\n👨 {humans} humains • 🤖 {bots} bots", inline=True)
    e.add_field(name="📌 Salons",         value=f"💬 {len(guild.text_channels)} texte\n🔊 {len(guild.voice_channels)} vocal", inline=True)
    e.add_field(name="🏷️ Roles",          value=str(len(guild.roles)), inline=True)
    e.add_field(name="💎 Boosts",         value=f"{guild.premium_subscription_count} (Niv. {guild.premium_tier})", inline=True)
    e.add_field(name="📅 Serveur créé le",value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    e.add_field(name="🔒 Vérification",   value=str(guild.vérification_level), inline=True)
    e.add_field(name="🌍 Langue",         value=str(guild.preferred_locale), inline=True)

    if joined:
        e.add_field(name="🌐 Total serveurs", value=f"Le bot est maintenant dans **{len(bot.guilds)}** serveurs.", inline=False)

    e.set_footer(text=f"Pocoyo • ID : {guild.id}")
    return e

@bot.event
async def on_guild_join(guild):
    for owner_id in OWNER_IDS:
        try:
            owner = await bot.fetch_user(owner_id)
            e     = make_guild_join_embed(guild, joined=True)
            view  = GuildJoinView(guild)
            await owner.send(embed=e, view=view)
        except Exception as ex:
            print(f"[on_guild_join] Impossible d'envoyer DM a {owner_id}: {ex}")

@bot.event
async def on_guild_remove(guild):
    for owner_id in OWNER_IDS:
        try:
            owner = await bot.fetch_user(owner_id)
            e     = make_guild_join_embed(guild, joined=False)
            await owner.send(embed=e)
        except Exception as ex:
            print(f"[on_guild_remove] Impossible d'envoyer DM a {owner_id}: {ex}")

# Multi-word command aliases (ex: "+end giveaway" -> "+end_giveaway")
MULTIWORD_CMDS = {
    "end giveaway":        "end_giveaway",
    "del sanction":        "del_sanction",
    "clear sanctions":     "clear_sanctions",
    "clear all sanctions": "clear_all_sanctions",
    "clear wl":            "clear_wl",
    "clear webhooks":      "clear_webhooks",
    "clear customs":       "clear_customs",
    "clear perms":         "clear_perms",
    "clear limit":         "clear_limit",
    "clear owners":        "clear_owners",
    "clear bl":            "clear_bl",
    "set muterole":        "set_muterole",
    "set boostembed":      "set_boostembed",
    "set perm":            "set_perm",
    "del perm":            "del_perm",
    "ticket settings":     "ticket_settings",
    "reminder list":       "reminder_list",
    "custom transfer":     "custom_transfer",
    "backup list":         "backup_list",
    "backup delete":       "backup_delete",
    "backup load":         "backup_load",
    "lb suggestions":      "lb_suggestions",
    "join settings":       "join_settings",
    "join channel":        "join_channel",
    "join role":           "join_role",
    "join message":        "join_message",
    "leave settings":      "leave_settings",
    "leave channel":       "leave_channel",
    "leave message":       "leave_message",
    "report settings":     "report_settings",
    "show pics":           "show_pics",
    "server pic":          "server_pic",
    "server banner":       "server_banner",
    "server list":         "server_list",
    "search wiki":         "search_wiki",
    "reset server":        "reset_server",
    "antiraid settings":   "antiraid_settings",
    "automod settings":    "automod",
    "réaction role":       "reactionrole",
    "sticky msg":          "stickymsg",
    "création limit":      "creation_limit",
    "clear badwords":      "badwords",
    "boostembed test":     "boostembed",
}

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        await bot.process_commands(message); return

    # Intercepte les commandes multi-mots et les redirige
    if message.content.startswith(PREFIX):
        body = message.content[len(PREFIX):]
        for phrase, cmd_name in MULTIWORD_CMDS.items():
            if body.lower().startswith(phrase):
                rest   = body[len(phrase):]
                # Pour "clear badwords", on passe "clear" comme arg
                if phrase == "clear badwords":
                    message.content = PREFIX + cmd_name + " clear" + rest
                else:
                    message.content = PREFIX + cmd_name + rest
                break
    cfg = get_guild("antiraid.json", message.guild.id)
    wl  = cfg.get("whitelist", [])
    if str(message.author.id) not in wl:
        if cfg.get("antispam"):
            limit = cfg.get("antispam_limit", 5); window = cfg.get("antispam_window", 5)
            now = datetime.utcnow().timestamp()
            caché = spam_cache[message.guild.id][message.author.id]
            caché.append(now)
            spam_cache[message.guild.id][message.author.id] = [t for t in caché if now - t < window]
            if len(spam_cache[message.guild.id][message.author.id]) >= limit:
                spam_cache[message.guild.id][message.author.id] = []
                try: await message.delete()
                except: pass
                await do_punish(message.guild, message.author, cfg.get("punish_antispam","mute"), "Spam détecté", cfg)
                e = discord.Embed(title="🔨 Automod - Antispam", description=f"{message.author.mention} sanctionné pour spam. Sanction : **{cfg.get('punish_antispam','mute')}**", color=0xff4500, timestamp=datetime.utcnow())
                await send_log(message.guild, "raidlog", e)
        if cfg.get("antilink"):
            mode = cfg.get("antilink_mode","all"); c = message.content.lower()
            inv = "discord.gg/" in c or "discord.com/invite/" in c
            lnk = "http://" in c or "https://" in c
            if (mode=="invite" and inv) or (mode=="all" and (inv or lnk)):
                try: await message.delete()
                except: pass
                await do_punish(message.guild, message.author, cfg.get("punish_antilink","warn"), "Lien interdit", cfg)
                e = discord.Embed(title="Antiraid - Antilink", description=f"{message.author.mention} : lien supprimé.", color=0xff4500, timestamp=datetime.utcnow())
                await send_log(message.guild, "raidlog", e)
        if cfg.get("badwords"):
            words = cfg.get("badwords_list",[])
            if any(w in message.content.lower() for w in words):
                try: await message.delete()
                except: pass
                e = discord.Embed(title="Antiraid - Badwords", description=f"{message.author.mention} : mot interdit supprimé.", color=0xff4500, timestamp=datetime.utcnow())
                await send_log(message.guild, "raidlog", e)
        if cfg.get("antimassmention") and len(message.mentions) >= cfg.get("antimassmention_limit",5):
            try: await message.delete()
            except: pass
            await do_punish(message.guild, message.author, cfg.get("punish_antimassmention","mute"), "Spam de mentions", cfg)
            e = discord.Embed(title="Antiraid - Antimassmention", description=f"{message.author.mention} : spam mentions.", color=0xff4500, timestamp=datetime.utcnow())
            await send_log(message.guild, "raidlog", e)
        if cfg.get("antieveryone") and cfg.get("antieveryone") != "off" and message.mention_everyone:
            try: await message.delete()
            except: pass
            await do_punish(message.guild, message.author, cfg.get("punish_antieveryone","warn"), "@everyone interdit", cfg)
            e = discord.Embed(title="Antiraid - Antieveryone", description=f"{message.author.mention} : @everyone supprimé.", color=0xff4500, timestamp=datetime.utcnow())
            await send_log(message.guild, "raidlog", e)
    mcfg    = get_guild("modconfig.json", message.guild.id)
    piconly = mcfg.get("piconly", [])
    if str(message.channel.id) in piconly and not message.attachments:
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention} Ce salon est reserve aux photos uniquement !", delete_after=5)
        except: pass
        return
    autoreacts = mcfg.get("autoreacts", {})
    for emoji in autoreacts.get(str(message.channel.id), []):
        try: await message.add_reaction(emoji)
        except: pass
    customs = get_guild("customs.json", message.guild.id)
    if message.content.startswith(PREFIX):
        keyword = message.content[len(PREFIX):].strip().lower().split()[0] if message.content[len(PREFIX):].strip() else ""
        if keyword in customs:
            await message.channel.send(customs[keyword]); return
    # Sticky message
    await on_message_sticky(message)
    await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild: return
    snipe_cache[message.channel.id] = message
    now = discord.utils.utcnow()
    e = discord.Embed(title="🗑️ Message supprimé", color=0xff4500, timestamp=now)
    e.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
    e.set_thumbnail(url=message.author.display_avatar.url)
    e.add_field(name="👤 Auteur",    value=f"{message.author.mention}\n`{message.author}` • `{message.author.id}`", inline=True)
    e.add_field(name="📌 Salon",     value=f"{message.channel.mention}\n`#{message.channel.name}`", inline=True)
    e.add_field(name="🕐 Envoyé",    value=f"<t:{int(message.created_at.timestamp())}:F>", inline=True)
    if message.content:
        content_val = message.content[:1024] if len(message.content) <= 1024 else message.content[:1021] + "..."
        e.add_field(name="📝 Contenu", value=content_val, inline=False)
    else:
        e.add_field(name="📝 Contenu", value="*Message sans texte*", inline=False)
    if message.attachments:
        e.add_field(name="📎 Pièces jointes", value="\n".join(f"[{a.filename}]({a.url})" for a in message.attachments[:5]), inline=False)
    if message.embeds:
        e.add_field(name="🖼️ Embeds", value=f"`{len(message.embeds)}` embed(s)", inline=True)
    # Qui a supprimé via audit log
    try:
        async for entry in message.guild.audit_logs(limit=1, action=discord.AuditLogAction.message_delete):
            if (now - entry.created_at.replace(tzinfo=None) if entry.created_at.tzinfo is None else now - entry.created_at).total_seconds() < 3:
                if entry.target.id == message.author.id:
                    e.add_field(name="🛡️ Supprimé par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID message : {message.id} • ID auteur : {message.author.id}")
    await send_log(message.guild, "messagelog", e)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild or before.content == after.content: return
    e = discord.Embed(title="✏️ Message modifié", color=0xffd700, timestamp=datetime.utcnow())
    e.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
    e.set_thumbnail(url=before.author.display_avatar.url)
    e.add_field(name="👤 Auteur",  value=f"{before.author.mention} `({before.author.id})`", inline=True)
    e.add_field(name="📌 Salon",   value=before.channel.mention, inline=True)
    e.add_field(name="🔗 Lien",    value=f"[Aller au message]({after.jump_url})", inline=True)
    e.add_field(name="📝 Avant",   value=before.content[:1024] or "*vide*", inline=False)
    e.add_field(name="✅ Apres",   value=after.content[:1024]  or "*vide*", inline=False)
    e.set_footer(text=f"ID message : {before.id}")
    await send_log(before.guild, "messagelog", e)

@bot.event
async def on_voice_state_update(member, before, after):
    channel_ref = after.channel or before.channel
    now = discord.utils.utcnow()

    # Connexion vocale
    if not before.channel and after.channel:
        e = discord.Embed(title="Connexion vocale", color=0x00ff00, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="Salon",  value=after.channel.name, inline=True)
        e.add_field(name="Heure",  value=f"<t:{int(now.timestamp())}:T>", inline=True)
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)
        return

    # Deconnexion vocale
    if before.channel and not after.channel:
        e = discord.Embed(title="Deconnexion vocale", color=0xff4500, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="Salon",  value=before.channel.name, inline=True)
        e.add_field(name="Heure",  value=f"<t:{int(now.timestamp())}:T>", inline=True)
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)
        return

    # Changement de salon vocal
    if before.channel and after.channel and before.channel != after.channel:
        e = discord.Embed(title="Changement vocal", color=0xffd700, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="De",     value=before.channel.name, inline=True)
        e.add_field(name="Vers",   value=after.channel.name, inline=True)
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)
        return

    # Micro coupe/active (self_mute)
    if before.self_mute != after.self_mute:
        statut = "coupé" if after.self_mute else "activé"
        e = discord.Embed(title=f"Micro {statut}", color=0xaaaaaa, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="Statut", value=f"{'🔇 Micro coupé' if after.self_mute else '🎙️ Micro activé'}", inline=True)
        if channel_ref: e.add_field(name="Salon", value=channel_ref.name, inline=True)
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)

    # Casque coupe/active (self_deaf)
    if before.self_deaf != after.self_deaf:
        statut = "coupé" if after.self_deaf else "activé"
        e = discord.Embed(title=f"Son {statut}", color=0xaaaaaa, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="Statut", value=f"{'🔕 Son coupé (casque)' if after.self_deaf else '🔊 Son activé (casque)'}", inline=True)
        if channel_ref: e.add_field(name="Salon", value=channel_ref.name, inline=True)
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)

    # Mute forcé par un modérateur
    if before.mute != after.mute:
        statut = "muté" if after.mute else "démuté"
        e = discord.Embed(title=f"Membre {statut} (vocal)", color=0xff8c00, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="Statut", value=f"{'🔇 Muté par un modérateur' if after.mute else '🔊 Démuté par un modérateur'}", inline=True)
        if channel_ref: e.add_field(name="Salon", value=channel_ref.name, inline=True)
        try:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if (now - entry.created_at.replace(tzinfo=None) if entry.created_at.tzinfo is None else now - entry.created_at).total_seconds() < 3:
                    e.add_field(name="Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
        except: pass
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)

    # Deafen forcé par un modérateur
    if before.deaf != after.deaf:
        statut = "deafen" if after.deaf else "undeafen"
        e = discord.Embed(title=f"Membre {statut} (vocal)", color=0xff8c00, timestamp=now)
        e.set_author(name=str(member), icon_url=member.display_avatar.url)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Membre", value=f"{member.mention} `({member.id})`", inline=True)
        e.add_field(name="Statut", value=f"{'🔕 Son coupé par un modérateur' if after.deaf else '🔊 Son rétabli par un modérateur'}", inline=True)
        if channel_ref: e.add_field(name="Salon", value=channel_ref.name, inline=True)
        try:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if (now - entry.created_at.replace(tzinfo=None) if entry.created_at.tzinfo is None else now - entry.created_at).total_seconds() < 3:
                    e.add_field(name="Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
        except: pass
        e.set_footer(text=f"ID : {member.id}")
        await send_log(member.guild, "voicelog", e)

@bot.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        now = discord.utils.utcnow()
        color = 0x00bfff if added else 0xff8c00
        title = ("✅ Rôle ajouté" if added else "❌ Rôle retiré") + (" & retiré" if added and removed else "")
        e = discord.Embed(title=title, color=color, timestamp=now)
        e.set_author(name=str(before), icon_url=before.display_avatar.url)
        e.set_thumbnail(url=before.display_avatar.url)
        e.add_field(name="👤 Membre",  value=f"{before.mention}\n`{before}` • `{before.id}`", inline=True)
        if added:   e.add_field(name="✅ Rôle(s) ajouté(s)",  value="\n".join(r.mention for r in added),   inline=True)
        if removed: e.add_field(name="❌ Rôle(s) retiré(s)",  value="\n".join(r.mention for r in removed), inline=True)
        e.add_field(name="⏰ Heure", value=f"<t:{int(now.timestamp())}:T>", inline=True)
        # Qui a modifié les rôles via audit log
        try:
            async for entry in before.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                if (now - entry.created_at.replace(tzinfo=None) if entry.created_at.tzinfo is None else now - entry.created_at).total_seconds() < 3:
                    e.add_field(name="🛡️ Par", value=f"{entry.user.mention}\n`{entry.user}`", inline=True)
        except: pass
        e.set_footer(text=f"ID membre : {before.id}")
        await send_log(before.guild, "rolelog", e)
    if before.nick != after.nick:
        e = discord.Embed(title="✏️ Surnom modifié", color=get_color(before.guild.id), timestamp=datetime.utcnow())
        e.set_author(name=str(before), icon_url=before.display_avatar.url)
        e.set_thumbnail(url=before.display_avatar.url)
        e.add_field(name="👤 Membre",   value=f"{before.mention} `({before.id})`", inline=False)
        e.add_field(name="📝 Avant",    value=before.nick or "*Aucun*", inline=True)
        e.add_field(name="✅ Apres",    value=after.nick  or "*Aucun*", inline=True)
        e.set_footer(text=f"ID : {before.id}")
        await send_log(before.guild, "rolelog", e)
    if not before.premium_since and after.premium_since:
        e = discord.Embed(title="💎 Nouveau boost !", color=0xff73fa, timestamp=datetime.utcnow())
        e.set_author(name=str(after), icon_url=after.display_avatar.url)
        e.set_thumbnail(url=after.display_avatar.url)
        e.add_field(name="👤 Membre",  value=f"{after.mention} `({after.id})`", inline=True)
        e.add_field(name="🚀 Boosts",  value=str(after.guild.premium_subscription_count), inline=True)
        e.add_field(name="⭐ Niveau",  value=str(after.guild.premium_tier), inline=True)
        e.set_footer(text=f"ID : {after.id}")
        await send_log(before.guild, "boostlog", e)

@bot.event
async def on_invite_create(invite):
    try:
        invites = await invite.guild.invites()
        invite_cache[invite.guild.id] = {inv.code: inv.uses for inv in invites}
    except: pass

@bot.event
async def on_invite_delete(invite):
    try:
        invites = await invite.guild.invites()
        invite_cache[invite.guild.id] = {inv.code: inv.uses for inv in invites}
    except: pass

async def get_invite_used(guild):
    """Compare le cache avant/apres pour trouver l'invitation utilisée."""
    try:
        new_invites = await guild.invites()
        old_uses    = invite_cache.get(guild.id, {})
        used_invite = None
        for inv in new_invites:
            old_use_count = old_uses.get(inv.code, 0)
            if inv.uses > old_use_count:
                used_invite = inv
                break
        # Mettre a jour le cache
        invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}
        return used_invite
    except:
        return None

@bot.event
async def on_member_join(member):
    age_delta  = datetime.utcnow() - member.created_at.replace(tzinfo=None)
    age_str    = f"{age_delta.days} jours"
    new_acct   = age_delta.days < 7
    used_inv   = await get_invite_used(member.guild)
    e = discord.Embed(
        title="📥 Membre rejoint",
        color=0xff4500 if new_acct else 0x00ff00,
        timestamp=datetime.utcnow()
    )
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre",      value=f"{member.mention}\n`{member} ({member.id})`", inline=True)
    e.add_field(name="📅 Compte créé", value=f"{member.created_at.strftime('%d/%m/%Y')}\n`{age_str}`", inline=True)
    e.add_field(name="👥 Membres",     value=str(member.guild.member_count), inline=True)
    if new_acct:
        e.add_field(name="⚠️ Compte recent", value="Ce compte a moins de 7 jours !", inline=False)
    if used_inv:
        inviter = used_inv.inviter
        e.add_field(name="🔗 Invitation", value=f"`{used_inv.code}` — utilisée `{used_inv.uses}` fois", inline=True)
        e.add_field(name="👤 Invité par", value=f"{inviter.mention} `({inviter})`" if inviter else "Inconnu", inline=True)
    e.set_footer(text=f"ID : {member.id}")
    await send_log(member.guild, "joinlog", e)
    jset = get_guild("joinsettings.json", member.guild.id)
    if jset.get("enabled") and jset.get("channel"):
        wch = member.guild.get_channel(int(jset["channel"]))
        if wch:
            text, embed = build_join_leave_msg(jset, member, used_inv)
            try: await wch.send(content=text, embed=embed)
            except: pass
    # Role auto 1
    for rkey in ("role", "role2"):
        rid = jset.get(rkey)
        if rid:
            role = member.guild.get_role(int(rid))
            if role:
                try: await member.add_roles(role)
                except: pass
    cfg = get_guild("antiraid.json", member.guild.id)
    if cfg.get("antitoken"):
        limit = cfg.get("antitoken_limit",10); window = cfg.get("antitoken_window",10)
        now = datetime.utcnow().timestamp()
        join_cache[member.guild.id].append(now)
        join_cache[member.guild.id] = [t for t in join_cache[member.guild.id] if now - t < window]
        if len(join_cache[member.guild.id]) >= limit:
            for ch in member.guild.text_channels:
                try: await ch.set_permissions(member.guild.default_role, send_messages=False)
                except: pass
            re2 = discord.Embed(title="RAID Détecté", description=f"{limit} membres ont rejoint en {window}s - serveur verrouillé !", color=0xff0000, timestamp=datetime.utcnow())
            await send_log(member.guild, "raidlog", re2)
    cl = cfg.get("creation_limit")
    if cl:
        age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).total_seconds()
        if age < cl: await member.kick(reason="Compte trop recent (antiraid)")

@bot.event
async def on_member_remove(member):
    roles = [r.mention for r in member.roles if r != member.guild.default_role]
    e = discord.Embed(title="📤 Membre parti", color=0xff0000, timestamp=datetime.utcnow())
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre",    value=f"{member.mention}\n`{member} ({member.id})`", inline=True)
    e.add_field(name="📅 A rejoint", value=member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "?", inline=True)
    e.add_field(name="👥 Membres",   value=str(member.guild.member_count), inline=True)
    if roles: e.add_field(name=f"🏷️ Roles ({len(roles)})", value=" ".join(roles[:10]), inline=False)
    e.set_footer(text=f"ID : {member.id}")
    await send_log(member.guild, "leavelog", e)
    lset = get_guild("leavesettings.json", member.guild.id)
    if lset.get("enabled") and lset.get("channel"):
        lch = member.guild.get_channel(int(lset["channel"]))
        if lch:
            text, embed = build_join_leave_msg(lset, member)
            try: await lch.send(content=text, embed=embed)
            except: pass

#  LOGS ANTIRAID - SUPPRESSION/MODIFICATION SALONS, ROLES, SERVEUR

@bot.event
async def on_guild_channel_delete(channel):
    e = discord.Embed(title="🗑️ Salon supprimé", color=0xff0000, timestamp=datetime.utcnow())
    e.add_field(name="📌 Nom",       value=f"#{channel.name}", inline=True)
    e.add_field(name="🗂️ Type",     value=str(channel.type), inline=True)
    e.add_field(name="📁 Catégorie", value=channel.category.name if channel.category else "Aucune", inline=True)
    e.add_field(name="🆔 ID",        value=str(channel.id), inline=True)
    # Tentative audit log
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID salon : {channel.id}")
    await send_log(channel.guild, "raidlog", e)

@bot.event
async def on_guild_channel_create(channel):
    e = discord.Embed(title="✅ Salon créé", color=0x00ff00, timestamp=datetime.utcnow())
    e.add_field(name="📌 Nom",       value=f"#{channel.name}", inline=True)
    e.add_field(name="🗂️ Type",     value=str(channel.type), inline=True)
    e.add_field(name="📁 Catégorie", value=channel.category.name if channel.category else "Aucune", inline=True)
    e.add_field(name="🆔 ID",        value=str(channel.id), inline=True)
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID salon : {channel.id}")
    await send_log(channel.guild, "raidlog", e)

@bot.event
async def on_guild_channel_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"**Nom :** `#{before.name}` → `#{after.name}`")
    if before.category != after.category:
        b = before.category.name if before.category else "Aucune"
        a = after.category.name  if after.category  else "Aucune"
        changes.append(f"**Categorie :** `{b}` → `{a}`")
    if hasattr(before, "topic") and before.topic != after.topic:
        changes.append(f"**Sujet :** `{before.topic or 'vidé'}` → `{after.topic or 'vidé'}`")
    if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
        changes.append(f"**Slowmode :** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
    if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
        changes.append(f"**NSFW :** `{before.nsfw}` → `{after.nsfw}`")
    if not changes: return
    e = discord.Embed(title="✏️ Salon modifié", color=0xffd700, timestamp=datetime.utcnow())
    e.add_field(name="📌 Salon",       value=after.mention, inline=True)
    e.add_field(name="🆔 ID",          value=str(after.id), inline=True)
    e.add_field(name="📝 Modifications", value="\n".join(changes), inline=False)
    try:
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID salon : {after.id}")
    await send_log(after.guild, "raidlog", e)

@bot.event
async def on_guild_role_create(role):
    e = discord.Embed(title="✅ Role créé", color=0x00ff00, timestamp=datetime.utcnow())
    e.add_field(name="🏷️ Nom",         value=role.name, inline=True)
    e.add_field(name="🎨 Couleur",      value=str(role.color), inline=True)
    e.add_field(name="📌 Mentionnable", value="Oui" if role.mentionable else "Non", inline=True)
    e.add_field(name="🆔 ID",           value=str(role.id), inline=True)
    try:
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID role : {role.id}")
    await send_log(role.guild, "raidlog", e)

@bot.event
async def on_guild_role_delete(role):
    e = discord.Embed(title="🗑️ Role supprimé", color=0xff0000, timestamp=datetime.utcnow())
    e.add_field(name="🏷️ Nom",    value=role.name, inline=True)
    e.add_field(name="🎨 Couleur",value=str(role.color), inline=True)
    e.add_field(name="🆔 ID",     value=str(role.id), inline=True)
    members_had = len(role.members)
    e.add_field(name="👥 Membres qui l'avaient", value=str(members_had), inline=True)
    try:
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID role : {role.id}")
    await send_log(role.guild, "raidlog", e)

@bot.event
async def on_guild_role_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"**Nom :** `{before.name}` → `{after.name}`")
    if before.color != after.color:
        changes.append(f"**Couleur :** `{before.color}` → `{after.color}`")
    if before.permissions != after.permissions:
        added_perms   = [p for p, v in after.permissions  if v and not getattr(before.permissions, p)]
        removed_perms = [p for p, v in before.permissions if v and not getattr(after.permissions,  p)]
        if added_perms:   changes.append(f"**Perms ajoutees :** `{'`, `'.join(added_perms)}`")
        if removed_perms: changes.append(f"**Perms retirees :** `{'`, `'.join(removed_perms)}`")
    if before.hoist != after.hoist:
        changes.append(f"**Affiche séparément :** `{before.hoist}` → `{after.hoist}`")
    if before.mentionable != after.mentionable:
        changes.append(f"**Mentionnable :** `{before.mentionable}` → `{after.mentionable}`")
    if not changes: return
    e = discord.Embed(title="✏️ Role modifié", color=0xffd700, timestamp=datetime.utcnow())
    e.add_field(name="🏷️ Role",          value=f"{after.mention} `({after.id})`", inline=True)
    e.add_field(name="📝 Modifications",  value="\n".join(changes), inline=False)
    try:
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID role : {after.id}")
    await send_log(after.guild, "raidlog", e)

@bot.event
async def on_guild_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"**Nom :** `{before.name}` → `{after.name}`")
    if before.icon != after.icon:
        changes.append("**Icone :** modifiée")
    if before.banner != after.banner:
        changes.append("**Banniere :** modifiée")
    if before.owner != after.owner:
        changes.append(f"**Propriétaire :** `{before.owner}` → `{after.owner}`")
    if before.vérification_level != after.vérification_level:
        changes.append(f"**Niveau vérif :** `{before.vérification_level}` → `{after.vérification_level}`")
    if before.default_notifications != after.default_notifications:
        changes.append(f"**Notifs :** `{before.default_notifications}` → `{after.default_notifications}`")
    if before.afk_channel != after.afk_channel:
        b = before.afk_channel.name if before.afk_channel else "Aucun"
        a = after.afk_channel.name  if after.afk_channel  else "Aucun"
        changes.append(f"**Salon AFK :** `{b}` → `{a}`")
    if not changes: return
    e = discord.Embed(title="⚙️ Serveur modifié", color=0xff8c00, timestamp=datetime.utcnow())
    if after.icon: e.set_thumbnail(url=after.icon.url)
    e.add_field(name="🏠 Serveur",        value=f"`{after.name}` ({after.id})", inline=False)
    e.add_field(name="📝 Modifications",  value="\n".join(changes), inline=False)
    try:
        async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID serveur : {after.id}")
    await send_log(after, "raidlog", e)

@bot.event
async def on_webhooks_update(channel):
    e = discord.Embed(title="🔗 Webhooks modifiés", color=0xff4500, timestamp=datetime.utcnow())
    e.add_field(name="📌 Salon", value=channel.mention, inline=True)
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
            e.add_field(name="👤 Par",      value=f"{entry.user.mention} `({entry.user})`", inline=True)
            e.add_field(name="🔗 Webhook",  value=entry.target.name if hasattr(entry.target, "name") else "?", inline=True)
    except: pass
    e.set_footer(text=f"ID salon : {channel.id}")
    await send_log(channel.guild, "raidlog", e)

@bot.event
async def on_member_ban(guild, user):
    e = discord.Embed(title="🔨 Membre banni", color=0xff0000, timestamp=datetime.utcnow())
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="👤 Membre", value=f"`{user} ({user.id})`", inline=True)
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            e.add_field(name="👤 Par",    value=f"{entry.user.mention} `({entry.user})`", inline=True)
            e.add_field(name="📋 Raison", value=entry.reason or "Aucune", inline=False)
    except: pass
    e.set_footer(text=f"ID : {user.id}")
    await send_log(guild, "raidlog", e)

@bot.event
async def on_member_unban(guild, user):
    e = discord.Embed(title="✅ Membre débanni", color=0x00ff00, timestamp=datetime.utcnow())
    e.set_thumbnail(url=user.display_avatar.url)
    e.add_field(name="👤 Membre", value=f"`{user} ({user.id})`", inline=True)
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            e.add_field(name="👤 Par", value=f"{entry.user.mention} `({entry.user})`", inline=True)
    except: pass
    e.set_footer(text=f"ID : {user.id}")
    await send_log(guild, "raidlog", e)

@bot.event
async def on_raw_reaction_add(payload):
    if not payload.guild_id: return
    data = get_guild("rolemenus.json", payload.guild_id)
    menu = data.get(str(payload.message_id))
    if not menu: return
    guild  = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id) if guild else None
    if not member or member.bot: return
    for rid, emoji in menu.items():
        if emoji == str(payload.emoji):
            role = guild.get_role(int(rid))
            if role:
                try: await member.add_roles(role)
                except: pass
            break

@bot.event
async def on_raw_reaction_remove(payload):
    if not payload.guild_id: return
    data = get_guild("rolemenus.json", payload.guild_id)
    menu = data.get(str(payload.message_id))
    if not menu: return
    guild  = bot.get_guild(payload.guild_id)
    member = guild.get_member(payload.user_id) if guild else None
    if not member: return
    for rid, emoji in menu.items():
        if emoji == str(payload.emoji):
            role = guild.get_role(int(rid))
            if role:
                try: await member.remove_roles(role)
                except: pass
            break

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Tu n'as pas la permission d'utiliser cette commande.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("Membre introuvable.")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send("Role introuvable.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Argument manquant : `{error.param.name}` - utilise `+help`.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Erreur : {error}")

def build_embeds(guild=None):
    footer = "Pocoyo - Préfixe actuel : +"
    note   = "*Les paramètres peuvent être des noms, des mentions, ou des IDs*"
    embeds = {}

    e = discord.Embed(title="🛠️ Utilitaire", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+changelogs", "Affiché les dernieres notes de mise a jour"),
        ("+allbots", "Liste des bots presents sur le serveur"),
        ("+alladmins", "Liste des membres ayant la permission administrateur"),
        ("+botadmins", "Liste des bots ayant la permission administrateur"),
        ("+boosters", "Liste des membres boostant le serveur"),
        ("+rolemembers <role>", "Liste des membres ayant un role precis"),
        ("+serverinfo", "Informations relatives au serveur"),
        ("+vocinfo", "Informations relatives a l'activité vocale"),
        ("+role <role>", "Informations relatives a un role"),
        ("+channel [salon]", "Informations relatives a un salon"),
        ("+user [membre]", "Informations relatives a un utilisateur"),
        ("+member [membre]", "Informations relatives a un membre sur le serveur"),
        ("+pic [membre]", "Recupere la photo de profil"),
        ("+banner [membre]", "Recupere la banniere"),
        ("+server banner", "Recupere la banniere du serveur"),
        ("+snipe", "Dernier message supprimé du salon"),
        ("+emoji <emoji>", "Recupere l'image d'un emoji custom"),
        ("+image <mot-cle>", "Recherche Google Images"),
        ("+suggestion <message>", "Poste une suggestion sur le serveur"),
        ("+wiki <mot-cle>", "Recherche Wikipedia"),
        ("+calc <calcul>", "Resout des calculs ou des equations"),
        ("+pocoyo", "Invitation pour le serveur de support"),
        ("+avatar", "Photo de profil avec bouton navigateur"),
        ("+id", "Retourne l'ID de n'importe quoi"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["utilitaire"] = e

    e = discord.Embed(title="🤖 Controle du bot", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+setname <nom>", "Change le nom du bot"),
        ("+setpic <lien>", "Change la photo de profil du bot"),
        ("+setbanner <lien>", "Change la banniere du bot"),
        ("+setprofil", "Modifié le profil du bot en interactif"),
        ("+theme <couleur>", "Change la couleur des embeds"),
        ("+playto / +listen / +watch", "Change l'activité du bot"),
        ("+compet / +stream", "Activité competition ou stream"),
        ("+removeactivity", "Supprimé l'activité du bot"),
        ("+online / +idle / +dnd / +invisible", "Change le statut du bot"),
        ("+mp <membre> <message>", "Envoie un MP a un membre"),
        ("+server list", "Liste des serveurs du bot"),
        ("+owner [membre]", "Donne/affiche les owners du bot"),
        ("+unowner <membre>", "Retiré le grade owner"),
        ("+clear owners", "Supprimé tous les owners"),
        ("+bl [membre] [raison]", "Ajoute/affiche la blacklist du bot"),
        ("+unbl <membre>", "Retiré de la blacklist"),
        ("+blinfo <membre>", "Infos blacklist d'un membre"),
        ("+clear bl", "Vidé la blacklist du bot"),
        ("+say <message>", "Fait dire au bot le message voulu"),
        ("+prefix <prefixe>", "Change le préfixe sur ce serveur"),
        ("+reset server", "Réinitialisé les paramètres de ce serveur"),
        ("+resetall", "Réinitialisé tous les paramètres du bot"),
        ("+permchannel <membre>", "Coche toutes les permissions pour un membre"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["controle"] = e

    e = discord.Embed(title="🛡️ Antiraid", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+secur [on/off/max]", "Affiche/modifie tous les paramètres antiraid d'un coup"),
        ("+raidlog <on/off> [salon]", "Activé les logs de l'antiraid"),
        ("+raidping <role>", "Role mentionné en cas de raid"),
        ("+antitoken <on/off/lock>", "Anti-raid en cas d'arrivée massive"),
        ("+antitoken <nombre>/<duree>", "Règle la sensibilite de l'antitoken"),
        ("+creation_limit <secondes>", "Age minimum d'un compte pour rejoindre"),
        ("+antispam <on/off> ou <nb>/<duree>", "Protection et reglage anti-spam"),
        ("+antilink <on/off> ou invite/all", "Protection anti-liens"),
        ("+antimassmention <on/off> ou <nb>", "Protection anti-spam de mentions"),
        ("+antieveryone <on/off/max>", "Protection contre @everyone"),
        ("+antirole <on/off/max/danger/all>", "Protection contre les modifs de roles"),
        ("+antiwebhook <on/off/max>", "Protection contre les webhooks"),
        ("+antiunban <on/off/max>", "Protection contre les unbans"),
        ("+antibot <on/off/max>", "Protection contre l'ajout de bots"),
        ("+antideco <on/off/max>", "Protection contre les deconnexions en masse"),
        ("+antiupdate / +antichannel", "Protection contre modifs serveur/salons"),
        ("+clear webhooks", "Supprimé tous les webhooks du serveur"),
        ("+badwords <on/off>", "Protection contre les mots interdits"),
        ("+badwords <add/del/list/clear> [mot]", "Gestion de la liste de mots interdits"),
        ("+punition <type> <sanction>", "Définit la punition d'un module antiraid"),
        ("+blrank <on/off/add/del>", "Blacklist rank"),
        ("+wl [membre]", "Ajoute/affiche la whitelist antiraid"),
        ("+unwl <membre>", "Retiré de la whitelist"),
        ("+clear wl", "Vidé la whitelist antiraid"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["antiraid"] = e

    e = discord.Embed(title="⚙️ Gestion du serveur", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+giveaway", "Créé un giveaway interactif"),
        ("+end giveaway <ID> / +reroll", "Terminé ou rejoue un giveaway"),
        ("+embed", "Generateur d'embed interactif"),
        ("+backup <serveur/emoji> [nom]", "Créé une backup du serveur ou emojis"),
        ("+backup list/delete/load", "Gestion des backups"),
        ("+autobackup <type> <jours>", "Backups automatiques"),
        ("+loading <duree> <message>", "Barre de chargement"),
        ("+massiverole / +unmassiverole", "Ajoute/retire un role a tous les membres"),
        ("+temprole <membre> <role> <duree>", "Role temporaire"),
        ("+voicemove <salon1> <salon2>", "Déplacé tous les membres d'un vocal"),
        ("+voicekick / +cleanup / +bringall", "Gestion des membres en vocal"),
        ("+renew [salon]", "Supprimé et recree un salon"),
        ("+slowmode <duree> [salon]", "Mode lent (max 6h)"),
        ("+sync <salon/all>", "Synchronisé les permissions avec la catégorie"),
        ("+autoreact <add/del/list>", "Réactions automatiques sur un salon"),
        ("+rolemenu", "Menu de roles interactif"),
        ("+ticket settings", "Panneau de configuration complet des tickets"),
        ("+claim / +rename / +add / +close", "Gestion des tickets"),
        ("+reminder <duree> <message>", "Créé un rappel"),
        ("+custom <mot-cle> <réponse>", "Commande personnalisee"),
        ("+customlist / +clear customs", "Gestion des commandes custom"),
        ("+suggestion / +suggestion settings", "Système de suggestions"),
        ("+join settings / +leave settings", "Actions a l'arrivee/depart d'un membre"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["gestion"] = e

    e = discord.Embed(title="⚙️ Gestion du serveur (suite)", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+boostembed <on/off/test>", "Embeds de boost"),
        ("+set boostembed", "Configuré l'embed de boost"),
        ("+autodelete <cible> <on/off/duree>", "Suppression automatique"),
        ("+piconly <add/del> [salon]", "Salon photos uniquement"),
        ("+restrict / +unrestrict <emoji>", "Restreindre un emoji a un role"),
        ("+public <on/off>", "Commandes publiques"),
        ("+set perm <permission> <role>", "Donne une permission a un role"),
        ("+del perm <role>", "Supprimé les permissions d'un role"),
        ("+clear perms", "Supprimé toutes les permissions"),
        ("+stickymsg off", "Supprime le message epingle"),
        ("+tempvoc", "Systeme de vocaux temporaires"),
        ("+antiraid settings", "Panneau antiraid avance (anti kick, ban, channel...)"),
        ("+automod", "Panneau de configuration de l'automod"),
        ("+color <hex>", "Apercu d'une couleur hex"),
        ("+set muterole", "Definit le role muet sur un role existant"),
        ("+create [emoji] <nom>", "Copie un ou plusieurs emojis sur ce serveur"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["gestion2"] = e

    e = discord.Embed(title="📋 Logs", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+settings", "Affiché les paramètres des logs"),
        ("+modlog on/off [salon]", "Logs de moderation"),
        ("+voicelog on/off [salon]", "Logs de l'activité vocale"),
        ("+boostlog on/off [salon]", "Logs de boosts"),
        ("+rolelog on/off [salon]", "Logs des roles"),
        ("+raidlog on/off [salon]", "Logs de l'antiraid"),
        ("+joinlog on/off [salon]", "Logs d'arrivees"),
        ("+leavelog on/off [salon]", "Logs de departs"),
        ("+autoconfiglog", "Créé automatiquement tous les salons de logs"),
        ("+nolog <add/del> [salon]", "Désactivé les logs dans un salon specifique"),
        ("+antiraid settings", "Panneau antiraid avance"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["logs"] = e

    e = discord.Embed(title="⚖️ Paramètres de modération", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+muterole", "Créé ou met a jour le role muet"),
        ("+set muterole <role>", "Définit le role muet"),
        ("+clear limit <nombre>", "Limite de la commande +clear"),
        ("+strikes [declencheur] [nombre]", "Gestion des strikes"),
        ("+ancien <duree>", "Durée pour etre considere comme ancien"),
        ("+punish", "Affiché les sanctions automatiques"),
        ("+punish add <nb> <duree> <sanction>", "Ajouté une sanction automatique"),
        ("+punish del <numero>", "Supprimé une sanction automatique"),
        ("+punish setup", "Remet les sanctions par defaut"),
        ("+noderank <add/del> <role>", "Role non supprimé lors d'un derank"),
        ("+piconly <add/del> [salon]", "Salon a photos uniquement"),
        ("+join settings / +leave settings", "Paramètres d'arrivée et de départ"),
        ("+public <on/off>", "Commandes publiques on/off"),
        ("+set muterole <role>", "Definit le role muet sur un role existant"),
        ("+timeout <membre> <duree> [raison]", "Timeout natif Discord (max 28 jours)"),
        ("+untimeout <membre>", "Leve le timeout d'un membre"),
        ("+softban <membre> [raison]", "Ban + unban immediat, supprime les messages 7j"),
        ("+unhoist", "Retire les caracteres speciaux des pseudos"),
        ("+massban <ID1> <ID2>...", "Bannit plusieurs membres par ID"),
        ("+unmuteall", "Demute tous les membres mutes"),
        ("+purge <bots/humans/links/images>", "Supprime des messages par type"),
        ("+create emoji", "Cree un emoji custom depuis un lien ou image"),
        ("+nuke", "Clone le salon (supprime et recree)"),
        ("+reactionrole", "Reaction role sur un message existant"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["modparams"] = e

    e = discord.Embed(title="🔨 Modération", color=get_color(guild.id) if guild else 0x1a0a2e)
    e.description = note
    for cmd, desc in [
        ("+warn <membre> [raison]", "Avertissement"),
        ("+mute <membre> [raison]", "Muté permanent"),
        ("+unmute <membre>", "Fin du muté"),
        ("+mutelist / +unmuteall", "Liste des mutes / Demuter tout le monde"),
        ("+cmute <membre> [raison]", "Muté sur le salon actuel"),
        ("+tempcmute <membre> <duree> [raison]", "Muté temporaire sur le salon actuel"),
        ("+uncmute <membre>", "Fin du cmute"),
        ("+kick <membre> [raison]", "Expulsé un membre"),
        ("+ban <membre> [raison]", "Bannit un membre"),
        ("+unban <membre>", "Deban un membre"),
        ("+banlist / +unbanall", "Liste des bans / Debannir tout le monde"),
        ("+clear [nombre] [membre]", "Supprimé des messages"),
        ("+sanctions <membre>", "Affiché les sanctions d'un membre"),
        ("+del sanction <membre> <numero>", "Supprimé une sanction"),
        ("+addrole / +delrole <membre> <role>", "Ajoute/retire un role"),
        ("+derank <membre>", "Supprimé tous les roles d'un membre"),
        ("+lock / +unlock [salon]", "Verrouille/deverrouille un salon"),
        ("+lockall / +unlockall", "Verrouille/deverrouille tous les salons"),
        ("+hide / +unhide [salon]", "Cache/affiche un salon"),
        ("+hideall / +unhideall", "Cache/affiche tous les salons"),
        ("+renew [salon]", "Supprimé et recree un salon"),
        ("+permchannel <membre>", "Toutes les permissions pour un membre"),
        ("+warnlist", "Liste de tous les membres avec des avertissements"),
        ("+clear sanctions @membre/all", "Supprime les sanctions d'un membre ou de tous"),
    ]: e.add_field(name=f"**{cmd}**", value=desc, inline=False)
    e.set_footer(text=footer)
    embeds["moderation"] = e

    return embeds

PAGES = ["utilitaire", "controle", "antiraid", "gestion", "gestion2", "logs", "modparams", "moderation"]
PAGE_LABELS = {
    "utilitaire": "🛠️ Utilitaire",
    "controle":   "🤖 Controle bot",
    "antiraid":   "🛡️ Antiraid",
    "gestion":    "⚙️ Gestion (1/2)",
    "gestion2":   "⚙️ Gestion (2/2)",
    "logs":       "📋 Logs",
    "modparams":  "⚖️ Mod. Params",
    "moderation": "🔨 Moderation",
}

class HelpView(discord.ui.View):
    def __init__(self, ctx, embeds, current_page="utilitaire"):
        super().__init__(timeout=120)
        self.ctx          = ctx
        self.embeds       = embeds
        self.current_page = current_page
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        idx = PAGES.index(self.current_page)

        # Bouton precedent
        prev_btn = discord.ui.Button(
            label="◀ Precedent",
            style=discord.ButtonStyle.secondary,
            disabled=(idx == 0),
            custom_id="prev"
        )
        prev_btn.callback = self.prev_callback
        self.add_item(prev_btn)

        # Bouton page actuelle (indicateur)
        page_btn = discord.ui.Button(
            label=f"{idx+1}/{len(PAGES)} - {PAGE_LABELS[self.current_page]}",
            style=discord.ButtonStyle.primary,
            disabled=True,
            custom_id="current"
        )
        self.add_item(page_btn)

        # Bouton suivant
        next_btn = discord.ui.Button(
            label="Suivant ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(idx == len(PAGES) - 1),
            custom_id="next"
        )
        next_btn.callback = self.next_callback
        self.add_item(next_btn)

        # Select menu pour aller directement a une page
        select = discord.ui.Select(
            placeholder="Aller directement a une catégorie...",
            options=[
                discord.SelectOption(
                    label=PAGE_LABELS[p],
                    value=p,
                    default=(p == self.current_page)
                ) for p in PAGES
            ],
            custom_id="select_page"
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def prev_callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce menu ne t'appartient pas.", ephemeral=True)
        idx = PAGES.index(self.current_page)
        self.current_page = PAGES[idx - 1]
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def next_callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce menu ne t'appartient pas.", ephemeral=True)
        idx = PAGES.index(self.current_page)
        self.current_page = PAGES[idx + 1]
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce menu ne t'appartient pas.", ephemeral=True)
        self.current_page = interaction.data["values"][0]
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except: pass

@bot.command(name="help")
async def help_cmd(ctx):
    embeds = build_embeds(ctx.guild)
    view   = HelpView(ctx, embeds)
    msg    = await ctx.send(embed=embeds["utilitaire"], view=view)
    view.message = msg

@bot.command(name="warn")
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="Aucune raison"):
    await add_sanction(ctx.guild.id, member.id, "warn", reason, ctx.author.id)
    count = len(get_member("sanctions.json", ctx.guild.id, member.id).get("list", []))
    await ctx.send(f"{member.mention} a recu un avertissement. Raison : {reason} ({count} warn(s) au total)")
    await log_mod(ctx.guild, "warn", member, ctx.author, reason)

@bot.command(name="mute")
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason="Aucune raison"):
    role = await get_mute_role(ctx.guild)
    await member.add_roles(role, reason=reason)
    await add_sanction(ctx.guild.id, member.id, "mute", reason, ctx.author.id)
    await ctx.send(f"{member.mention} a ete mute. Raison : {reason}")
    await log_mod(ctx.guild, "mute", member, ctx.author, reason)



@bot.command(name="unmute")
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    cfg = get_guild("modconfig.json", ctx.guild.id); rid = cfg.get("muterole")
    role = ctx.guild.get_role(int(rid)) if rid else discord.utils.get(ctx.guild.roles, name="Muted")
    if role and role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f"{member.mention} a ete unmute.")
        await log_mod(ctx.guild, "unmute", member, ctx.author)
    else: await ctx.send("Ce membre n'est pas mute.")

@bot.command(name="cmute")
@commands.has_permissions(manage_roles=True)
async def cmute(ctx, member: discord.Member, *, reason="Aucune raison"):
    await ctx.channel.set_permissions(member, send_messages=False)
    await add_sanction(ctx.guild.id, member.id, "cmute", reason, ctx.author.id)
    e = discord.Embed(title="Cmute", color=0xff8c00)
    e.add_field(name="Membre", value=str(member)); e.add_field(name="Salon", value=ctx.channel.mention); e.add_field(name="Raison", value=reason)
    await ctx.send(embed=e)

@bot.command(name="tempcmute")
@commands.has_permissions(manage_roles=True)
async def tempcmute(ctx, member: discord.Member, duration: str, *, reason="Aucune raison"):
    delta = parse_dur(duration)
    if not delta: return await ctx.send("Durée invalide. Ex: `10m`, `2h`")
    await ctx.channel.set_permissions(member, send_messages=False)
    await add_sanction(ctx.guild.id, member.id, "tempcmute", f"{duration} - {reason}", ctx.author.id)
    e = discord.Embed(title="Cmute temporaire", color=0xff8c00)
    e.add_field(name="Membre", value=str(member)); e.add_field(name="Durée", value=duration); e.add_field(name="Raison", value=reason)
    await ctx.send(embed=e)
    await asyncio.sleep(delta.total_seconds())
    await ctx.channel.set_permissions(member, send_messages=None)

@bot.command(name="uncmute")
@commands.has_permissions(manage_roles=True)
async def uncmute(ctx, member: discord.Member):
    await ctx.channel.set_permissions(member, send_messages=None)
    await ctx.send(f"**{member}** peut de nouveau ecrire dans {ctx.channel.mention}.")

@bot.command(name="mutelist")
@commands.has_permissions(manage_roles=True)
async def mutelist(ctx):
    cfg = get_guild("modconfig.json", ctx.guild.id); rid = cfg.get("muterole")
    role = ctx.guild.get_role(int(rid)) if rid else discord.utils.get(ctx.guild.roles, name="Muted")
    if not role: return await ctx.send("Aucun role muet configuré. Utilise `+muterole`.")
    muted = [m for m in ctx.guild.members if role in m.roles]
    if not muted: return await ctx.send("Aucun membre actuellement muté.")
    e = discord.Embed(title=f"Membres mutes ({len(muted)})", color=0xff8c00)
    e.description = "\n".join(f"- {m.mention}" for m in muted[:20])
    await ctx.send(embed=e)

@bot.command(name="unmuteall")
@commands.has_permissions(administrator=True)
async def unmuteall(ctx):
    cfg = get_guild("modconfig.json", ctx.guild.id); rid = cfg.get("muterole")
    role = ctx.guild.get_role(int(rid)) if rid else discord.utils.get(ctx.guild.roles, name="Muted")
    if not role: return await ctx.send("Aucun role muet configuré.")
    muted = [m for m in ctx.guild.members if role in m.roles]
    for m in muted:
        try: await m.remove_roles(role)
        except: pass
    await ctx.send(f"**{len(muted)}** membre(s) demute(s).")

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="Aucune raison"):
    await add_sanction(ctx.guild.id, member.id, "kick", reason, ctx.author.id)
    await member.kick(reason=reason)
    await ctx.send(f"{member} a ete expulse. Raison : {reason}")
    await log_mod(ctx.guild, "kick", member, ctx.author, reason)

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Aucune raison"):
    await add_sanction(ctx.guild.id, member.id, "ban", reason, ctx.author.id)
    await member.ban(reason=reason)
    await ctx.send(f"{member} a ete banni. Raison : {reason}")
    await log_mod(ctx.guild, "ban", member, ctx.author, reason)


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, member_str: str):
    bans   = [b async for b in ctx.guild.bans()]
    target = next((b.user for b in bans if str(b.user.id) == member_str or str(b.user) == member_str), None)
    if not target: return await ctx.send("Membre introuvable dans les bans.")
    await ctx.guild.unban(target)
    await ctx.send(f"{target} a ete debanni.")

@bot.command(name="banlist")
@commands.has_permissions(ban_members=True)
async def banlist(ctx):
    bans = [b async for b in ctx.guild.bans()]
    if not bans: return await ctx.send("Aucun membre banni.")
    e = discord.Embed(title=f"Bans ({len(bans)})", description="\n".join(f"- {b.user} ({b.user.id}) - {b.reason or 'Aucune raison'}" for b in bans[:20]), color=0xff0000)
    await ctx.send(embed=e)

@bot.command(name="unbanall")
@commands.has_permissions(administrator=True)
async def unbanall(ctx):
    bans = [b async for b in ctx.guild.bans()]
    msg  = await ctx.send(f"Debannissement de {len(bans)} membre(s)...")
    count = 0
    for b in bans:
        try: await ctx.guild.unban(b.user); count += 1
        except: pass
    await msg.edit(content=f"**{count}** membre(s) debanni(s).")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10, member: discord.Member = None):
    check   = (lambda m: member is None or m.author == member)
    deleted = await ctx.channel.purge(limit=amount, check=check)
    msg = await ctx.send(f"{ctx.author.mention} a supprime {len(deleted)} message(s).")
    await asyncio.sleep(3); await msg.delete()

@bot.command(name="sanctions")
@commands.has_permissions(manage_messages=True)
async def sanctions(ctx, member: discord.Member):
    data  = get_member("sanctions.json", ctx.guild.id, member.id)
    slist = data.get("list", [])
    if not slist: return await ctx.send(f"**{member}** n'a aucune sanction.")
    e = discord.Embed(title=f"Sanctions de {member}", color=0xff8c00)
    for i, s in enumerate(slist[-10:], 1):
        e.add_field(name=f"#{i} - {s['type'].upper()}", value=f"Raison : {s['reason']}\nDate : {s['date'][:10]}", inline=False)
    e.set_footer(text=f"Total : {len(slist)} sanction(s)")
    await ctx.send(embed=e)

@bot.command(name="del_sanction")
@commands.has_permissions(manage_messages=True)
async def del_sanction(ctx, member: discord.Member, number: int):
    data  = get_member("sanctions.json", ctx.guild.id, member.id); slist = data.get("list", [])
    if number < 1 or number > len(slist): return await ctx.send("Numéro invalide.")
    removed = slist.pop(number - 1); data["list"] = slist
    set_member("sanctions.json", ctx.guild.id, member.id, data)
    await ctx.send(f"Sanction #{number} ({removed['type']}) supprimée pour **{member}**.")

@bot.command(name="clear_sanctions")
@commands.has_permissions(administrator=True)
async def clear_sanctions(ctx, cible: str = None):
    """Usage : +clear sanctions @membre  OU  +clear sanctions all"""
    # Si pas d'argument, afficher l'aide
    if not cible:
        e = discord.Embed(title="Clear sanctions", color=get_color(ctx.guild.id))
        e.add_field(name="Utilisation", value="`+clear sanctions @membre` — Supprime les sanctions d'un membre\n`+clear sanctions all` — Supprime toutes les sanctions du serveur", inline=False)
        return await ctx.send(embed=e)

    # Cas all
    if cible.lower() == "all":
        view = ClearSanctionsConfirmView(ctx, None)
        await ctx.send(f"Confirmer la suppression de **toutes** les sanctions du serveur ?", view=view)
        return

    # Cas membre
    try:
        member = await commands.MemberConverter().convert(ctx, cible)
    except:
        return await ctx.send("Membre introuvable. Usage : `+clear sanctions @membre` ou `+clear sanctions all`")

    view = ClearSanctionsConfirmView(ctx, member)
    await ctx.send(f"Confirmer la suppression de toutes les sanctions de **{member}** ?", view=view)

class ClearSanctionsConfirmView(discord.ui.View):
    def __init__(self, ctx, member):
        super().__init__(timeout=30)
        self.ctx    = ctx
        self.member = member

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        if self.member:
            set_member("sanctions.json", self.ctx.guild.id, self.member.id, {"list": []})
            await interaction.response.edit_message(content=f"Sanctions de **{self.member}** supprimées.", view=None)
        else:
            data = db_load("sanctions.json"); data[str(self.ctx.guild.id)] = {}; db_save("sanctions.json", data)
            await interaction.response.edit_message(content="Toutes les sanctions du serveur supprimées.", view=None)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        await interaction.response.edit_message(content="Annulé.", view=None)
        self.stop()

# Alias clear_all_sanctions pour la compatibilite
@bot.command(name="clear_all_sanctions")
@commands.has_permissions(administrator=True)
async def clear_all_sanctions(ctx):
    view = ClearSanctionsConfirmView(ctx, None)
    await ctx.send("Confirmer la suppression de **toutes** les sanctions du serveur ?", view=view)

@bot.command(name="addrole")
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role); await ctx.send(f"{member.mention} a recu le role **{role.name}**.")

@bot.command(name="delrole")
@commands.has_permissions(manage_roles=True)
async def delrole(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role); await ctx.send(f"{member.mention} a perdu le role **{role.name}**.")

@bot.command(name="derank")
@commands.has_permissions(manage_roles=True)
async def derank(ctx, member: discord.Member):
    roles = [r for r in member.roles if r != ctx.guild.default_role and r.position < ctx.guild.me.top_role.position]
    await member.remove_roles(*roles); await ctx.send(f"Tous les roles de **{member}** supprimés.")

@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"**#{channel.name}** verrouillé.")

@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"**#{channel.name}** déverrouillé.")

@bot.command(name="lockall")
@commands.has_permissions(administrator=True)
async def lockall(ctx):
    for ch in ctx.guild.text_channels:
        try: await ch.set_permissions(ctx.guild.default_role, send_messages=False)
        except: pass
    await ctx.send("Tous les salons verrouilles.")

@bot.command(name="unlockall")
@commands.has_permissions(administrator=True)
async def unlockall(ctx):
    for ch in ctx.guild.text_channels:
        try: await ch.set_permissions(ctx.guild.default_role, send_messages=True)
        except: pass
    await ctx.send("Tous les salons deverrouilles.")

@bot.command(name="hide")
@commands.has_permissions(manage_channels=True)
async def hide(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, view_channel=False)
    await ctx.send(f"#{channel.name} est maintenant cache.")

@bot.command(name="unhide")
@commands.has_permissions(manage_channels=True)
async def unhide(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, view_channel=True)
    await ctx.send(f"#{channel.name} est maintenant visible.")

@bot.command(name="hideall")
@commands.has_permissions(administrator=True)
async def hideall(ctx):
    for ch in ctx.guild.channels:
        try: await ch.set_permissions(ctx.guild.default_role, view_channel=False)
        except: pass
    await ctx.send("Tous les salons caches.")

@bot.command(name="unhideall")
@commands.has_permissions(administrator=True)
async def unhideall(ctx):
    for ch in ctx.guild.channels:
        try: await ch.set_permissions(ctx.guild.default_role, view_channel=True)
        except: pass
    await ctx.send("Tous les salons visibles.")

@bot.command(name="muterole")
@commands.has_permissions(administrator=True)
async def muterole_cmd(ctx):
    role = await get_mute_role(ctx.guild)
    cfg  = get_guild("modconfig.json", ctx.guild.id); cfg["muterole"] = str(role.id); set_guild("modconfig.json", ctx.guild.id, cfg)
    await ctx.send(f"Role muet **{role.name}** configuré.")

@bot.command(name="set_muterole")
@commands.has_permissions(administrator=True)
async def set_muterole(ctx, role: discord.Role):
    cfg = get_guild("modconfig.json", ctx.guild.id); cfg["muterole"] = str(role.id); set_guild("modconfig.json", ctx.guild.id, cfg)
    await ctx.send(f"Role muet défini sur **{role.name}**.")

@bot.command(name="renew")
@commands.has_permissions(manage_channels=True)
async def renew(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    name = channel.name; cat = channel.category; pos = channel.position; ow = channel.overwrites
    await channel.delete()
    new_ch = await ctx.guild.create_text_channel(name, category=cat, overwrites=ow)
    await new_ch.edit(position=pos); await new_ch.send(f"{ctx.author.mention} a recree le salon #{name}.")

@bot.command(name="modlog")
@commands.has_permissions(administrator=True)
async def modlog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("modlog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs de moderation désactivés.")
    ch = channel or ctx.channel; cfg["modlog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs de moderation activés dans {ch.mention}.")

@bot.command(name="messagelog")
@commands.has_permissions(administrator=True)
async def messagelog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("messagelog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs des messages désactivés.")
    ch = channel or ctx.channel; cfg["messagelog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs des messages activés dans {ch.mention}.")

@bot.command(name="voicelog")
@commands.has_permissions(administrator=True)
async def voicelog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("voicelog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs vocaux désactivés.")
    ch = channel or ctx.channel; cfg["voicelog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs vocaux activés dans {ch.mention}.")

@bot.command(name="boostlog")
@commands.has_permissions(administrator=True)
async def boostlog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("boostlog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs de boosts désactivés.")
    ch = channel or ctx.channel; cfg["boostlog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs de boosts activés dans {ch.mention}.")

@bot.command(name="rolelog")
@commands.has_permissions(administrator=True)
async def rolelog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("rolelog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs des roles désactivés.")
    ch = channel or ctx.channel; cfg["rolelog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs des roles activés dans {ch.mention}.")

@bot.command(name="raidlog")
@commands.has_permissions(administrator=True)
async def raidlog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("raidlog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs de raid désactivés.")
    ch = channel or ctx.channel; cfg["raidlog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs de raid activés dans {ch.mention}.")

@bot.command(name="joinlog")
@commands.has_permissions(administrator=True)
async def joinlog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("joinlog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs d'arrivees désactivés.")
    ch = channel or ctx.channel; cfg["joinlog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs d'arrivees activés dans {ch.mention}.")

@bot.command(name="leavelog")
@commands.has_permissions(administrator=True)
async def leavelog(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("logs.json", ctx.guild.id)
    if action.lower() == "off":
        cfg.pop("leavelog", None); set_guild("logs.json", ctx.guild.id, cfg)
        return await ctx.send("Logs de departs désactivés.")
    ch = channel or ctx.channel; cfg["leavelog"] = str(ch.id); set_guild("logs.json", ctx.guild.id, cfg)
    await ctx.send(f"Logs de departs activés dans {ch.mention}.")

@bot.command(name="settings")
@commands.has_permissions(manage_guild=True)
async def settings(ctx):
    cfg  = get_guild("logs.json", ctx.guild.id)
    keys = ["modlog","messagelog","voicelog","rolelog","boostlog","raidlog","joinlog","leavelog"]
    e    = discord.Embed(title="Paramètres des logs", color=get_color(ctx.guild.id))
    for k in keys:
        cid = cfg.get(k); ch = ctx.guild.get_channel(int(cid)) if cid else None
        e.add_field(name=k, value=ch.mention if ch else "Désactivé", inline=True)
    await ctx.send(embed=e)

@bot.command(name="autoconfiglog")
@commands.has_permissions(administrator=True)
async def autoconfiglog(ctx):
    cfg   = get_guild("logs.json", ctx.guild.id)
    names = {"modlog":"modlogs","messagelog":"msglogs","voicelog":"voclogs","rolelog":"rolelogs","boostlog":"boostlogs","raidlog":"raidlogs","joinlog":"joinlogs","leavelog":"leavelogs"}

    msg = await ctx.send("⚙️ Configuration des logs en cours...")

    # 1. Supprimer l'ancienne categorie Logs et ses salons si elle existe
    for cat in ctx.guild.categories:
        if cat.name.lower() in ("logs", "📋 logs", "log"):
            for ch in cat.channels:
                try: await ch.delete(reason="Reconfiguration des logs")
                except: pass
            try: await cat.delete(reason="Reconfiguration des logs")
            except: pass
            break

    # 2. Aussi supprimer les salons logs existants configures
    for log_key in names.keys():
        old_cid = cfg.get(log_key)
        if old_cid:
            old_ch = ctx.guild.get_channel(int(old_cid))
            if old_ch:
                try: await old_ch.delete(reason="Reconfiguration des logs")
                except: pass

    # 3. Permissions : visible uniquement par le bot et les admins
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            read_messages=False
        ),
        ctx.guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_messages=True,
            embed_links=True,
            attach_files=True,
        ),
    }
    # Ajouter les roles admins
    for role in ctx.guild.roles:
        if role.permissions.administrator and role != ctx.guild.default_role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                send_messages=False
            )

    # 4. Creer la nouvelle categorie privee
    cat_overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.guild.me: discord.PermissionOverwrite(view_channel=True),
    }
    for role in ctx.guild.roles:
        if role.permissions.administrator and role != ctx.guild.default_role:
            cat_overwrites[role] = discord.PermissionOverwrite(view_channel=True)

    cat = await ctx.guild.create_category("Logs", overwrites=cat_overwrites)

    # 5. Creer les salons
    for k, n in names.items():
        ch       = await ctx.guild.create_text_channel(n, category=cat, overwrites=overwrites)
        cfg[k]   = str(ch.id)

    set_guild("logs.json", ctx.guild.id, cfg)
    await msg.edit(content=f"✅ Catégorie **Logs** créée avec **{len(names)}** salons privés ! Seuls toi et les administrateurs peuvent les voir.")

@bot.command(name="nolog")
@commands.has_permissions(administrator=True)
async def nolog(ctx, action: str, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    cfg = get_guild("logs.json", ctx.guild.id); nologs = cfg.get("nolog", [])
    if action.lower() == "add":
        if str(channel.id) not in nologs: nologs.append(str(channel.id))
        await ctx.send(f"Logs désactivés dans {channel.mention}.")
    elif action.lower() == "del":
        if str(channel.id) in nologs: nologs.remove(str(channel.id))
        await ctx.send(f"Logs reactives dans {channel.mention}.")
    cfg["nolog"] = nologs; set_guild("logs.json", ctx.guild.id, cfg)

@bot.command(name="snipe")
async def snipe(ctx):
    msg = snipe_cache.get(ctx.channel.id)
    if not msg: return await ctx.send("Aucun message recemment supprimé dans ce salon.")
    e = discord.Embed(description=msg.content or "*vide*", color=0xff4500, timestamp=msg.created_at)
    e.set_author(name=str(msg.author), icon_url=msg.author.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="antispam")
@commands.has_permissions(administrator=True)
async def antispam_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if action.lower() in ("on","off"):
        cfg["antispam"] = (action.lower()=="on"); set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"Antispam {'activé' if action.lower()=='on' else 'désactivé'}.")
    elif "/" in action:
        p = action.split("/"); cfg["antispam_limit"] = int(p[0]); cfg["antispam_window"] = int(p[1])
        set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"Sensibilite antispam : {p[0]} msgs / {p[1]}s.")

@bot.command(name="antilink")
@commands.has_permissions(administrator=True)
async def antilink_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if action.lower() in ("on","off"): cfg["antilink"] = (action.lower()=="on")
    elif action.lower() in ("invite","all"): cfg["antilink_mode"] = action.lower()
    set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antilink mis à jour : `{action}`.")

@bot.command(name="antimassmention")
@commands.has_permissions(administrator=True)
async def antimassmention_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    try:
        cfg["antimassmention_limit"] = int(action); set_guild("antiraid.json", ctx.guild.id, cfg)
        return await ctx.send(f"Limite mention spam : {action} mentions.")
    except ValueError: pass
    cfg["antimassmention"] = (action.lower()=="on"); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antimassmention {'activé' if action.lower()=='on' else 'désactivé'}.")

@bot.command(name="antitoken")
@commands.has_permissions(administrator=True)
async def antitoken_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if action.lower() in ("on","off"):
        cfg["antitoken"] = (action.lower()=="on"); set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"Antitoken {'activé' if action.lower()=='on' else 'désactivé'}.")
    elif action.lower() == "lock":
        for ch in ctx.guild.text_channels:
            try: await ch.set_permissions(ctx.guild.default_role, send_messages=False)
            except: pass
        await ctx.send("Serveur verrouillé manuellement.")
    elif "/" in action:
        p = action.split("/"); cfg["antitoken_limit"] = int(p[0]); cfg["antitoken_window"] = int(p[1])
        set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"Sensibilite antitoken : {p[0]} joins / {p[1]}s.")

@bot.command(name="antieveryone")
@commands.has_permissions(administrator=True)
async def antieveryone_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antieveryone"] = action.lower(); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antieveryone : `{action}`.")

@bot.command(name="antirole")
@commands.has_permissions(administrator=True)
async def antirole_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antirole"] = action.lower(); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antirole : `{action}`.")

@bot.command(name="antiwebhook")
@commands.has_permissions(administrator=True)
async def antiwebhook_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antiwebhook"] = action.lower() in ("on","max"); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antiwebhook {'activé' if cfg['antiwebhook'] else 'désactivé'}.")

@bot.command(name="antiupdate")
@commands.has_permissions(administrator=True)
async def antiupdate_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antiupdate"] = action.lower(); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antiupdate : `{action}`.")

@bot.command(name="antichannel")
@commands.has_permissions(administrator=True)
async def antichannel_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antichannel"] = action.lower(); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antichannel : `{action}`.")

@bot.command(name="antiban")
@commands.has_permissions(administrator=True)
async def antiban_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if action.lower() in ("on","off","max"): cfg["antiban"] = action.lower()
    elif "/" in action:
        p = action.split("/"); cfg["antiban_limit"] = int(p[0]); cfg["antiban_window"] = int(p[1])
    set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antiban mis à jour : `{action}`.")

@bot.command(name="antiunban")
@commands.has_permissions(administrator=True)
async def antiunban_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antiunban"] = action.lower() in ("on","max"); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antiunban {'activé' if cfg['antiunban'] else 'désactivé'}.")

@bot.command(name="antibot")
@commands.has_permissions(administrator=True)
async def antibot_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    cfg["antibot"] = action.lower() in ("on","max"); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antibot {'activé' if cfg['antibot'] else 'désactivé'}.")

@bot.command(name="antideco")
@commands.has_permissions(administrator=True)
async def antideco_cmd(ctx, action: str):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if action.lower() in ("on","off","max"): cfg["antideco"] = action.lower()
    elif "/" in action:
        p = action.split("/"); cfg["antideco_limit"] = int(p[0]); cfg["antideco_window"] = int(p[1])
    set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antideco mis à jour : `{action}`.")

@bot.command(name="badwords")
@commands.has_permissions(administrator=True)
async def badwords_cmd(ctx, action: str, *, word: str = None):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if action.lower() in ("on","off"):
        cfg["badwords"] = (action.lower()=="on"); set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"Badwords {'activé' if action.lower()=='on' else 'désactivé'}.")
    elif action.lower() == "add" and word:
        words = cfg.get("badwords_list",[]); words.append(word.lower()); cfg["badwords_list"] = words
        set_guild("antiraid.json", ctx.guild.id, cfg); await ctx.send(f"`{word}` ajouté aux mots interdits.")
    elif action.lower() == "del" and word:
        words = cfg.get("badwords_list",[])
        if word.lower() in words: words.remove(word.lower())
        cfg["badwords_list"] = words; set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"`{word}` retiré des mots interdits.")
    elif action.lower() == "list":
        words = cfg.get("badwords_list",[])
        e = discord.Embed(title="Mots interdits", description=", ".join(f"`{w}`" for w in words) or "*Aucun*", color=0xff0000)
        await ctx.send(embed=e)
    elif action.lower() in ("clear","reset"):
        cfg["badwords_list"] = []; set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send("Liste des mots interdits vidée.")

@bot.command(name="wl")
async def whitelist(ctx, member: discord.Member = None):
    if ctx.author.id not in OWNER_IDS:
        return await ctx.send("❌ Seuls les owners du bot peuvent utiliser cette commande.")
    cfg = get_guild("antiraid.json", ctx.guild.id); wl = cfg.get("whitelist",[])
    if not member:
        members_wl = [ctx.guild.get_member(int(m)) for m in wl if ctx.guild.get_member(int(m))]
        e = discord.Embed(title="🛡️ Whitelist Antiraid", color=0x00ff00, timestamp=datetime.utcnow())
        e.description = "\n".join(f"- {m.mention} `({m.id})`" for m in members_wl) or "*Vide*"
        e.set_footer(text=f"{len(members_wl)} membre(s) en whitelist")
        return await ctx.send(embed=e)
    if str(member.id) not in wl: wl.append(str(member.id))
    cfg["whitelist"] = wl; set_guild("antiraid.json", ctx.guild.id, cfg)
    e = discord.Embed(title="✅ Whitelist - Membre ajouté", color=0x00ff00, timestamp=datetime.utcnow())
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre", value=f"{member.mention} `({member.id})`")
    await ctx.send(embed=e)

@bot.command(name="unwl")
async def unwhitelist(ctx, member: discord.Member):
    if ctx.author.id not in OWNER_IDS:
        return await ctx.send("❌ Seuls les owners du bot peuvent utiliser cette commande.")
    cfg = get_guild("antiraid.json", ctx.guild.id); wl = cfg.get("whitelist",[])
    if str(member.id) in wl: wl.remove(str(member.id))
    cfg["whitelist"] = wl; set_guild("antiraid.json", ctx.guild.id, cfg)
    e = discord.Embed(title="❌ Whitelist - Membre retiré", color=0xff4500, timestamp=datetime.utcnow())
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre", value=f"{member.mention} `({member.id})`")
    await ctx.send(embed=e)

@bot.command(name="clear_wl")
async def clear_wl(ctx):
    if ctx.author.id not in OWNER_IDS:
        return await ctx.send("❌ Seuls les owners du bot peuvent utiliser cette commande.")
    cfg = get_guild("antiraid.json", ctx.guild.id); cfg["whitelist"] = []; set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send("🗑️ Whitelist antiraid vidée.")

@bot.command(name="secur")
@commands.has_permissions(administrator=True)
async def secur(ctx, action: str = None):
    cfg  = get_guild("antiraid.json", ctx.guild.id)
    keys = ["antispam","antilink","antitoken","antimassmention","badwords","antieveryone","antirole","antiwebhook","antiban","antiunban","antibot","antideco"]
    if not action:
        e = discord.Embed(title="Paramètres Antiraid", color=get_color(ctx.guild.id))
        for k in keys:
            val = cfg.get(k)
            e.add_field(name=k, value="Actif" if val and val not in ("off", False) else "Inactif")
        return await ctx.send(embed=e)
    val = action.lower() in ("on","max")
    for k in keys: cfg[k] = val
    if action.lower() == "max": cfg.update({"antispam_limit":3,"antispam_window":3,"antimassmention_limit":3})
    set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Protection antiraid `{action}` appliquée a tous les modules.")

@bot.command(name="creation_limit")
@commands.has_permissions(administrator=True)
async def creation_limit(ctx, seconds: int):
    cfg = get_guild("antiraid.json", ctx.guild.id); cfg["creation_limit"] = seconds; set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Comptes de moins de **{seconds}s** seront expulses a l'arrivée.")

@bot.command(name="clear_webhooks")
@commands.has_permissions(manage_webhooks=True)
async def clear_webhooks(ctx):
    webhooks = await ctx.guild.webhooks(); count = 0
    for wh in webhooks:
        try: await wh.delete(); count += 1
        except: pass
    await ctx.send(f"**{count}** webhook(s) supprime(s).")

@bot.command(name="raidping")
@commands.has_permissions(administrator=True)
async def raidping(ctx, role: discord.Role):
    cfg = get_guild("antiraid.json", ctx.guild.id); cfg["raidping"] = str(role.id); set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Role mentionné en cas de raid : **{role.name}**.")

@bot.command(name="punition")
@commands.has_permissions(administrator=True)
async def punition(ctx, antiraid_type: str, punishment: str):
    if punishment.lower() not in ("warn","muté","kick","ban","derank"):
        return await ctx.send("Punition invalide. Choix : `warn`, `mute`, `kick`, `ban`, `derank`.")
    cfg = get_guild("antiraid.json", ctx.guild.id)
    if antiraid_type.lower() == "all":
        for k in ["antispam","antilink","antimassmention","antieveryone"]:
            cfg[f"punish_{k}"] = punishment.lower()
    else:
        cfg[f"punish_{antiraid_type.lower()}"] = punishment.lower()
    set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Punition pour `{antiraid_type}` : **{punishment}**.")

@bot.command(name="blrank")
@commands.has_permissions(administrator=True)
async def blrank(ctx, action: str = None, member: discord.Member = None):
    cfg = get_guild("antiraid.json", ctx.guild.id); blr = cfg.get("blrank",[])
    if not action:
        members_bl = [ctx.guild.get_member(int(m)) for m in blr if ctx.guild.get_member(int(m))]
        e = discord.Embed(title="Blacklist Rank", description="\n".join(f"- {m}" for m in members_bl) or "*Vide*", color=0xff0000)
        return await ctx.send(embed=e)
    if action.lower() in ("on","off","max","danger","all"):
        cfg["blrank_active"] = action.lower(); set_guild("antiraid.json", ctx.guild.id, cfg)
        return await ctx.send(f"Blrank : `{action}`.")
    if action.lower() == "add" and member:
        if str(member.id) not in blr: blr.append(str(member.id))
        cfg["blrank"] = blr; set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"**{member}** ajouté a la blacklist rank.")
    elif action.lower() == "del" and member:
        if str(member.id) in blr: blr.remove(str(member.id))
        cfg["blrank"] = blr; set_guild("antiraid.json", ctx.guild.id, cfg)
        await ctx.send(f"**{member}** retiré de la blacklist rank.")

@bot.command(name="spam")
@commands.has_permissions(administrator=True)
async def spam_channel(ctx, action: str, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    cfg = get_guild("antiraid.json", ctx.guild.id); nospam = cfg.get("nospam_channels",{})
    if action.lower() == "reset": nospam.pop(str(channel.id), None)
    else: nospam[str(channel.id)] = action.lower()
    cfg["nospam_channels"] = nospam; set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antispam `{action}` dans {channel.mention}.")

@bot.command(name="link")
@commands.has_permissions(administrator=True)
async def link_channel(ctx, action: str, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    cfg = get_guild("antiraid.json", ctx.guild.id); nolink = cfg.get("nolink_channels",{})
    if action.lower() == "reset": nolink.pop(str(channel.id), None)
    else: nolink[str(channel.id)] = action.lower()
    cfg["nolink_channels"] = nolink; set_guild("antiraid.json", ctx.guild.id, cfg)
    await ctx.send(f"Antilink `{action}` dans {channel.mention}.")

@bot.command(name="giveaway")
@commands.has_permissions(manage_guild=True)
async def giveaway(ctx):
    def check(m): return m.author == ctx.author and m.channel == ctx.channel
    await ctx.send("**Giveaway** - Quel est le titre ?")
    try:
        title = (await bot.wait_for("message", check=check, timeout=60)).content
        await ctx.send("Durée ? (ex: `10m`, `2h`, `1d`)")
        dur_str = (await bot.wait_for("message", check=check, timeout=60)).content
        delta   = parse_dur(dur_str)
        if not delta: return await ctx.send("Durée invalide.")
        await ctx.send("Nombre de gagnants ?")
        winners_count = int((await bot.wait_for("message", check=check, timeout=60)).content)
    except (asyncio.TimeoutError, ValueError): return await ctx.send("Temps écoulé ou valeur invalide.")
    end_time = datetime.utcnow() + delta
    e = discord.Embed(title=title, color=0xff73fa)
    e.description = f"Reagissez avec pour participer !\n\n**Gagnants :** {winners_count}\n**Fin :** <t:{int(end_time.timestamp())}:R>"
    gaw_msg = await ctx.send(embed=e)
    await gaw_msg.add_reaction("🎉")
    data = get_guild("giveaways.json", ctx.guild.id)
    data[str(gaw_msg.id)] = {"channel": str(ctx.channel.id), "title": title, "winners": winners_count, "activé": True}
    set_guild("giveaways.json", ctx.guild.id, data)
    await asyncio.sleep(delta.total_seconds())
    data = get_guild("giveaways.json", ctx.guild.id); gaw = data.get(str(gaw_msg.id))
    if gaw and gaw.get("activé"):
        try:
            msg_ref      = await ctx.channel.fetch_message(gaw_msg.id)
            réaction     = discord.utils.get(msg_ref.réactions, emoji="🎉")
            participants = [u async for u in réaction.users() if not u.bot] if réaction else []
            if not participants: await ctx.send(f"Giveaway **{title}** terminé, personne n'a participe.")
            else:
                winners = random.sample(participants, min(winners_count, len(participants)))
                await ctx.send(f"Felicitations {', '.join(w.mention for w in winners)} ! Vous avez gagne **{title}** !")
        except: pass
        data[str(gaw_msg.id)]["activé"] = False; set_guild("giveaways.json", ctx.guild.id, data)

@bot.command(name="end_giveaway")
@commands.has_permissions(manage_guild=True)
async def end_giveaway(ctx, message_id: int):
    data = get_guild("giveaways.json", ctx.guild.id); gaw = data.get(str(message_id))
    if not gaw: return await ctx.send("Giveaway introuvable.")
    ch = ctx.guild.get_channel(int(gaw["channel"]))
    if not ch: return await ctx.send("Salon introuvable.")
    try:
        msg      = await ch.fetch_message(message_id)
        réaction = discord.utils.get(msg.réactions, emoji="🎉")
        participants = [u async for u in réaction.users() if not u.bot] if réaction else []
        if not participants: await ch.send(f"Giveaway **{gaw['title']}** terminé, personne n'a participe.")
        else:
            winners = random.sample(participants, min(gaw["winners"], len(participants)))
            await ch.send(f"Felicitations {', '.join(w.mention for w in winners)} ! Vous avez gagne **{gaw['title']}** !")
    except Exception as ex: await ctx.send(f"Erreur : {ex}")
    data[str(message_id)]["activé"] = False; set_guild("giveaways.json", ctx.guild.id, data)
    await ctx.send("Giveaway terminé.")

@bot.command(name="reroll")
@commands.has_permissions(manage_guild=True)
async def reroll(ctx):
    data = get_guild("giveaways.json", ctx.guild.id)
    last = next(((gid, gaw) for gid, gaw in reversed(list(data.items())) if gaw.get("channel") == str(ctx.channel.id)), None)
    if not last: return await ctx.send("Aucun giveaway recent dans ce salon.")
    gid, gaw = last
    try:
        msg          = await ctx.channel.fetch_message(int(gid))
        réaction     = discord.utils.get(msg.réactions, emoji="🎉")
        participants = [u async for u in réaction.users() if not u.bot]
        if not participants: return await ctx.send("Aucun participant.")
        await ctx.send(f"Nouveau tirage ! Gagnant : {random.choice(participants).mention} !")
    except Exception as ex: await ctx.send(f"Erreur : {ex}")


@bot.command(name="embed")
@commands.has_permissions(manage_messages=True)
async def embed_builder(ctx):
    """Panneau de création d'embed 100% configurable."""
    data = {
        "title": "", "description": "", "color": "000000",
        "footer": "", "author": "", "image": "", "thumbnail": "",
        "fields": [], "channel": None
    }
    e    = _embed_preview(data, ctx.guild)
    view = EmbedBuilderView(ctx, data)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

def _embed_preview(data, guild):
    try: color = int(data.get("color","000000").replace("#","").replace("0x",""), 16)
    except: color = 0x000000
    e = discord.Embed(
        title=data.get("title") or None,
        description=data.get("description") or None,
        color=color
    )
    if data.get("footer"):   e.set_footer(text=data["footer"])
    if data.get("author"):   e.set_author(name=data["author"])
    if data.get("image"):
        try: e.set_image(url=data["image"])
        except: pass
    if data.get("thumbnail"):
        try: e.set_thumbnail(url=data["thumbnail"])
        except: pass
    for field in data.get("fields", []):
        e.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
    if not any([data.get("title"), data.get("description"), data.get("fields")]):
        e.description = "*Configure ton embed avec les boutons ci-dessous*"
    return e

class EmbedBuilderView(discord.ui.View):
    def __init__(self, ctx, data):
        super().__init__(timeout=300)
        self.ctx     = ctx
        self.data    = data
        self.message = None

    async def refresh(self, interaction):
        e = _embed_preview(self.data, interaction.guild)
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="📝 Titre", style=discord.ButtonStyle.primary, row=0)
    async def set_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("Titre", "title", self, max_length=256))

    @discord.ui.button(label="📄 Description", style=discord.ButtonStyle.primary, row=0)
    async def set_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("Description", "description", self, paragraph=True))

    @discord.ui.button(label="🎨 Couleur", style=discord.ButtonStyle.primary, row=0)
    async def set_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("Couleur hex (ex: ff0000)", "color", self, max_length=7))

    @discord.ui.button(label="📋 Footer", style=discord.ButtonStyle.secondary, row=0)
    async def set_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("Footer", "footer", self, max_length=200))

    @discord.ui.button(label="👤 Auteur", style=discord.ButtonStyle.secondary, row=0)
    async def set_author(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("Auteur", "author", self, max_length=100))

    @discord.ui.button(label="🖼️ Image (URL)", style=discord.ButtonStyle.secondary, row=1)
    async def set_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("URL de l'image", "image", self))

    @discord.ui.button(label="🖼️ Thumbnail (URL)", style=discord.ButtonStyle.secondary, row=1)
    async def set_thumbnail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFieldModal("URL du thumbnail", "thumbnail", self))

    @discord.ui.button(label="➕ Ajouter un champ", style=discord.ButtonStyle.success, row=1)
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedAddFieldModal(self))

    @discord.ui.button(label="➖ Supprimer un champ", style=discord.ButtonStyle.danger, row=1)
    async def del_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        fields = self.data.get("fields", [])
        if not fields:
            return await interaction.response.send_message("Aucun champ à supprimer.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Supprimer un champ",
            options=[discord.SelectOption(label=f["name"][:25], value=str(i)) for i, f in enumerate(fields[:25])]
        )
        parent = self
        async def del_cb(inter):
            idx = int(inter.data["values"][0])
            parent.data["fields"].pop(idx)
            e = _embed_preview(parent.data, inter.guild)
            await inter.response.edit_message(embed=e, view=parent)
        sel.callback = del_cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="📤 Envoyer", style=discord.ButtonStyle.success, row=2)
    async def send_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        chans = interaction.guild.text_channels[:25]
        sel   = discord.ui.Select(
            placeholder="Dans quel salon envoyer ?",
            options=[discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chans]
        )
        parent = self
        async def send_cb(inter):
            ch = inter.guild.get_channel(int(inter.data["values"][0]))
            if not ch:
                return await inter.response.send_message("Salon introuvable.", ephemeral=True)
            e = _embed_preview(parent.data, inter.guild)
            await ch.send(embed=e)
            await inter.response.send_message(f"✅ Embed envoyé dans {ch.mention} !", ephemeral=True)
        sel.callback = send_cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="🗑️ Reset", style=discord.ButtonStyle.danger, row=2)
    async def reset_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.data = {"title":"","description":"","color":"000000","footer":"","author":"","image":"","thumbnail":"","fields":[],"channel":None}
        await self.refresh(interaction)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class EmbedFieldModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Valeur", max_length=1024)
    def __init__(self, title, key, parent, paragraph=False, max_length=1024):
        super().__init__(title=title[:45])
        self.key    = key
        self.parent = parent
        self.value.style      = discord.TextStyle.paragraph if paragraph else discord.TextStyle.short
        self.value.max_length = max_length
        self.value.required   = False
    async def on_submit(self, interaction: discord.Interaction):
        self.parent.data[self.key] = str(self.value).strip()
        await self.parent.refresh(interaction)

class EmbedAddFieldModal(discord.ui.Modal, title="Ajouter un champ"):
    name_   = discord.ui.TextInput(label="Nom du champ",   max_length=256)
    value_  = discord.ui.TextInput(label="Valeur du champ", style=discord.TextStyle.paragraph, max_length=1024)
    inline_ = discord.ui.TextInput(label="Inline ? (oui/non)", max_length=3, default="non")
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        self.parent.data.setdefault("fields", []).append({
            "name":   str(self.name_),
            "value":  str(self.value_),
            "inline": str(self.inline_).lower() in ("oui","yes","true","1")
        })
        await self.parent.refresh(interaction)

def get_ticket_cfg(gid):
    cfg = get_guild("tickets.json", gid)
    cfg.setdefault("category",        None)
    cfg.setdefault("panel_channel",   None)
    cfg.setdefault("log_channel",     None)
    cfg.setdefault("staff_roles",     [])
    cfg.setdefault("required_roles",  [])
    cfg.setdefault("banned_roles",    [])
    cfg.setdefault("options",         [])
    cfg.setdefault("panel_type",      "selector")
    cfg.setdefault("claim_enabled",   False)
    cfg.setdefault("autoclaim",       False)
    cfg.setdefault("auto_delete",     False)
    cfg.setdefault("max_per_user",    1)
    cfg.setdefault("close_on_leave",  False)
    cfg.setdefault("btn_claim",       False)
    cfg.setdefault("btn_close",       False)
    cfg.setdefault("btn_add",         False)
    cfg.setdefault("transcript_mp",   False)
    cfg.setdefault("claim_lock",      False)
    cfg.setdefault("claim_hide",      False)
    cfg.setdefault("auto_msg",        "")
    cfg.setdefault("close_msg",       "")
    cfg.setdefault("panel_title",     "")
    cfg.setdefault("panel_desc",      "")
    cfg.setdefault("panel_color",     "0x000000")
    cfg.setdefault("ticket_title",    "")
    cfg.setdefault("ticket_desc",     "")
    cfg.setdefault("ticket_color",    "0x000000")
    cfg.setdefault("name_format",     "ticket-{username}")
    cfg.setdefault("mention_staff",   False)
    cfg.setdefault("dm_on_open",      False)
    cfg.setdefault("dm_on_close",     False)
    cfg.setdefault("numbering",       False)
    cfg.setdefault("ticket_count",    0)
    cfg.setdefault("notify_open",     False)
    cfg.setdefault("notify_close",    False)
    return cfg

def save_ticket_cfg(gid, cfg):
    set_guild("tickets.json", gid, cfg)

async def send_transcript(channel, member):
    import io
    messages = []
    async for msg in channel.history(limit=500, oldest_first=True):
        ts = msg.created_at.strftime("%d/%m/%Y %H:%M")
        line = f"[{ts}] {msg.author}: {msg.content}"
        if msg.attachments:
            line += " [PJ: " + ", ".join(a.filename for a in msg.attachments) + "]"
        messages.append(line)
    if not messages:
        return
    try:
        content  = "\n".join(messages)
        e        = discord.Embed(title=f"📄 Transcript - #{channel.name}", color=get_color(channel.guild.id), timestamp=datetime.utcnow())
        e.add_field(name="Salon",    value=channel.name)
        e.add_field(name="Messages", value=str(len(messages)))
        file = discord.File(io.StringIO(content), filename=f"transcript-{channel.name}.txt")
        await member.send(embed=e, file=file)
    except:
        pass

async def do_claim(channel, claimer, guild, cfg):
    data = get_guild("tickets.json", guild.id)
    data.setdefault("claimed", {})[str(channel.id)] = str(claimer.id)
    set_guild("tickets.json", guild.id, data)
    staff_roles = [guild.get_role(int(r)) for r in cfg.get("staff_roles", []) if guild.get_role(int(r))]
    if cfg.get("claim_lock"):
        for sr in staff_roles:
            if sr:
                try: await channel.set_permissions(sr, send_messages=False)
                except: pass
        try: await channel.set_permissions(claimer, send_messages=True, view_channel=True)
        except: pass
    if cfg.get("claim_hide"):
        for sr in staff_roles:
            if sr:
                try: await channel.set_permissions(sr, view_channel=False)
                except: pass
        try: await channel.set_permissions(claimer, view_channel=True, send_messages=True)
        except: pass

def format_ticket_name(fmt, member, count):
    name = fmt.replace("{username}", member.name.lower()[:15])
    name = name.replace("{id}", str(member.id))
    name = name.replace("{count}", str(count).zfill(4))
    name = name.replace("{discriminator}", member.discriminator)
    return name[:100]

async def log_ticket(guild, action, member, channel, cfg, reason=""):
    cid = cfg.get("log_channel")
    if not cid: return
    ch = guild.get_channel(int(cid))
    if not ch: return
    colors = {"open": 0x00ff00, "close": 0xff4500, "claim": 0x00bfff}
    icons  = {"open": "📥", "close": "🔐", "claim": "🔒"}
    e = discord.Embed(title=f"{icons.get(action,'📋')} Ticket {action}", color=colors.get(action, 0x888888), timestamp=datetime.utcnow())
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Membre",  value=f"{member.mention} `({member.id})`", inline=True)
    e.add_field(name="📌 Salon",   value=channel.mention if channel else "Supprimé", inline=True)
    if reason: e.add_field(name="📋 Raison", value=reason, inline=False)
    e.set_footer(text=f"ID : {member.id}")
    try: await ch.send(embed=e)
    except: pass

async def open_ticket(guild, member, option):
    cfg = get_ticket_cfg(guild.id)

    # Vérifications
    req = cfg.get("required_roles", [])
    if req:
        member_role_ids = [str(r.id) for r in member.roles]
        if not any(r in member_role_ids for r in req):
            return None, "Tu n'as pas le role requis pour ouvrir un ticket."
    banned = cfg.get("banned_roles", [])
    if banned:
        member_role_ids = [str(r.id) for r in member.roles]
        if any(r in member_role_ids for r in banned):
            return None, "Tu n'as pas le droit d'ouvrir un ticket."
    existing = [c for c in guild.text_channels if c.topic and f"TICKET_OWNER:{member.id}" in c.topic]
    if len(existing) >= cfg.get("max_per_user", 1):
        return None, f"Tu as déjà **{cfg['max_per_user']}** ticket(s) ouvert(s) : {existing[0].mention}"

    # Numérotation
    count = cfg.get("ticket_count", 0) + 1
    cfg["ticket_count"] = count
    save_ticket_cfg(guild.id, cfg)

    category    = guild.get_channel(int(cfg["category"])) if cfg.get("category") else None
    staff_roles = [guild.get_role(int(r)) for r in cfg.get("staff_roles", []) if guild.get_role(int(r))]
    opt_emoji   = option.get("emoji", "🎫")
    opt_label   = option.get("label", "Support")

    # Permissions
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member:             discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
        guild.me:           discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
    }
    for sr in staff_roles:
        overwrites[sr] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)

    # Nom du salon
    fmt  = cfg.get("name_format", "ticket-{username}")
    if cfg.get("numbering"):
        fmt = fmt.replace("{username}", f"{str(count).zfill(4)}-{member.name.lower()[:10]}")
    name = format_ticket_name(fmt, member, count)

    ch = await guild.create_text_channel(
        name, category=category, overwrites=overwrites,
        topic=f"TICKET_OWNER:{member.id} | TYPE:{opt_label} | COUNT:{count}"
    )

    # Embed du ticket
    try:    color = int(cfg.get("ticket_color","0x00bfff").replace("0x",""), 16)
    except: color = 0x00bfff

    title = cfg.get("ticket_title", "{emoji} Ticket {option}").replace("{emoji}", opt_emoji).replace("{option}", opt_label)
    desc  = cfg.get("ticket_desc", "Bonjour {member} !\nDecris ton probleme.").replace("{member}", member.mention).replace("{option}", opt_label).replace("{count}", str(count))

    e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.utcnow())
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name="👤 Ouvert par", value=member.mention, inline=True)
    e.add_field(name="📂 Catégorie",  value=opt_label, inline=True)
    if cfg.get("numbering"):
        e.add_field(name="🔢 Numéro", value=f"#{count}", inline=True)
    e.set_footer(text="Pocoyo - Système de tickets")

    view = TicketControlView(guild.id)
    await ch.send(embed=e, view=view)

    # Mention staff
    if cfg.get("mention_staff") and staff_roles:
        mentions = " ".join(r.mention for r in staff_roles)
        await ch.send(mentions, delete_after=5)

    # Message auto
    if cfg.get("auto_msg"):
        await ch.send(cfg["auto_msg"])

    # DM a l'ouverture
    if cfg.get("dm_on_open"):
        try:
            dm_e = discord.Embed(title="🎫 Ticket ouvert", description=f"Ton ticket **{opt_label}** a ete ouvert sur **{guild.name}**.\nSalon : {ch.mention}", color=color)
            await member.send(embed=dm_e)
        except: pass

    # Autoclaim
    if cfg.get("autoclaim") and staff_roles:
        sr_members = [m for m in staff_roles[0].members if not m.bot]
        if sr_members:
            await do_claim(ch, sr_members[0], guild, cfg)

    # Log
    await log_ticket(guild, "open", member, ch, cfg)

    return ch, None

class TicketControlView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        cfg = get_ticket_cfg(guild_id)
        if not cfg.get("btn_claim"): self.remove_item(self.claim_btn)
        if not cfg.get("btn_close"): self.remove_item(self.close_btn)
        if not cfg.get("btn_add"):   self.remove_item(self.add_btn)

    @discord.ui.button(label="Claim", emoji="🔒", style=discord.ButtonStyle.primary, custom_id="tcv_claim")
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_ticket_cfg(interaction.guild.id)
        if not cfg.get("claim_enabled"):
            return await interaction.response.send_message("Le claim est désactivé.", ephemeral=True)
        staff_roles = [interaction.guild.get_role(int(r)) for r in cfg.get("staff_roles", [])]
        is_staff    = any(r in interaction.user.roles for r in staff_roles if r)
        if not is_staff and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Tu dois etre staff pour claim.", ephemeral=True)
        await do_claim(interaction.channel, interaction.user, interaction.guild, cfg)
        topic    = interaction.channel.topic or ""
        owner_id = None
        if "TICKET_OWNER:" in topic:
            try: owner_id = int(topic.split("TICKET_OWNER:")[1].split(" ")[0])
            except: pass
        owner = interaction.guild.get_member(owner_id) if owner_id else None
        e = discord.Embed(title="🔒 Ticket claim", description=f"Pris en chargé par {interaction.user.mention}.", color=0x00bfff, timestamp=datetime.utcnow())
        await interaction.response.send_message(embed=e)
        if owner: await log_ticket(interaction.guild, "claim", owner, interaction.channel, cfg)

    @discord.ui.button(label="Fermer", emoji="🔐", style=discord.ButtonStyle.danger, custom_id="tcv_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg      = get_ticket_cfg(interaction.guild.id)
        topic    = interaction.channel.topic or ""
        owner_id = None
        if "TICKET_OWNER:" in topic:
            try: owner_id = int(topic.split("TICKET_OWNER:")[1].split(" ")[0])
            except: pass
        staff_roles = [interaction.guild.get_role(int(r)) for r in cfg.get("staff_roles", [])]
        is_staff    = any(r in interaction.user.roles for r in staff_roles if r)
        if not is_staff and not interaction.user.guild_permissions.administrator and interaction.user.id != owner_id:
            return await interaction.response.send_message("Tu ne peux pas fermer ce ticket.", ephemeral=True)
        view = TicketCloseConfirmView(interaction.guild.id, owner_id, interaction.user)
        e    = discord.Embed(title="🔐 Fermer le ticket ?", description="Confirme la fermeture.", color=0xff4500)
        await interaction.response.send_message(embed=e, view=view, ephemeral=True)

    @discord.ui.button(label="Ajouter", emoji="➕", style=discord.ButtonStyle.secondary, custom_id="tcv_add")
    async def add_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg         = get_ticket_cfg(interaction.guild.id)
        staff_roles = [interaction.guild.get_role(int(r)) for r in cfg.get("staff_roles", [])]
        is_staff    = any(r in interaction.user.roles for r in staff_roles if r)
        if not is_staff and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Staff seulement.", ephemeral=True)
        await interaction.response.send_modal(TicketAddMemberModal(interaction.channel))

class TicketAddMemberModal(discord.ui.Modal, title="Ajouter un membre"):
    member_id = discord.ui.TextInput(label="ID ou nom du membre", placeholder="123456789 ou NomMembre#0000")
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
    async def on_submit(self, interaction: discord.Interaction):
        try:
            mid    = int(str(self.member_id))
            member = interaction.guild.get_member(mid)
        except:
            member = discord.utils.find(lambda m: str(m) == str(self.member_id), interaction.guild.members)
        if not member:
            return await interaction.response.send_message("Membre introuvable.", ephemeral=True)
        await self.channel.set_permissions(member, view_channel=True, send_messages=True)
        await interaction.response.send_message(f"{member.mention} ajouté au ticket.", ephemeral=False)

class TicketCloseConfirmView(discord.ui.View):
    def __init__(self, guild_id, owner_id, closer):
        super().__init__(timeout=30)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.closer   = closer

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_ticket_cfg(self.guild_id)
        await interaction.response.defer()
        close_msg = cfg.get("close_msg") or "Suppression dans 5 secondes..."
        e = discord.Embed(title="🔐 Ticket fermé", description=f"{close_msg}\n\nFerme par {self.closer.mention}.", color=0xff4500, timestamp=datetime.utcnow())
        await interaction.channel.send(embed=e)
        owner = interaction.guild.get_member(self.owner_id) if self.owner_id else None
        if cfg.get("transcript_mp") and owner:
            await send_transcript(interaction.channel, owner)
        if owner:
            await log_ticket(interaction.guild, "close", owner, interaction.channel, cfg)
        await asyncio.sleep(5)
        if cfg.get("auto_delete"):
            try: await interaction.channel.delete()
            except: pass

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Annule.", ephemeral=True)
        self.stop()

class TicketSelectView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        cfg     = get_ticket_cfg(guild_id)
        options = cfg.get("options", [{"label":"Support","emoji":"🔧"},{"label":"Purchase","emoji":"🛒"}])
        sel     = discord.ui.Select(
            placeholder="📂 Choisis le type de ticket...",
            options=[discord.SelectOption(label=o["label"], emoji=o.get("emoji","🎫"), description=o.get("description","")[:100], value=o["label"]) for o in options[:25]],
            custom_id="tpanel_select"
        )
        sel.callback = self.cb
        self.add_item(sel)

    async def cb(self, interaction: discord.Interaction):
        cfg  = get_ticket_cfg(interaction.guild.id)
        opts = cfg.get("options", [])
        opt  = next((o for o in opts if o["label"] == interaction.data["values"][0]), {"label":"Support","emoji":"🎫"})
        ch, err = await open_ticket(interaction.guild, interaction.user, opt)
        if err: return await interaction.response.send_message(err, ephemeral=True)
        await interaction.response.send_message(f"✅ Ticket ouvert : {ch.mention}", ephemeral=True)

class TicketButtonView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        cfg     = get_ticket_cfg(guild_id)
        options = cfg.get("options", [{"label":"Support","emoji":"🔧"},{"label":"Purchase","emoji":"🛒"}])
        for opt in options[:5]:
            btn = discord.ui.Button(
                label=opt["label"], emoji=opt.get("emoji","🎫"),
                style=discord.ButtonStyle.primary, custom_id=f"tpanel_btn_{opt['label']}"
            )
            async def make_cb(option):
                async def cb(interaction: discord.Interaction):
                    ch, err = await open_ticket(interaction.guild, interaction.user, option)
                    if err: return await interaction.response.send_message(err, ephemeral=True)
                    await interaction.response.send_message(f"✅ Ticket ouvert : {ch.mention}", ephemeral=True)
                return cb
            btn.callback = make_cb(opt)
            self.add_item(btn)

def ticket_settings_embed(guild, cfg):
    staff  = [guild.get_role(int(r)) for r in cfg.get("staff_roles",[]) if guild.get_role(int(r))]
    req    = [guild.get_role(int(r)) for r in cfg.get("required_roles",[]) if guild.get_role(int(r))]
    banned = [guild.get_role(int(r)) for r in cfg.get("banned_roles",[]) if guild.get_role(int(r))]
    cat    = guild.get_channel(int(cfg["category"])) if cfg.get("category") else None
    log_ch = guild.get_channel(int(cfg["log_channel"])) if cfg.get("log_channel") else None
    opts   = cfg.get("options", [])

    e = discord.Embed(title="🎫 Configuration des tickets", color=0x00bfff, timestamp=datetime.utcnow())
    e.add_field(name="📁 Catégorie",         value=cat.mention if cat else "*Non configure*", inline=True)
    e.add_field(name="📋 Logs",              value=log_ch.mention if log_ch else "*Non configure*", inline=True)
    e.add_field(name="👥 Staff",             value=" ".join(r.mention for r in staff) if staff else "*Non configure*", inline=True)
    e.add_field(name="📝 Format nom salon",  value=f"`{cfg.get('name_format','ticket-{username}')}`", inline=True)
    e.add_field(name="🔢 Numérotation",      value="✅" if cfg.get("numbering") else "❌", inline=True)
    e.add_field(name="👤 Max/personne",      value=str(cfg.get("max_per_user",1)), inline=True)
    e.add_field(name="🔒 Claim",             value="✅" if cfg.get("claim_enabled") else "❌", inline=True)
    e.add_field(name="📌 Autoclaim",         value="✅" if cfg.get("autoclaim") else "❌", inline=True)
    e.add_field(name="🔑 Claim lock",        value="✅" if cfg.get("claim_lock") else "❌", inline=True)
    e.add_field(name="👁️ Claim caché",       value="✅" if cfg.get("claim_hide") else "❌", inline=True)
    e.add_field(name="🗑️ Suppression auto",  value="✅" if cfg.get("auto_delete") else "❌", inline=True)
    e.add_field(name="🚪 Fermer si quitté",  value="✅" if cfg.get("close_on_leave") else "❌", inline=True)
    e.add_field(name="📢 Mention staff",      value="✅" if cfg.get("mention_staff") else "❌", inline=True)
    e.add_field(name="📩 DM ouverture",       value="✅" if cfg.get("dm_on_open") else "❌", inline=True)
    e.add_field(name="📄 Transcript MP",      value="✅" if cfg.get("transcript_mp") else "❌", inline=True)
    e.add_field(name="🔘 Btn claim",          value="✅" if cfg.get("btn_claim") else "❌", inline=True)
    e.add_field(name="🔘 Btn fermer",         value="✅" if cfg.get("btn_close") else "❌", inline=True)
    e.add_field(name="🔘 Btn ajouter",        value="✅" if cfg.get("btn_add") else "❌", inline=True)
    e.add_field(name="✅ Roles requis",        value=" ".join(r.mention for r in req) if req else "Aucun", inline=True)
    e.add_field(name="❌ Roles interdits",     value=" ".join(r.mention for r in banned) if banned else "Aucun", inline=True)
    opts_str = "\n".join(f"{o.get('emoji','🎫')} **{o['label']}** — {o.get('description','')}" for o in opts) or "Aucune"
    e.add_field(name=f"📂 Options ({len(opts)})", value=opts_str[:500], inline=False)
    e.set_footer(text=f"Tickets ouverts : #{cfg.get('ticket_count',0)} | Utilisez le menu pour tout configurer")
    return e

class ModalAutoMsg(discord.ui.Modal, title="Message automatique dans le ticket"):
    msg = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Laissez vidé pour désactiver. Variables: {member} {option}", required=False, max_length=1000)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_ticket_cfg(self.guild_id); cfg["auto_msg"] = str(self.msg)
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class ModalCloseMsg(discord.ui.Modal, title="Message de fermeture"):
    msg = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Message affiché avant la fermeture du ticket", required=False, max_length=500)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_ticket_cfg(self.guild_id); cfg["close_msg"] = str(self.msg)
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class ModalMaxTickets(discord.ui.Modal, title="Max tickets par personne"):
    nombre = discord.ui.TextInput(label="Nombre maximum", placeholder="1", max_length=2)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_ticket_cfg(self.guild_id)
        try: cfg["max_per_user"] = max(1, int(str(self.nombre)))
        except: pass
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class ModalNameFormat(discord.ui.Modal, title="Format du nom de salon"):
    fmt = discord.ui.TextInput(label="Format", placeholder="ticket-{username} | ticket-{count} | ticket-{id}", max_length=50)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_ticket_cfg(self.guild_id); cfg["name_format"] = str(self.fmt)
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class ModalPanelEmbed(discord.ui.Modal, title="Personnaliser le panel"):
    title_  = discord.ui.TextInput(label="Titre", placeholder="🎫 Ouvrir un ticket", max_length=100)
    desc_   = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Selectionnez un type...", max_length=500)
    color_  = discord.ui.TextInput(label="Couleur hex (ex: 00bfff)", placeholder="00bfff", max_length=6)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_ticket_cfg(self.guild_id)
        cfg["panel_title"] = str(self.title_)
        cfg["panel_desc"]  = str(self.desc_)
        try: cfg["panel_color"] = "0x" + str(self.color_).replace("#","").replace("0x","")
        except: pass
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class ModalTicketEmbed(discord.ui.Modal, title="Personnaliser l'embed du ticket"):
    title_ = discord.ui.TextInput(label="Titre", placeholder="{emoji} Ticket {option}", max_length=100)
    desc_  = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Bonjour {member} ! Variables: {member} {option} {count}", max_length=500)
    color_ = discord.ui.TextInput(label="Couleur hex", placeholder="00bfff", max_length=6)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_ticket_cfg(self.guild_id)
        cfg["ticket_title"] = str(self.title_)
        cfg["ticket_desc"]  = str(self.desc_)
        try: cfg["ticket_color"] = "0x" + str(self.color_).replace("#","").replace("0x","")
        except: pass
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class ModalAddOption(discord.ui.Modal, title="Ajouter une option"):
    label = discord.ui.TextInput(label="Nom", placeholder="Support", max_length=30)
    emoji = discord.ui.TextInput(label="Emoji", placeholder="🔧", max_length=10, required=False)
    desc  = discord.ui.TextInput(label="Description", placeholder="Besoin d'aide", max_length=100, required=False)
    def __init__(self, guild_id, parent):
        super().__init__()
        self.guild_id = guild_id; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg  = get_ticket_cfg(self.guild_id)
        opts = cfg.get("options", [])
        opts.append({"label": str(self.label), "emoji": str(self.emoji) or "🎫", "description": str(self.desc)})
        cfg["options"] = opts; save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self.parent)

class TicketSettingsView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=300)
        self.guild    = guild
        self.guild_id = guild.id
        self.message  = None
        self._build()

    def _build(self):
        for item in self.children[:]:
            self.remove_item(item)

        # Menu 1 : Salons & Roles
        s1 = discord.ui.Select(
            placeholder="📁 Salons & Roles",
            options=[
                discord.SelectOption(label="Catégorie des tickets",    emoji="📁", value="category"),
                discord.SelectOption(label="Salon de logs",             emoji="📋", value="log_channel"),
                discord.SelectOption(label="Role(s) staff",             emoji="👥", value="staff_roles"),
                discord.SelectOption(label="Roles requis",              emoji="✅", value="required_roles"),
                discord.SelectOption(label="Roles interdits",           emoji="❌", value="banned_roles"),
            ], custom_id="ts1"
        )
        s1.callback = self.cb_channels_roles
        self.add_item(s1)

        # Menu 2 : Comportement
        s2 = discord.ui.Select(
            placeholder="⚙️ Comportement",
            options=[
                discord.SelectOption(label="Max tickets par personne",  emoji="👤", value="max_tickets"),
                discord.SelectOption(label="Format nom du salon",        emoji="📝", value="name_format"),
                discord.SelectOption(label="Numérotation des tickets",   emoji="🔢", value="toggle_numbering"),
                discord.SelectOption(label="Suppression auto",           emoji="🗑️", value="toggle_autodelete"),
                discord.SelectOption(label="Fermer si membre quitté",   emoji="🚪", value="toggle_leave"),
                discord.SelectOption(label="Mention staff a l'ouverture",emoji="📢", value="toggle_mention"),
                discord.SelectOption(label="DM a l'ouverture",           emoji="📩", value="toggle_dm_open"),
                discord.SelectOption(label="Transcript MP (fermeture)",  emoji="📄", value="toggle_transcript"),
            ], custom_id="ts2"
        )
        s2.callback = self.cb_behavior
        self.add_item(s2)

        # Menu 3 : Claim
        s3 = discord.ui.Select(
            placeholder="🔒 Claim",
            options=[
                discord.SelectOption(label="Activer/Desactiver le claim",emoji="🔒", value="toggle_claim"),
                discord.SelectOption(label="Autoclaim",                  emoji="📌", value="toggle_autoclaim"),
                discord.SelectOption(label="Claim lock le salon",        emoji="🔑", value="toggle_claimlock"),
                discord.SelectOption(label="Claim caché le salon",       emoji="👁️", value="toggle_claimhide"),
            ], custom_id="ts3"
        )
        s3.callback = self.cb_claim
        self.add_item(s3)

        # Menu 4 : Boutons & Messages
        s4 = discord.ui.Select(
            placeholder="🔘 Boutons & Messages",
            options=[
                discord.SelectOption(label="Bouton claim",              emoji="🔘", value="toggle_btnclaim"),
                discord.SelectOption(label="Bouton fermer",             emoji="🔘", value="toggle_btnclose"),
                discord.SelectOption(label="Bouton ajouter membre",     emoji="🔘", value="toggle_btnadd"),
                discord.SelectOption(label="Message automatique",       emoji="💬", value="auto_msg"),
                discord.SelectOption(label="Message de fermeture",      emoji="🔐", value="close_msg"),
            ], custom_id="ts4"
        )
        s4.callback = self.cb_buttons_msgs
        self.add_item(s4)

        # Menu 5 : Options & Apparence
        s5 = discord.ui.Select(
            placeholder="🎨 Options & Apparence",
            options=[
                discord.SelectOption(label="Ajouter une option",        emoji="➕", value="add_option"),
                discord.SelectOption(label="Supprimer une option",      emoji="➖", value="del_option"),
                discord.SelectOption(label="Personnaliser l'embed panel",emoji="🎨", value="panel_embed"),
                discord.SelectOption(label="Personnaliser l'embed ticket",emoji="🎫",value="ticket_embed"),
                discord.SelectOption(label="Type : bouton ou sélecteur", emoji="🔄", value="toggle_type"),
                discord.SelectOption(label="Envoyer le panel maintenant",emoji="📤", value="send_panel"),
                discord.SelectOption(label="Reset configuration",        emoji="♻️", value="reset"),
            ], custom_id="ts5"
        )
        s5.callback = self.cb_options
        self.add_item(s5)

    async def _toggle(self, interaction, key, default=True):
        cfg = get_ticket_cfg(self.guild_id)
        cfg[key] = not cfg.get(key, default)
        save_ticket_cfg(self.guild_id, cfg)
        await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self)

    async def _role_select(self, interaction, cfg_key, placeholder, multi=True):
        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed][:25]
        if not roles:
            return await interaction.response.send_message("Aucun role disponible.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder=placeholder,
            options=[discord.SelectOption(label=r.name[:25], value=str(r.id)) for r in roles],
            min_values=0, max_values=min(5, len(roles)) if multi else 1,
            custom_id=f"ts_role_{cfg_key}"
        )
        parent = self
        async def role_cb(inter):
            cfg2 = get_ticket_cfg(self.guild_id)
            cfg2[cfg_key] = inter.data["values"]
            save_ticket_cfg(self.guild_id, cfg2)
            await inter.response.edit_message(embed=ticket_settings_embed(inter.guild, cfg2), view=parent)
        sel.callback = role_cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    async def cb_channels_roles(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        cfg = get_ticket_cfg(self.guild_id)

        if val == "category":
            cats = interaction.guild.categories[:25]
            if not cats:
                return await interaction.response.send_message("Aucune catégorie.", ephemeral=True)
            sel = discord.ui.Select(
                placeholder="Choisir la catégorie des tickets",
                options=[discord.SelectOption(label=c.name[:25], value=str(c.id)) for c in cats],
                custom_id="ts_cat"
            )
            parent = self
            async def cat_cb(inter):
                cfg2 = get_ticket_cfg(self.guild_id)
                cfg2["category"] = inter.data["values"][0]
                save_ticket_cfg(self.guild_id, cfg2)
                await inter.response.edit_message(embed=ticket_settings_embed(inter.guild, cfg2), view=parent)
            sel.callback = cat_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        if val == "log_channel":
            chans = [c for c in interaction.guild.text_channels][:25]
            sel = discord.ui.Select(
                placeholder="Choisir le salon de logs",
                options=[discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chans],
                custom_id="ts_log"
            )
            parent = self
            async def log_cb(inter):
                cfg2 = get_ticket_cfg(self.guild_id)
                cfg2["log_channel"] = inter.data["values"][0]
                save_ticket_cfg(self.guild_id, cfg2)
                await inter.response.edit_message(embed=ticket_settings_embed(inter.guild, cfg2), view=parent)
            sel.callback = log_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        if val == "staff_roles":
            return await self._role_select(interaction, "staff_roles", "Choisir les roles staff")
        if val == "required_roles":
            return await self._role_select(interaction, "required_roles", "Roles requis pour ouvrir un ticket")
        if val == "banned_roles":
            return await self._role_select(interaction, "banned_roles", "Roles interdits des tickets")

    async def cb_behavior(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        toggles = {
            "toggle_numbering": "numbering",
            "toggle_autodelete":"auto_delete",
            "toggle_leave":     "close_on_leave",
            "toggle_mention":   "mention_staff",
            "toggle_dm_open":   "dm_on_open",
            "toggle_transcript":"transcript_mp",
        }
        if val in toggles:
            return await self._toggle(interaction, toggles[val])
        if val == "max_tickets":
            return await interaction.response.send_modal(ModalMaxTickets(self.guild_id, self))
        if val == "name_format":
            return await interaction.response.send_modal(ModalNameFormat(self.guild_id, self))

    async def cb_claim(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        toggles = {
            "toggle_claim":      "claim_enabled",
            "toggle_autoclaim":  "autoclaim",
            "toggle_claimlock":  "claim_lock",
            "toggle_claimhide":  "claim_hide",
        }
        if val in toggles:
            return await self._toggle(interaction, toggles[val])

    async def cb_buttons_msgs(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        toggles = {
            "toggle_btnclaim": "btn_claim",
            "toggle_btnclose": "btn_close",
            "toggle_btnadd":   "btn_add",
        }
        if val in toggles:
            return await self._toggle(interaction, toggles[val])
        if val == "auto_msg":
            return await interaction.response.send_modal(ModalAutoMsg(self.guild_id, self))
        if val == "close_msg":
            return await interaction.response.send_modal(ModalCloseMsg(self.guild_id, self))

    async def cb_options(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        cfg = get_ticket_cfg(self.guild_id)

        if val == "add_option":
            return await interaction.response.send_modal(ModalAddOption(self.guild_id, self))

        if val == "del_option":
            opts = cfg.get("options", [])
            if not opts:
                return await interaction.response.send_message("Aucune option.", ephemeral=True)
            sel = discord.ui.Select(
                placeholder="Supprimer une option",
                options=[discord.SelectOption(label=o["label"], emoji=o.get("emoji","🎫"), value=o["label"]) for o in opts],
                custom_id="ts_del_opt"
            )
            parent = self
            async def del_cb(inter):
                cfg2 = get_ticket_cfg(self.guild_id)
                cfg2["options"] = [o for o in cfg2.get("options",[]) if o["label"] != inter.data["values"][0]]
                save_ticket_cfg(self.guild_id, cfg2)
                await inter.response.edit_message(embed=ticket_settings_embed(inter.guild, cfg2), view=parent)
            sel.callback = del_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        if val == "panel_embed":
            return await interaction.response.send_modal(ModalPanelEmbed(self.guild_id, self))
        if val == "ticket_embed":
            return await interaction.response.send_modal(ModalTicketEmbed(self.guild_id, self))

        if val == "toggle_type":
            cfg["panel_type"] = "button" if cfg.get("panel_type") == "selector" else "selector"
            save_ticket_cfg(self.guild_id, cfg)
            return await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg), view=self)

        if val == "send_panel":
            chans = [c for c in interaction.guild.text_channels][:25]
            sel   = discord.ui.Select(
                placeholder="Dans quel salon envoyer le panel ?",
                options=[discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chans],
                custom_id="ts_send_panel"
            )
            parent = self
            async def send_cb(inter):
                cfg2  = get_ticket_cfg(self.guild_id)
                ch_id = inter.data["values"][0]
                ch    = inter.guild.get_channel(int(ch_id))
                if not ch:
                    return await inter.response.send_message("Salon introuvable.", ephemeral=True)
                try: color = int(cfg2.get("panel_color","0x00bfff").replace("0x",""), 16)
                except: color = 0x00bfff
                pe = discord.Embed(title=cfg2.get("panel_title","🎫 Ouvrir un ticket"), description=cfg2.get("panel_desc","Selectionnez un type de ticket."), color=color)
                pe.set_footer(text="Pocoyo - Système de tickets")
                pview = TicketButtonView(self.guild_id) if cfg2.get("panel_type") == "button" else TicketSelectView(self.guild_id)
                await ch.send(embed=pe, view=pview)
                await inter.response.edit_message(embed=ticket_settings_embed(inter.guild, cfg2), view=parent)
            sel.callback = send_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        if val == "reset":
            save_ticket_cfg(self.guild_id, {})
            cfg2 = get_ticket_cfg(self.guild_id)
            return await interaction.response.edit_message(embed=ticket_settings_embed(interaction.guild, cfg2), view=self)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

@bot.command(name="ticket_settings")
@commands.has_permissions(administrator=True)
async def ticket_settings_cmd(ctx):
    """Une seule commande : ouvre le panneau de configuration complet des tickets."""
    cfg  = get_ticket_cfg(ctx.guild.id)
    e    = ticket_settings_embed(ctx.guild, cfg)
    view = TicketSettingsView(ctx.guild)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

@bot.command(name="claim")
@commands.has_permissions(manage_messages=True)
async def claim(ctx):
    if "TICKET_OWNER:" not in (ctx.channel.topic or ""):
        return await ctx.send("Ce n'est pas un salon de ticket.")
    cfg = get_ticket_cfg(ctx.guild.id)
    await do_claim(ctx.channel, ctx.author, ctx.guild, cfg)
    e = discord.Embed(title="🔒 Ticket claim", description=f"Pris en chargé par {ctx.author.mention}.", color=0x00bfff, timestamp=datetime.utcnow())
    await ctx.send(embed=e)

@bot.command(name="rename")
@commands.has_permissions(manage_channels=True)
async def rename_ticket(ctx, *, name: str):
    if "TICKET_OWNER:" not in (ctx.channel.topic or ""):
        return await ctx.send("Ce n'est pas un salon de ticket.")
    await ctx.channel.edit(name=f"ticket-{name}")
    await ctx.send(f"Ticket renommé en **ticket-{name}**.")

@bot.command(name="add")
@commands.has_permissions(manage_channels=True)
async def add_to_ticket(ctx, member: discord.Member):
    if "TICKET_OWNER:" not in (ctx.channel.topic or ""):
        return await ctx.send("Ce n'est pas un salon de ticket.")
    await ctx.channel.set_permissions(member, view_channel=True, send_messages=True)
    await ctx.send(f"{member.mention} ajouté au ticket.")

@bot.command(name="close")
async def close(ctx, *, reason="Ticket resolu"):
    if "TICKET_OWNER:" not in (ctx.channel.topic or ""):
        return await ctx.send("Ce n'est pas un salon de ticket.")
    cfg      = get_ticket_cfg(ctx.guild.id)
    topic    = ctx.channel.topic or ""
    owner_id = None
    if "TICKET_OWNER:" in topic:
        try: owner_id = int(topic.split("TICKET_OWNER:")[1].split(" ")[0])
        except: pass
    close_msg = cfg.get("close_msg") or "Suppression dans 5 secondes..."
    e = discord.Embed(title="🔐 Ticket fermé", description=f"{close_msg}\n\nRaison : {reason}\nFerme par {ctx.author.mention}.", color=0xff4500, timestamp=datetime.utcnow())
    await ctx.send(embed=e)
    if cfg.get("transcript_mp") and owner_id:
        owner = ctx.guild.get_member(owner_id)
        if owner: await send_transcript(ctx.channel, owner)
    if owner_id:
        owner2 = ctx.guild.get_member(owner_id)
        if owner2: await log_ticket(ctx.guild, "close", owner2, ctx.channel, cfg, reason)
    await asyncio.sleep(5)
    if cfg.get("auto_delete"):
        try: await ctx.channel.delete()
        except: pass

@bot.event
async def on_member_remove_ticket(member):
    cfg = get_ticket_cfg(member.guild.id)
    if not cfg.get("close_on_leave"): return
    tickets = [c for c in member.guild.text_channels if c.topic and f"TICKET_OWNER:{member.id}" in c.topic]
    for ch in tickets:
        try:
            e = discord.Embed(title="🔐 Ticket fermé automatiquement", description=f"Le membre **{member}** a quitté le serveur.", color=0xff4500)
            await ch.send(embed=e)
            await asyncio.sleep(3)
            await ch.delete()
        except: pass

@bot.command(name="rolemenu")
@commands.has_permissions(manage_roles=True)
async def rolemenu(ctx):
    if not ctx.message.role_mentions: return await ctx.send("Usage : `+rolemenu @Role1 @Role2 ...`")
    roles  = ctx.message.role_mentions
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    desc   = "\n".join(f"{emojis[i]} - {r.mention}" for i, r in enumerate(roles[:10]))
    e      = discord.Embed(title="Menu de roles", description=desc, color=get_color(ctx.guild.id))
    e.set_footer(text="Reagissez pour obtenir un role")
    msg    = await ctx.send(embed=e)
    for i in range(len(roles[:10])): await msg.add_reaction(emojis[i])
    data   = get_guild("rolemenus.json", ctx.guild.id)
    data[str(msg.id)] = {str(r.id): emojis[i] for i, r in enumerate(roles[:10])}
    set_guild("rolemenus.json", ctx.guild.id, data)

@bot.command(name="reminder")
async def reminder(ctx, duration: str, *, message: str):
    delta = parse_dur(duration)
    if not delta: return await ctx.send("Durée invalide. Ex: `10m`, `2h`")
    await ctx.send(f"Rappel programmé dans **{duration}** !")
    await asyncio.sleep(delta.total_seconds())
    try: await ctx.author.send(f"Rappel : {message}")
    except: await ctx.send(f"{ctx.author.mention} Rappel : {message}")

@bot.command(name="reminder_list")
async def reminder_list_cmd(ctx):
    await ctx.send("Les reminders actifs sont geres en memoire. Ils se reinitient au redémarrage du bot.")

@bot.command(name="custom")
@commands.has_permissions(manage_guild=True)
async def custom(ctx, keyword: str, *, response: str = None):
    if not response: return await ctx.send("Usage : `+custom <mot-cle> <réponse>`")
    data = get_guild("customs.json", ctx.guild.id); data[keyword.lower()] = response
    set_guild("customs.json", ctx.guild.id, data)
    await ctx.send(f"Commande `+{keyword}` créée.")

@bot.command(name="customlist")
async def customlist(ctx):
    data = get_guild("customs.json", ctx.guild.id)
    if not data: return await ctx.send("Aucune commande custom.")
    e = discord.Embed(title="Commandes custom", description="\n".join(f"`+{k}` - {v[:50]}" for k, v in list(data.items())[:20]), color=get_color(ctx.guild.id))
    await ctx.send(embed=e)

@bot.command(name="clear_customs")
@commands.has_permissions(administrator=True)
async def clear_customs(ctx):
    set_guild("customs.json", ctx.guild.id, {}); await ctx.send("Toutes les commandes custom supprimées.")

@bot.command(name="custom_transfer")
@commands.has_permissions(administrator=True)
async def custom_transfer(ctx, source_guild_id: int):
    source = get_guild("customs.json", source_guild_id)
    if not source: return await ctx.send("Aucune commande custom pour ce serveur.")
    dest = get_guild("customs.json", ctx.guild.id); dest.update(source)
    set_guild("customs.json", ctx.guild.id, dest)
    await ctx.send(f"{len(source)} commande(s) custom transférée(s).")

@bot.command(name="massiverole")
@commands.has_permissions(manage_roles=True)
async def massiverole(ctx, role: discord.Role, filter_role: discord.Role = None):
    members = ctx.guild.members if not filter_role else [m for m in ctx.guild.members if filter_role in m.roles]
    msg = await ctx.send(f"Ajout en cours pour {len(members)} membres...")
    for m in members:
        try: await m.add_roles(role)
        except: pass
    await msg.edit(content=f"Role **{role.name}** ajouté a **{len(members)}** membres.")

@bot.command(name="unmassiverole")
@commands.has_permissions(manage_roles=True)
async def unmassiverole(ctx, role: discord.Role):
    members = [m for m in ctx.guild.members if role in m.roles]
    msg = await ctx.send(f"Retrait en cours pour {len(members)} membres...")
    for m in members:
        try: await m.remove_roles(role)
        except: pass
    await msg.edit(content=f"Role **{role.name}** retiré de **{len(members)}** membres.")

@bot.command(name="temprole")
@commands.has_permissions(manage_roles=True)
async def temprole(ctx, member: discord.Member, role: discord.Role, duration: str):
    delta = parse_dur(duration)
    if not delta: return await ctx.send("Durée invalide.")
    await member.add_roles(role)
    await ctx.send(f"Role **{role.name}** ajouté a **{member}** pour **{duration}**.")
    await asyncio.sleep(delta.total_seconds())
    if role in member.roles: await member.remove_roles(role)

@bot.command(name="voicemove")
@commands.has_permissions(administrator=True)
async def voicemove(ctx, from_channel: discord.VoiceChannel, to_channel: discord.VoiceChannel):
    count = 0
    for m in from_channel.members:
        try: await m.move_to(to_channel); count += 1
        except: pass
    await ctx.send(f"**{count}** membre(s) deplace(s) vers **{to_channel.name}**.")

@bot.command(name="voicekick")
@commands.has_permissions(administrator=True)
async def voicekick(ctx, *members: discord.Member):
    count = 0
    for member in members:
        if member.voice:
            try: await member.move_to(None); count += 1
            except: pass
    await ctx.send(f"**{count}** membre(s) deconnecte(s) du vocal.")

@bot.command(name="cleanup")
@commands.has_permissions(administrator=True)
async def cleanup_voice(ctx, channel: discord.VoiceChannel = None):
    if not channel: return await ctx.send("Precise un salon vocal.")
    count = len(channel.members)
    for m in channel.members:
        try: await m.move_to(None)
        except: pass
    await ctx.send(f"**{count}** membre(s) deconnecte(s) de **{channel.name}**.")

@bot.command(name="bringall")
@commands.has_permissions(administrator=True)
async def bringall(ctx, channel: discord.VoiceChannel = None):
    if not ctx.author.voice and not channel: return await ctx.send("Tu dois etre dans un vocal ou préciser un salon.")
    target  = channel or ctx.author.voice.channel
    members = [m for vc in ctx.guild.voice_channels for m in vc.members if vc != target]
    count   = 0
    for m in members:
        try: await m.move_to(target); count += 1
        except: pass
    await ctx.send(f"**{count}** membre(s) deplace(s) vers **{target.name}**.")

@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, duration: int, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    if duration > 21600: return await ctx.send("Maximum 6 heures (21600s).")
    await channel.edit(slowmode_delay=duration)
    await ctx.send(f"Mode lent : **{duration}s** dans {channel.mention}." if duration else f"Mode lent désactivé dans {channel.mention}.")

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_perms(ctx, target: str = "all"):
    if target == "all":
        count = 0
        for channel in ctx.guild.channels:
            try: await channel.edit(sync_permissions=True); count += 1
            except: pass
        await ctx.send(f"Permissions synchronisees sur **{count}** salons.")
    else:
        try:
            ch = await commands.TextChannelConverter().convert(ctx, target)
            await ch.edit(sync_permissions=True)
            await ctx.send(f"Permissions de **{ch.name}** synchronisees.")
        except: await ctx.send("Salon introuvable.")

@bot.command(name="autoreact")
@commands.has_permissions(administrator=True)
async def autoreact_cmd(ctx, action: str, channel: discord.TextChannel = None, emoji: str = None):
    cfg = get_guild("modconfig.json", ctx.guild.id); ar = cfg.get("autoreacts",{})
    if action.lower() == "list":
        e = discord.Embed(title="Autoreacts", color=get_color(ctx.guild.id))
        if not ar: e.description = "*Aucun autoreact configuré.*"
        else:
            for cid, emojis in ar.items():
                ch2 = ctx.guild.get_channel(int(cid))
                e.add_field(name=ch2.mention if ch2 else cid, value=" ".join(emojis))
        return await ctx.send(embed=e)
    channel = channel or ctx.channel
    if action.lower() == "add" and emoji:
        ar.setdefault(str(channel.id),[])
        if emoji not in ar[str(channel.id)]: ar[str(channel.id)].append(emoji)
        await ctx.send(f"Réaction {emoji} ajoutée dans {channel.mention}.")
    elif action.lower() == "del" and emoji:
        if str(channel.id) in ar and emoji in ar[str(channel.id)]: ar[str(channel.id)].remove(emoji)
        await ctx.send(f"Réaction {emoji} supprimée de {channel.mention}.")
    cfg["autoreacts"] = ar; set_guild("modconfig.json", ctx.guild.id, cfg)

@bot.command(name="backup")
@commands.has_permissions(administrator=True)
async def backup(ctx, backup_type: str = "serveur", *, name: str = None):
    name = name or f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    data = get_guild("backups.json", ctx.guild.id)
    if backup_type.lower() == "serveur":
        bdata = {
            "name": name, "date": datetime.utcnow().isoformat(), "type": "serveur",
            "roles":    [{"name":r.name,"color":str(r.color),"hoist":r.hoist,"perms":r.permissions.value} for r in ctx.guild.roles if not r.managed and r != ctx.guild.default_role],
            "channels": [{"name":c.name,"type":str(c.type),"position":c.position} for c in ctx.guild.channels]
        }
        data[name] = bdata
        e = discord.Embed(title="Backup créé", color=0x00ff00)
        e.add_field(name="Nom", value=name); e.add_field(name="Type", value="Serveur")
        e.add_field(name="Roles", value=str(len(bdata["roles"]))); e.add_field(name="Salons", value=str(len(bdata["channels"])))
    elif backup_type.lower() == "emoji":
        emojis = [{"name":em.name,"url":str(em.url)} for em in ctx.guild.emojis]
        data[name] = {"name":name,"date":datetime.utcnow().isoformat(),"type":"emoji","emojis":emojis}
        e = discord.Embed(title="Backup emojis créé", color=0x00ff00)
        e.add_field(name="Nom", value=name); e.add_field(name="Emojis", value=str(len(emojis)))
    else: return await ctx.send("Type invalide. Choix : `serveur` ou `emoji`")
    set_guild("backups.json", ctx.guild.id, data); await ctx.send(embed=e)

@bot.command(name="backup_list")
@commands.has_permissions(administrator=True)
async def backup_list(ctx):
    data = get_guild("backups.json", ctx.guild.id)
    if not data: return await ctx.send("Aucun backup.")
    e = discord.Embed(title="Liste des backups", color=get_color(ctx.guild.id))
    for name, b in list(data.items())[:10]: e.add_field(name=name, value=f"Type : {b.get('type','?')} | Date : {b.get('date','?')[:10]}", inline=False)
    await ctx.send(embed=e)

@bot.command(name="backup_delete")
@commands.has_permissions(administrator=True)
async def backup_delete(ctx, *, name: str):
    data = get_guild("backups.json", ctx.guild.id)
    if name not in data: return await ctx.send(f"Backup `{name}` introuvable.")
    del data[name]; set_guild("backups.json", ctx.guild.id, data)
    await ctx.send(f"Backup **{name}** supprimée.")

@bot.command(name="backup_load")
@commands.has_permissions(administrator=True)
async def backup_load(ctx, backup_type: str, *, name: str):
    data   = get_guild("backups.json", ctx.guild.id); backup = data.get(name)
    if not backup: return await ctx.send(f"Backup `{name}` introuvable.")
    if backup_type.lower() == "emoji" and backup.get("type") == "emoji":
        count = 0
        for em in backup.get("emojis",[]):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(em["url"]) as r: img = await r.read()
                await ctx.guild.create_custom_emoji(name=em["name"], image=img); count += 1
            except: pass
        await ctx.send(f"{count} emoji(s) restaure(s) depuis la backup **{name}**.")
    else: await ctx.send(f"Backup **{name}** chargée (restauration manuelle des roles/salons).")

@bot.command(name="autobackup")
@commands.has_permissions(administrator=True)
async def autobackup(ctx, backup_type: str, jours: int):
    cfg = get_guild("modconfig.json", ctx.guild.id); cfg["autobackup"] = {"type":backup_type,"days":jours}
    set_guild("modconfig.json", ctx.guild.id, cfg)
    await ctx.send(f"Backup automatique `{backup_type}` tous les **{jours}** jours.")

@bot.command(name="loading")
@commands.has_permissions(manage_messages=True)
async def loading(ctx, duration: int, *, message: str = "Chargement..."):
    bar_length = 10; msg = await ctx.send(f"{message}\n`{'░'*bar_length}` 0%")
    for i in range(1, bar_length + 1):
        await asyncio.sleep(duration / bar_length)
        filled = "█" * i; empty = "░" * (bar_length - i); pct = int((i / bar_length) * 100)
        await msg.edit(content=f"{message}\n`{filled}{empty}` {pct}%")

@bot.command(name="restrict")
@commands.has_permissions(administrator=True)
async def restrict_cmd(ctx, emoji: str, role: discord.Role):
    cfg = get_guild("modconfig.json", ctx.guild.id); r = cfg.get("restricted_emojis",{})
    r[emoji] = str(role.id); cfg["restricted_emojis"] = r; set_guild("modconfig.json", ctx.guild.id, cfg)
    await ctx.send(f"L'emoji `{emoji}` est reserve a **{role.name}**.")

@bot.command(name="unrestrict")
@commands.has_permissions(administrator=True)
async def unrestrict_cmd(ctx, emoji: str):
    cfg = get_guild("modconfig.json", ctx.guild.id); r = cfg.get("restricted_emojis",{})
    r.pop(emoji, None); cfg["restricted_emojis"] = r; set_guild("modconfig.json", ctx.guild.id, cfg)
    await ctx.send(f"L'emoji `{emoji}` est de nouveau accèssible a tous.")

@bot.command(name="suggestion")
async def suggestion(ctx, *, message: str):
    cfg     = get_guild("suggestions.json", ctx.guild.id)
    channel = ctx.guild.get_channel(int(cfg["channel"])) if cfg.get("channel") else ctx.channel
    e = discord.Embed(title="Nouvelle suggestion", description=message, color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
    e.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
    e.set_footer(text="Pocoyo - Préfixe actuel : +")
    msg = await channel.send(embed=e)
    await msg.add_reaction("✅"); await msg.add_reaction("❌")
    if channel != ctx.channel:
        try: await ctx.message.delete()
        except: pass

@bot.command(name="lb_suggestions")
async def lb_suggestions(ctx):
    await ctx.send("Le classement des suggestions est disponible dans le salon de suggestions configuré.")


def resolve_vars(text, member, invite=None):
    """Remplace les variables dans les messages de bienvenue/départ."""
    if not text:
        return text
    # Calculer le nombre total de personnes invitées par l'inviteur
    inviter_count = "?"
    if invite and invite.inviter:
        try:
            guild_invites = invite_cache.get(member.guild.id, {})
            # On récupère toutes les invitations actives du serveur pour compter celles de l'inviteur
            inviter_total = 0
            for guild in member.guild.me.mutual_guilds:
                if guild.id == member.guild.id:
                    pass
            # Fallback : on utilise les uses de l'invite actuelle
            inviter_count = str(invite.uses) if invite.uses is not None else "?"
        except:
            inviter_count = "?"
    replacements = {
        "{member}":         member.mention,
        "{member_name}":    str(member),
        "{member_id}":      str(member.id),
        "{server}":         member.guild.name,
        "{count}":          str(member.guild.member_count),
        "{inviter}":        str(invite.inviter) if invite and invite.inviter else "Inconnu",
        "{invite_code}":    invite.code if invite else "?",
        "{invite_uses}":    str(invite.uses) if invite else "?",
        "{inviter_count}":  inviter_count,
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text

def _join_embed(guild, cfg):
    """Embed de configuration du système de bienvenue."""
    channel = guild.get_channel(int(cfg["channel"])) if cfg.get("channel") else None
    role    = guild.get_role(int(cfg["role"]))  if cfg.get("role")    else None
    role2   = guild.get_role(int(cfg["role2"])) if cfg.get("role2")   else None
    enabled = cfg.get("enabled", False)

    e = discord.Embed(
        title="📥 Configuration — Bienvenue",
        color=0x00ff00 if enabled else 0x888888
    )
    e.add_field(name="✅ Activé",          value="Oui" if enabled else "Non",              inline=True)
    e.add_field(name="📌 Salon",           value=channel.mention if channel else "*Non défini*", inline=True)
    e.add_field(name="🏷️ Rôle auto 1",    value=role.mention    if role    else "*Aucun*",  inline=True)
    e.add_field(name="🏷️ Rôle auto 2",    value=role2.mention   if role2   else "*Aucun*",  inline=True)
    e.add_field(name="💬 Message texte",   value=cfg.get("message")     or "*Non défini*",  inline=False)
    e.add_field(name="🖼️ Embed",          value="Activé" if cfg.get("use_embed") else "Désactivé", inline=True)
    e.add_field(name="📝 Titre embed",     value=cfg.get("embed_title") or "*Non défini*",  inline=True)
    e.add_field(name="📄 Description",     value=cfg.get("embed_desc")  or "*Non définie*", inline=False)
    e.set_footer(text="Variables dispo : {member} {member_name} {server} {count} {inviter}")
    return e

def _leave_embed(guild, cfg):
    """Embed de configuration du système de départ."""
    channel = guild.get_channel(int(cfg["channel"])) if cfg.get("channel") else None
    enabled = cfg.get("enabled", False)

    e = discord.Embed(
        title="📤 Configuration — Au revoir",
        color=0xff4500 if enabled else 0x888888
    )
    e.add_field(name="✅ Activé",        value="Oui" if enabled else "Non",                inline=True)
    e.add_field(name="📌 Salon",         value=channel.mention if channel else "*Non défini*", inline=True)
    e.add_field(name="💬 Message texte", value=cfg.get("message")     or "*Non défini*",    inline=False)
    e.add_field(name="🖼️ Embed",        value="Activé" if cfg.get("use_embed") else "Désactivé", inline=True)
    e.add_field(name="📝 Titre embed",   value=cfg.get("embed_title") or "*Non défini*",    inline=True)
    e.add_field(name="📄 Description",   value=cfg.get("embed_desc")  or "*Non définie*",   inline=False)
    e.set_footer(text="Variables dispo : {member} {member_name} {server} {count}")
    return e

class JoinSettingsView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.guild   = guild
        self.message = None

    async def refresh(self, interaction):
        cfg = get_guild("joinsettings.json", self.guild.id)
        await interaction.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="📌 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        chans = interaction.guild.text_channels[:25]
        sel   = discord.ui.Select(placeholder="Salon de bienvenue", options=[
            discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chans
        ])
        async def cb(inter):
            cfg = get_guild("joinsettings.json", self.guild.id)
            cfg["channel"] = inter.data["values"][0]
            set_guild("joinsettings.json", self.guild.id, cfg)
            await inter.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)
        sel.callback = cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="🏷️ Rôle auto 1", style=discord.ButtonStyle.primary, row=0)
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed and r.position < interaction.guild.me.top_role.position][:25]
        sel   = discord.ui.Select(placeholder="Rôle attribué à l'arrivée", options=[
            discord.SelectOption(label=r.name[:25], value=str(r.id)) for r in roles
        ])
        async def cb(inter):
            cfg = get_guild("joinsettings.json", self.guild.id)
            cfg["role"] = inter.data["values"][0]
            set_guild("joinsettings.json", self.guild.id, cfg)
            await inter.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)
        sel.callback = cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="🏷️ Rôle auto 2", style=discord.ButtonStyle.secondary, row=0)
    async def set_role2(self, interaction: discord.Interaction, button: discord.ui.Button):
        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed and r.position < interaction.guild.me.top_role.position][:25]
        sel   = discord.ui.Select(placeholder="2ème rôle attribué à l'arrivée", options=[
            discord.SelectOption(label=r.name[:25], value=str(r.id)) for r in roles
        ])
        async def cb(inter):
            cfg = get_guild("joinsettings.json", self.guild.id)
            cfg["role2"] = inter.data["values"][0]
            set_guild("joinsettings.json", self.guild.id, cfg)
            await inter.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)
        sel.callback = cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="🔔 Activer/Désactiver", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("joinsettings.json", self.guild.id)
        cfg["enabled"] = not cfg.get("enabled", False)
        set_guild("joinsettings.json", self.guild.id, cfg)
        await interaction.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="💬 Message texte", style=discord.ButtonStyle.primary, row=1)
    async def set_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("joinsettings.json", self.guild, "message", "Message de bienvenue", self, _join_embed))

    @discord.ui.button(label="📝 Titre embed", style=discord.ButtonStyle.primary, row=1)
    async def set_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("joinsettings.json", self.guild, "embed_title", "Titre de l'embed", self, _join_embed))

    @discord.ui.button(label="📄 Description embed", style=discord.ButtonStyle.primary, row=1)
    async def set_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("joinsettings.json", self.guild, "embed_desc", "Description de l'embed", self, _join_embed, paragraph=True))

    @discord.ui.button(label="🎨 Couleur embed", style=discord.ButtonStyle.secondary, row=1)
    async def set_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("joinsettings.json", self.guild, "embed_color", "Couleur hex (ex: 00ff00)", self, _join_embed, placeholder="00ff00"))

    @discord.ui.button(label="🖼️ Embed on/off", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("joinsettings.json", self.guild.id)
        cfg["use_embed"] = not cfg.get("use_embed", False)
        set_guild("joinsettings.json", self.guild.id, cfg)
        await interaction.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="🖼️ Image (avatar)", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("joinsettings.json", self.guild.id)
        cfg["embed_image"] = not cfg.get("embed_image", False)
        set_guild("joinsettings.json", self.guild.id, cfg)
        await interaction.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="👁️ Aperçu", style=discord.ButtonStyle.success, row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("joinsettings.json", self.guild.id)
        msg, embed = build_join_leave_msg(cfg, interaction.user)
        await interaction.response.send_message(content=msg, embed=embed, ephemeral=True)

    @discord.ui.button(label="🗑️ Reset", style=discord.ButtonStyle.danger, row=2)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_guild("joinsettings.json", self.guild.id, {})
        cfg = get_guild("joinsettings.json", self.guild.id)
        await interaction.response.edit_message(embed=_join_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="📖 Variables", style=discord.ButtonStyle.secondary, row=3)
    async def show_vars(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = discord.Embed(title="📖 Variables disponibles — Bienvenue", color=0x5865f2)
        e.add_field(name="`{member}`",       value="Mention du membre",                    inline=False)
        e.add_field(name="`{member_name}`",  value="Nom du membre (ex: Jean#1234)",        inline=False)
        e.add_field(name="`{member_id}`",    value="ID du membre",                         inline=False)
        e.add_field(name="`{server}`",       value="Nom du serveur",                       inline=False)
        e.add_field(name="`{count}`",        value="Nombre de membres sur le serveur",     inline=False)
        e.add_field(name="`{inviter}`",      value="Nom de la personne qui a invité",      inline=False)
        e.add_field(name="`{invite_code}`",  value="Code de l'invitation utilisée",        inline=False)
        e.add_field(name="`{invite_uses}`",  value="Nombre d'utilisations de l'invitation",inline=False)
        e.add_field(name="`{inviter_count}`",value="Nombre de membres invités par l'inviteur (via cette invitation)", inline=False)
        e.set_footer(text="Ces variables fonctionnent dans le message texte, le titre et la description de l'embed.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class LeaveSettingsView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.guild   = guild
        self.message = None

    @discord.ui.button(label="📌 Salon", style=discord.ButtonStyle.primary, row=0)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        chans = interaction.guild.text_channels[:25]
        sel   = discord.ui.Select(placeholder="Salon d'au revoir", options=[
            discord.SelectOption(label=f"#{c.name}"[:25], value=str(c.id)) for c in chans
        ])
        async def cb(inter):
            cfg = get_guild("leavesettings.json", self.guild.id)
            cfg["channel"] = inter.data["values"][0]
            set_guild("leavesettings.json", self.guild.id, cfg)
            await inter.response.edit_message(embed=_leave_embed(self.guild, cfg), view=self)
        sel.callback = cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="🔔 Activer/Désactiver", style=discord.ButtonStyle.secondary, row=0)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("leavesettings.json", self.guild.id)
        cfg["enabled"] = not cfg.get("enabled", False)
        set_guild("leavesettings.json", self.guild.id, cfg)
        await interaction.response.edit_message(embed=_leave_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="💬 Message texte", style=discord.ButtonStyle.primary, row=1)
    async def set_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("leavesettings.json", self.guild, "message", "Message de départ", self, _leave_embed))

    @discord.ui.button(label="📝 Titre embed", style=discord.ButtonStyle.primary, row=1)
    async def set_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("leavesettings.json", self.guild, "embed_title", "Titre de l'embed", self, _leave_embed))

    @discord.ui.button(label="📄 Description embed", style=discord.ButtonStyle.primary, row=1)
    async def set_desc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("leavesettings.json", self.guild, "embed_desc", "Description de l'embed", self, _leave_embed, paragraph=True))

    @discord.ui.button(label="🎨 Couleur embed", style=discord.ButtonStyle.secondary, row=1)
    async def set_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(JoinLeaveTextModal("leavesettings.json", self.guild, "embed_color", "Couleur hex (ex: ff4500)", self, _leave_embed, placeholder="ff4500"))

    @discord.ui.button(label="🖼️ Embed on/off", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("leavesettings.json", self.guild.id)
        cfg["use_embed"] = not cfg.get("use_embed", False)
        set_guild("leavesettings.json", self.guild.id, cfg)
        await interaction.response.edit_message(embed=_leave_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="🖼️ Image (avatar)", style=discord.ButtonStyle.secondary, row=2)
    async def toggle_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("leavesettings.json", self.guild.id)
        cfg["embed_image"] = not cfg.get("embed_image", False)
        set_guild("leavesettings.json", self.guild.id, cfg)
        await interaction.response.edit_message(embed=_leave_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="👁️ Aperçu", style=discord.ButtonStyle.success, row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = get_guild("leavesettings.json", self.guild.id)
        msg, embed = build_join_leave_msg(cfg, interaction.user)
        await interaction.response.send_message(content=msg, embed=embed, ephemeral=True)

    @discord.ui.button(label="🗑️ Reset", style=discord.ButtonStyle.danger, row=2)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_guild("leavesettings.json", self.guild.id, {})
        cfg = get_guild("leavesettings.json", self.guild.id)
        await interaction.response.edit_message(embed=_leave_embed(self.guild, cfg), view=self)

    @discord.ui.button(label="📖 Variables", style=discord.ButtonStyle.secondary, row=3)
    async def show_vars(self, interaction: discord.Interaction, button: discord.ui.Button):
        e = discord.Embed(title="📖 Variables disponibles — Au revoir", color=0x5865f2)
        e.add_field(name="`{member}`",      value="Mention du membre",                inline=False)
        e.add_field(name="`{member_name}`", value="Nom du membre (ex: Jean#1234)",    inline=False)
        e.add_field(name="`{member_id}`",   value="ID du membre",                     inline=False)
        e.add_field(name="`{server}`",      value="Nom du serveur",                   inline=False)
        e.add_field(name="`{count}`",       value="Nombre de membres sur le serveur", inline=False)
        e.set_footer(text="Ces variables fonctionnent dans le message texte, le titre et la description de l'embed.")
        await interaction.response.send_message(embed=e, ephemeral=True)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class JoinLeaveTextModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Valeur", max_length=1000)
    def __init__(self, db_file, guild, cfg_key, title, parent, embed_fn, paragraph=False, placeholder=""):
        super().__init__(title=title[:45])
        self.db_file  = db_file
        self.guild    = guild
        self.cfg_key  = cfg_key
        self.parent   = parent
        self.embed_fn = embed_fn
        self.value.style       = discord.TextStyle.paragraph if paragraph else discord.TextStyle.short
        self.value.placeholder = placeholder or f"Valeur pour {cfg_key}. Variables: {{member}} {{server}} {{count}}"
        self.value.required    = False
    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_guild(self.db_file, self.guild.id)
        cfg[self.cfg_key] = str(self.value).strip()
        set_guild(self.db_file, self.guild.id, cfg)
        await interaction.response.edit_message(embed=self.embed_fn(self.guild, cfg), view=self.parent)

def build_join_leave_msg(cfg, member, invite=None):
    """Construit le message/embed de bienvenue ou départ."""
    text    = resolve_vars(cfg.get("message",""), member, invite) if cfg.get("message") else None
    embed   = None
    if cfg.get("use_embed"):
        try: color = int(cfg.get("embed_color","00ff00").replace("#","").replace("0x",""), 16)
        except: color = 0x00ff00
        title = resolve_vars(cfg.get("embed_title","") or "", member, invite) or None
        desc  = resolve_vars(cfg.get("embed_desc","")  or "", member, invite) or None
        embed = discord.Embed(title=title, description=desc, color=color)
        if cfg.get("embed_image"):
            embed.set_thumbnail(url=member.display_avatar.url)
    return text, embed

@bot.command(name="join_settings")
@commands.has_permissions(administrator=True)
async def join_settings(ctx):
    cfg  = get_guild("joinsettings.json", ctx.guild.id)
    e    = _join_embed(ctx.guild, cfg)
    view = JoinSettingsView(ctx.guild)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

@bot.command(name="leave_settings")
@commands.has_permissions(administrator=True)
async def leave_settings(ctx):
    cfg  = get_guild("leavesettings.json", ctx.guild.id)
    e    = _leave_embed(ctx.guild, cfg)
    view = LeaveSettingsView(ctx.guild)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

@bot.command(name="join_channel")
@commands.has_permissions(administrator=True)
async def join_channel(ctx, channel: discord.TextChannel):
    cfg = get_guild("joinsettings.json", ctx.guild.id); cfg["channel"] = str(channel.id)
    set_guild("joinsettings.json", ctx.guild.id, cfg); await ctx.send(f"Salon de bienvenue : {channel.mention}")

@bot.command(name="join_role")
@commands.has_permissions(administrator=True)
async def join_role(ctx, role: discord.Role):
    cfg = get_guild("joinsettings.json", ctx.guild.id); cfg["role"] = str(role.id)
    set_guild("joinsettings.json", ctx.guild.id, cfg); await ctx.send(f"Rôle auto à l'arrivée : **{role.name}**")

@bot.command(name="join_message")
@commands.has_permissions(administrator=True)
async def join_message_cmd(ctx, *, message: str):
    cfg = get_guild("joinsettings.json", ctx.guild.id); cfg["message"] = message
    set_guild("joinsettings.json", ctx.guild.id, cfg)
    await ctx.send("Message défini.")

@bot.command(name="leave_channel")
@commands.has_permissions(administrator=True)
async def leave_channel(ctx, channel: discord.TextChannel):
    cfg = get_guild("leavesettings.json", ctx.guild.id); cfg["channel"] = str(channel.id)
    set_guild("leavesettings.json", ctx.guild.id, cfg); await ctx.send(f"Salon d'au revoir : {channel.mention}")

@bot.command(name="leave_message")
@commands.has_permissions(administrator=True)
async def leave_message(ctx, *, message: str):
    cfg = get_guild("leavesettings.json", ctx.guild.id); cfg["message"] = message
    set_guild("leavesettings.json", ctx.guild.id, cfg); await ctx.send("Message défini.")

@bot.command(name="boostembed")
@commands.has_permissions(administrator=True)
async def boostembed_cmd(ctx, action: str = None):
    cfg = get_guild("modconfig.json", ctx.guild.id)
    if not action: return await ctx.send("Usage : `+boostembed on/off` ou `+boostembed test`")
    if action.lower() in ("on","off"):
        cfg["boostembed"] = (action.lower()=="on"); set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Embed de boost {'activé' if action.lower()=='on' else 'désactivé'}.")
    elif action.lower() == "test":
        e = discord.Embed(title="Nouveau boost !", color=0xff73fa, timestamp=datetime.utcnow())
        e.description = f"{ctx.author.mention} vient de booster le serveur !"; e.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=e)

@bot.command(name="set_boostembed")
@commands.has_permissions(administrator=True)
async def set_boostembed(ctx):
    e = discord.Embed(title="Configuration embed boost", color=0xff73fa)
    e.description = "`+boostembed on` — Activer\n`+boostembed off` — Desactiver\n`+boostembed test` — Tester\n`+boostlog on #salon` — Salon de logs boost"
    await ctx.send(embed=e)



@bot.command(name="show_pics")
@commands.has_permissions(administrator=True)
async def show_pics(ctx, channel: discord.TextChannel = None):
    cfg = get_guild("modconfig.json", ctx.guild.id)
    if channel:
        cfg["show_pics_channel"] = str(channel.id); set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Photos de profil aleatoires dans {channel.mention}.")
    else:
        cfg.pop("show_pics_channel",None); set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send("Envoi automatique de photos de profil désactivé.")

@bot.command(name="autodelete")
@commands.has_permissions(administrator=True)
async def autodelete_cmd(ctx, target: str, action: str):
    cfg = get_guild("modconfig.json", ctx.guild.id); key = f"autodelete_{target.lower()}"
    if action.lower() in ("on","off"):
        cfg[key] = (action.lower()=="on"); set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Suppression automatique `{target}` {'activée' if action.lower()=='on' else 'désactivée'}.")
    else:
        delta = parse_dur(action)
        if delta:
            cfg[key] = delta.total_seconds(); set_guild("modconfig.json", ctx.guild.id, cfg)
            await ctx.send(f"Suppression automatique `{target}` dans **{action}**.")
        else: await ctx.send("Valeur invalide.")

@bot.command(name="piconly")
@commands.has_permissions(administrator=True)
async def piconly_cmd(ctx, action: str, channel: discord.TextChannel = None):
    channel = channel or ctx.channel; cfg = get_guild("modconfig.json", ctx.guild.id); po = cfg.get("piconly",[])
    if action.lower() == "add":
        if str(channel.id) not in po: po.append(str(channel.id))
        await ctx.send(f"{channel.mention} est maintenant un salon photos uniquement.")
    elif action.lower() == "del":
        if str(channel.id) in po: po.remove(str(channel.id))
        await ctx.send(f"{channel.mention} n'est plus un salon photos uniquement.")
    cfg["piconly"] = po; set_guild("modconfig.json", ctx.guild.id, cfg)

@bot.command(name="public")
@commands.has_permissions(administrator=True)
async def public_cmd(ctx, action: str, channel: discord.TextChannel = None):
    cfg = get_guild("modconfig.json", ctx.guild.id)
    if action.lower() in ("on","off"):
        cfg["public_commands"] = (action.lower()=="on"); set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Commandes publiques {'autorisees' if action.lower()=='on' else 'interdites'}.")
    elif action.lower() in ("allow","deny","reset") and channel:
        pc = cfg.get("public_channels",{})
        if action.lower() == "reset": pc.pop(str(channel.id),None)
        else: pc[str(channel.id)] = action.lower()
        cfg["public_channels"] = pc; set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Commandes publiques `{action}` dans {channel.mention}.")

@bot.command(name="set_perm")
@commands.has_permissions(administrator=True)
async def set_perm_cmd(ctx, permission: str, target: discord.Role = None):
    cfg = get_guild("modconfig.json", ctx.guild.id); perms = cfg.get("custom_perms",{})
    if target:
        perms[permission] = str(target.id); cfg["custom_perms"] = perms; set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Permission `{permission}` accordee a **{target.name}**.")
    else: await ctx.send("Precise un role.")

@bot.command(name="del_perm")
@commands.has_permissions(administrator=True)
async def del_perm_cmd(ctx, role: discord.Role):
    cfg = get_guild("modconfig.json", ctx.guild.id); perms = cfg.get("custom_perms",{})
    cfg["custom_perms"] = {k:v for k,v in perms.items() if v != str(role.id)}
    set_guild("modconfig.json", ctx.guild.id, cfg); await ctx.send(f"Permissions de **{role.name}** supprimées.")

@bot.command(name="clear_perms")
@commands.has_permissions(administrator=True)
async def clear_perms_cmd(ctx):
    cfg = get_guild("modconfig.json", ctx.guild.id); cfg["custom_perms"] = {}
    set_guild("modconfig.json", ctx.guild.id, cfg); await ctx.send("Toutes les permissions du bot supprimées.")

@bot.command(name="strikes")
@commands.has_permissions(manage_guild=True)
async def strikes_cmd(ctx, trigger: str = None, nombre: int = None, mode: str = None):
    cfg = get_guild("modconfig.json", ctx.guild.id); strikes = cfg.get("strikes",{})
    if not trigger:
        e = discord.Embed(title="Strikes configurés", color=get_color(ctx.guild.id))
        if not strikes: e.description = "*Aucun strike configuré.*"
        else:
            for t, v in strikes.items(): e.add_field(name=t, value=f"Nouveau : {v.get('nouveau',1)} | Ancien : {v.get('ancien',1)}")
        return await ctx.send(embed=e)
    if nombre is not None:
        if trigger not in strikes: strikes[trigger] = {}
        if mode == "ancien": strikes[trigger]["ancien"] = nombre
        else: strikes[trigger]["nouveau"] = nombre
        cfg["strikes"] = strikes; set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Strikes pour `{trigger}` mis à jour.")

@bot.command(name="ancien")
@commands.has_permissions(administrator=True)
async def ancien_cmd(ctx, duration: str):
    delta = parse_dur(duration)
    if not delta: return await ctx.send("Durée invalide. Ex: `30d`")
    cfg = get_guild("modconfig.json", ctx.guild.id); cfg["ancien_duration"] = delta.total_seconds()
    set_guild("modconfig.json", ctx.guild.id, cfg); await ctx.send(f"Membre considere comme ancien apres **{duration}**.")

@bot.command(name="punish")
@commands.has_permissions(administrator=True)
async def punish_cmd(ctx, action: str = None, nombre: int = None, durée: str = None, sanction: str = None, sanction_duree: str = None):
    cfg = get_guild("modconfig.json", ctx.guild.id); punishes = cfg.get("auto_punish",[])
    if not action:
        e = discord.Embed(title="Sanctions automatiques", color=get_color(ctx.guild.id))
        if not punishes: e.description = "*Aucune sanction configurée.*"
        else:
            for i, p in enumerate(punishes,1): e.add_field(name=f"#{i}", value=f"{p['strikes']} strikes en {p['durée']} -> {p['sanction']}", inline=False)
        return await ctx.send(embed=e)
    if action.lower() == "add" and nombre and durée and sanction:
        punishes.append({"strikes":nombre,"durée":durée,"sanction":sanction,"sanction_duree":sanction_duree})
        cfg["auto_punish"] = punishes; set_guild("modconfig.json", ctx.guild.id, cfg)
        await ctx.send(f"Sanction ajoutée : {nombre} strikes en {duree} -> {sanction}.")
    elif action.lower() == "del" and nombre:
        if 1 <= nombre <= len(punishes):
            punishes.pop(nombre-1); cfg["auto_punish"] = punishes; set_guild("modconfig.json", ctx.guild.id, cfg)
            await ctx.send(f"Sanction #{nombre} supprimée.")
    elif action.lower() == "setup":
        cfg["auto_punish"] = [
            {"strikes":3,"durée":"1h","sanction":"warn","sanction_duree":None},
            {"strikes":5,"durée":"1h","sanction":"muté","sanction_duree":"1h"},
            {"strikes":7,"durée":"1h","sanction":"kick","sanction_duree":None},
            {"strikes":10,"durée":"1h","sanction":"tempban","sanction_duree":"1d"}
        ]
        set_guild("modconfig.json", ctx.guild.id, cfg); await ctx.send("Sanctions par defaut retablies.")

@bot.command(name="noderank")
@commands.has_permissions(administrator=True)
async def noderank_cmd(ctx, action: str, role: discord.Role):
    cfg = get_guild("modconfig.json", ctx.guild.id); nr = cfg.get("noderank",[])
    if action.lower() == "add":
        if str(role.id) not in nr: nr.append(str(role.id))
        await ctx.send(f"**{role.name}** ne sera plus supprimé lors d'un derank.")
    elif action.lower() == "del":
        if str(role.id) in nr: nr.remove(str(role.id))
        await ctx.send(f"**{role.name}** sera a nouveau supprimé lors d'un derank.")
    cfg["noderank"] = nr; set_guild("modconfig.json", ctx.guild.id, cfg)

@bot.command(name="clear_limit")
@commands.has_permissions(administrator=True)
async def clear_limit(ctx, nombre: int):
    cfg = get_guild("modconfig.json", ctx.guild.id); cfg["clear_limit"] = nombre
    set_guild("modconfig.json", ctx.guild.id, cfg); await ctx.send(f"Limite de clear définie a **{nombre}** messages.")

@bot.command(name="serverinfo")
async def serverinfo(ctx):
    g = ctx.guild
    e = discord.Embed(title=g.name, color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
    e.add_field(name="Membres",      value=g.member_count)
    e.add_field(name="Salons",       value=len(g.channels))
    e.add_field(name="Roles",        value=len(g.roles))
    e.add_field(name="Boosts",       value=g.premium_subscription_count)
    e.add_field(name="Niveau boost", value=g.premium_tier)
    e.add_field(name="Créé le",      value=g.created_at.strftime("%d/%m/%Y"))
    e.add_field(name="Propriétaire", value=str(g.owner))
    e.add_field(name="ID",           value=str(g.id))
    if g.icon: e.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=e)

@bot.command(name="user")
async def user_info(ctx, member: discord.Member = None):
    member = member or ctx.author
    e      = discord.Embed(title=str(member), color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
    e.add_field(name="ID",        value=member.id)
    e.add_field(name="Bot",       value="Oui" if member.bot else "Non")
    e.add_field(name="Créé le",   value=member.created_at.strftime("%d/%m/%Y"))
    e.add_field(name="A rejoint", value=member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "?")
    roles = [r.mention for r in member.roles[1:]]
    e.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:10]) or "*Aucun*", inline=False)
    e.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="member")
async def member_info(ctx, member: discord.Member = None):
    member = member or ctx.author
    e      = discord.Embed(title=f"{member} (Serveur)", color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
    e.add_field(name="ID",        value=member.id)
    e.add_field(name="Surnom",    value=member.nick or "Aucun")
    e.add_field(name="Booster",   value="Oui" if member.premium_since else "Non")
    e.add_field(name="A rejoint", value=member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "?")
    roles = [r.mention for r in member.roles[1:]]
    e.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:10]) or "*Aucun*", inline=False)
    e.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=e)

@bot.command(name="role")
async def role_info(ctx, role: discord.Role):
    e = discord.Embed(title=role.name, color=role.color, timestamp=datetime.utcnow())
    e.add_field(name="ID",           value=role.id)
    e.add_field(name="Membres",      value=len(role.members))
    e.add_field(name="Mentionnable", value="Oui" if role.mentionable else "Non")
    e.add_field(name="Hisse",        value="Oui" if role.hoist else "Non")
    e.add_field(name="Position",     value=role.position)
    e.add_field(name="Créé le",      value=role.created_at.strftime("%d/%m/%Y"))
    await ctx.send(embed=e)

@bot.command(name="channel")
async def channel_info(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    e = discord.Embed(title=f"#{channel.name}", color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
    e.add_field(name="ID",        value=str(channel.id))
    e.add_field(name="Catégorie", value=channel.category.name if channel.category else "Aucune")
    e.add_field(name="NSFW",      value="Oui" if channel.is_nsfw() else "Non")
    e.add_field(name="Slowmode",  value=f"{channel.slowmode_delay}s" if channel.slowmode_delay else "Désactivé")
    e.add_field(name="Créé le",   value=channel.created_at.strftime("%d/%m/%Y"))
    if channel.topic: e.add_field(name="Sujet", value=channel.topic, inline=False)
    await ctx.send(embed=e)

@bot.command(name="pic")
async def pic(ctx, member: discord.Member = None):
    member = member or ctx.author
    e      = discord.Embed(color=get_color(ctx.guild.id))
    e.set_image(url=member.display_avatar.url); e.set_footer(text=f"Photo de profil de {member}")
    await ctx.send(embed=e)

@bot.command(name="banner")
async def banner(ctx, member: discord.Member = None):
    member = member or ctx.author
    user   = await bot.fetch_user(member.id)
    if not user.banner: return await ctx.send(f"**{member}** n'a pas de banniere.")
    e = discord.Embed(color=get_color(ctx.guild.id)); e.set_image(url=user.banner.url); e.set_footer(text=f"Banniere de {member}")
    await ctx.send(embed=e)

@bot.command(name="server_pic")
async def server_pic(ctx):
    if not ctx.guild.icon: return await ctx.send("Ce serveur n'a pas d'icone.")
    e = discord.Embed(color=get_color(ctx.guild.id)); e.set_image(url=ctx.guild.icon.url); e.set_footer(text=f"Icone de {ctx.guild.name}")
    await ctx.send(embed=e)

@bot.command(name="server_banner")
async def server_banner(ctx):
    if not ctx.guild.banner: return await ctx.send("Ce serveur n'a pas de banniere.")
    e = discord.Embed(color=get_color(ctx.guild.id)); e.set_image(url=ctx.guild.banner.url); e.set_footer(text=f"Banniere de {ctx.guild.name}")
    await ctx.send(embed=e)


@bot.command(name="boosters")
async def boosters(ctx):
    bl = ctx.guild.premium_subscribers
    if not bl: return await ctx.send("Aucun booster.")
    e = discord.Embed(title=f"Boosters ({len(bl)})", description="\n".join(f"- {b.mention}" for b in bl[:20]), color=0xff73fa)
    await ctx.send(embed=e)

@bot.command(name="allbots")
async def allbots(ctx):
    bots = [m for m in ctx.guild.members if m.bot]
    e    = discord.Embed(title=f"Bots ({len(bots)})", description="\n".join(f"- {b.mention}" for b in bots), color=get_color(ctx.guild.id))
    await ctx.send(embed=e)

@bot.command(name="botadmins")
async def botadmins(ctx):
    admins = [m for m in ctx.guild.members if m.bot and m.guild_permissions.administrator]
    e      = discord.Embed(title=f"Bots administrateurs ({len(admins)})", description="\n".join(f"- {b.mention}" for b in admins) or "*Aucun*", color=get_color(ctx.guild.id))
    await ctx.send(embed=e)

@bot.command(name="alladmins")
async def alladmins(ctx):
    admins = [m for m in ctx.guild.members if not m.bot and m.guild_permissions.administrator]
    e      = discord.Embed(title=f"Admins ({len(admins)})", description="\n".join(f"- {a.mention}" for a in admins), color=0xffd700)
    await ctx.send(embed=e)

@bot.command(name="rolemembers")
async def rolemembers(ctx, role: discord.Role):
    if not role.members: return await ctx.send(f"Aucun membre avec **{role.name}**.")
    e = discord.Embed(title=f"{role.name} ({len(role.members)})", description="\n".join(f"- {m.mention}" for m in role.members[:20]), color=role.color)
    await ctx.send(embed=e)

@bot.command(name="vocinfo")
async def vocinfo(ctx):
    e = discord.Embed(title="Activité vocale", color=get_color(ctx.guild.id))
    for vc in ctx.guild.voice_channels:
        if vc.members: e.add_field(name=vc.name, value="\n".join(f"- {m.display_name}" for m in vc.members), inline=True)
    if not e.fields: e.description = "Aucun membre en vocal."
    await ctx.send(embed=e)

@bot.command(name="say")
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message: str):
    try: await ctx.message.delete()
    except: pass
    await ctx.send(message)

@bot.command(name="perms")
async def perms(ctx):
    pr = [r for r in ctx.guild.roles if r.permissions.manage_messages or r.permissions.administrator]
    e  = discord.Embed(title="Roles avec permissions", description="\n".join(f"- {r.mention}" for r in pr) or "*Aucun*", color=get_color(ctx.guild.id))
    await ctx.send(embed=e)

@bot.command(name="wiki")
async def wiki(ctx, *, query: str):
    e = discord.Embed(title=f"Wikipedia - {query}", color=get_color(ctx.guild.id))
    e.description = f"[Voir sur Wikipedia](https://fr.wikipedia.org/wiki/{query.replace(' ','_')})"
    await ctx.send(embed=e)

@bot.command(name="search_wiki")
async def search_wiki(ctx, *, query: str):
    e = discord.Embed(title=f"Recherche Wikipedia - {query}", color=get_color(ctx.guild.id))
    e.description = f"[Voir les resultats](https://fr.wikipedia.org/w/index.php?search={query.replace(' ','+')})"
    await ctx.send(embed=e)

@bot.command(name="calc")
async def calc(ctx, *, expression: str):
    try:
        allowed = set("0123456789+-*/()., ")
        if not all(c in allowed for c in expression): return await ctx.send("Expression invalide.")
        result = eval(expression)
        e = discord.Embed(title="Calculatrice", color=get_color(ctx.guild.id))
        e.add_field(name="Expression", value=f"`{expression}`"); e.add_field(name="Resultat", value=f"`{result}`")
        await ctx.send(embed=e)
    except: await ctx.send("Expression invalide.")

@bot.command(name="image")
async def image_search(ctx, *, query: str):
    e = discord.Embed(title=f"Recherche image - {query}", color=get_color(ctx.guild.id))
    e.description = f"[Rechercher sur Google Images](https://www.google.com/search?tbm=isch&q={query.replace(' ','+')})"
    await ctx.send(embed=e)

@bot.command(name="pocoyo")
async def pocoyo_cmd(ctx):
    e = discord.Embed(title="Pocoyos - Support", color=get_color(ctx.guild.id))
    e.description = "Rejoins le serveur de support Pocoyos pour de l'aide !"
    await ctx.send(embed=e)

@bot.command(name="changelogs")
async def changelogs(ctx):
    e = discord.Embed(title="Changelogs Pocoyo", color=get_color(ctx.guild.id))
    e.description = "**v2.0** - Version complete\n- Moderation complete\n- Logs\n- Antiraid\n- Gestion serveur\n- Utilitaire\n- Controle du bot"
    await ctx.send(embed=e)

@bot.command(name="setname")
@commands.is_owner()
async def setname(ctx, *, name: str):
    try: await bot.user.edit(username=name); await ctx.send(f"Nom du bot change en **{name}**.")
    except discord.HTTPException as ex: await ctx.send(f"Erreur : {ex}")

@bot.command(name="setpic")
@commands.is_owner()
async def setpic(ctx, url: str = None):
    link = url or (ctx.message.attachments[0].url if ctx.message.attachments else None)
    if not link: return await ctx.send("Fournis un lien ou joins une image.")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(link) as r: data = await r.read()
        await bot.user.edit(avatar=data); await ctx.send("Photo de profil du bot mise a jour.")
    except Exception as ex: await ctx.send(f"Erreur : {ex}")

@bot.command(name="setbanner")
@commands.is_owner()
async def setbanner(ctx, url: str = None):
    link = url or (ctx.message.attachments[0].url if ctx.message.attachments else None)
    if not link: return await ctx.send("Fournis un lien ou joins une image.")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(link) as r: data = await r.read()
        await bot.user.edit(banner=data); await ctx.send("Banniere du bot mise a jour.")
    except Exception as ex: await ctx.send(f"Erreur : {ex}")

@bot.command(name="setprofil")
async def setprofil(ctx):
    if ctx.author.id not in OWNER_IDS:
        return
    e = discord.Embed(title="⚙️ Profil du bot", color=get_color(ctx.guild.id))
    e.set_thumbnail(url=bot.user.display_avatar.url)
    e.add_field(name="Nom actuel",   value=bot.user.name, inline=True)
    e.add_field(name="ID",           value=str(bot.user.id), inline=True)
    e.set_footer(text="Utilise les boutons pour modifier")
    view = SetProfilView()
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

class SetProfilView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.message = None

    @discord.ui.button(label="✏️ Nom du bot", style=discord.ButtonStyle.primary, row=0)
    async def set_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        await interaction.response.send_modal(SetProfilModal("nom", self))

    @discord.ui.button(label="🖼️ Photo de profil (URL)", style=discord.ButtonStyle.primary, row=0)
    async def set_avatar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        await interaction.response.send_modal(SetProfilModal("avatar", self))

    @discord.ui.button(label="🖼️ Bannière (URL)", style=discord.ButtonStyle.primary, row=0)
    async def set_banner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        await interaction.response.send_modal(SetProfilModal("banniere", self))

    @discord.ui.button(label="🎮 Activité", style=discord.ButtonStyle.secondary, row=1)
    async def set_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        await interaction.response.send_modal(SetProfilModal("activite", self))

    @discord.ui.button(label="🟢 Statut", style=discord.ButtonStyle.secondary, row=1)
    async def set_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Choisir le statut",
            options=[
                discord.SelectOption(label="En ligne",     value="online",    emoji="🟢"),
                discord.SelectOption(label="Inactif",      value="idle",      emoji="🟡"),
                discord.SelectOption(label="Ne pas déranger", value="dnd",    emoji="🔴"),
                discord.SelectOption(label="Invisible",    value="invisible", emoji="⚫"),
            ]
        )
        parent = self
        async def status_cb(inter):
            status_map = {"online": discord.Status.online, "idle": discord.Status.idle, "dnd": discord.Status.dnd, "invisible": discord.Status.invisible}
            await bot.change_presence(status=status_map[inter.data["values"][0]])
            await inter.response.send_message(f"Statut mis à jour : **{inter.data['values'][0]}**", ephemeral=True)
        sel.callback = status_cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    @discord.ui.button(label="📋 Type d'activité", style=discord.ButtonStyle.secondary, row=1)
    async def set_activity_type(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in OWNER_IDS:
            return await interaction.response.send_message("Non autorisé.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Type d'activité",
            options=[
                discord.SelectOption(label="Joue à",     value="playing",   emoji="🎮"),
                discord.SelectOption(label="Regarde",     value="watching",  emoji="📺"),
                discord.SelectOption(label="Écoute",     value="listening", emoji="🎵"),
                discord.SelectOption(label="En compétition", value="competing", emoji="🏆"),
            ]
        )
        async def type_cb(inter):
            cfg = get_guild("botconfig.json", 0)
            cfg["activity_type"] = inter.data["values"][0]
            set_guild("botconfig.json", 0, cfg)
            await inter.response.send_message(f"Type d'activité : **{inter.data['values'][0]}**", ephemeral=True)
        sel.callback = type_cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.edit_message(view=v)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class SetProfilModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Valeur", max_length=200)
    def __init__(self, field_type, parent):
        titles = {"nom": "Nouveau nom du bot", "avatar": "URL de la photo de profil", "banniere": "URL de la bannière", "activite": "Texte de l'activité"}
        super().__init__(title=titles.get(field_type, "Modifier"))
        self.field_type = field_type
        self.parent     = parent
        self.value.placeholder = {"nom": "Ex: Pocoyo", "avatar": "https://...", "banniere": "https://...", "activite": "votre serveur"}.get(field_type, "")
    async def on_submit(self, interaction: discord.Interaction):
        val = str(self.value).strip()
        try:
            if self.field_type == "nom":
                await bot.user.edit(username=val)
                await interaction.response.send_message(f"Nom mis à jour : **{val}**", ephemeral=True)
            elif self.field_type == "avatar":
                async with aiohttp.ClientSession() as s:
                    async with s.get(val) as r: data = await r.read()
                await bot.user.edit(avatar=data)
                await interaction.response.send_message("Photo de profil mise à jour !", ephemeral=True)
            elif self.field_type == "banniere":
                async with aiohttp.ClientSession() as s:
                    async with s.get(val) as r: data = await r.read()
                await bot.user.edit(banner=data)
                await interaction.response.send_message("Bannière mise à jour !", ephemeral=True)
            elif self.field_type == "activite":
                cfg = get_guild("botconfig.json", 0)
                act_type = cfg.get("activity_type", "watching")
                types = {"playing": discord.ActivityType.playing, "watching": discord.ActivityType.watching, "listening": discord.ActivityType.listening, "competing": discord.ActivityType.competing}
                await bot.change_presence(activity=discord.Activity(type=types.get(act_type, discord.ActivityType.watching), name=val))
                await interaction.response.send_message(f"Activité mise à jour : **{val}**", ephemeral=True)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

@bot.command(name="theme")
@commands.has_permissions(administrator=True)
async def theme_cmd(ctx, color: str):
    try:
        color_int = int(color.replace("#",""), 16)
        cfg = get_guild("modconfig.json", ctx.guild.id); cfg["theme_color"] = color_int
        set_guild("modconfig.json", ctx.guild.id, cfg)
        e = discord.Embed(title="Theme mis à jour", color=color_int); e.add_field(name="Couleur", value=color)
        await ctx.send(embed=e)
    except ValueError: await ctx.send("Couleur invalide. Ex: `#ff0000`")

@bot.command(name="prefix")
@commands.has_permissions(administrator=True)
async def prefix_cmd(ctx, new_prefix: str):
    cfg = get_guild("modconfig.json", ctx.guild.id); cfg["prefix"] = new_prefix
    set_guild("modconfig.json", ctx.guild.id, cfg); await ctx.send(f"Préfixe change en **{new_prefix}** sur ce serveur.")

@bot.command(name="removeactivity")
@commands.is_owner()
async def removeactivity(ctx):
    await bot.change_presence(activity=None); await ctx.send("Activité du bot supprimée.")

@bot.command(name="online")
@commands.is_owner()
async def status_online(ctx):
    await bot.change_presence(status=discord.Status.online); await ctx.send("Statut : En ligne.")

@bot.command(name="idle")
@commands.is_owner()
async def status_idle(ctx):
    await bot.change_presence(status=discord.Status.idle); await ctx.send("Statut : Inactif.")

@bot.command(name="dnd")
@commands.is_owner()
async def status_dnd(ctx):
    await bot.change_presence(status=discord.Status.do_not_disturb); await ctx.send("Statut : Ne pas deranger.")

@bot.command(name="invisible")
@commands.is_owner()
async def status_invisible(ctx):
    await bot.change_presence(status=discord.Status.invisible); await ctx.send("Statut : Invisible.")

@bot.command(name="playto")
@commands.is_owner()
async def playto(ctx, *, message: str):
    await bot.change_presence(activity=discord.Game(name=message)); await ctx.send(f"Activité : Joue a **{message}**.")

@bot.command(name="listen")
@commands.is_owner()
async def listen_cmd(ctx, *, message: str):
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=message))
    await ctx.send(f"Activité : Ecoute **{message}**.")

@bot.command(name="watch")
@commands.is_owner()
async def watch_cmd(ctx, *, message: str):
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=message))
    await ctx.send(f"Activité : Regarde **{message}**.")

@bot.command(name="compet")
@commands.is_owner()
async def compet_cmd(ctx, *, message: str):
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.competing, name=message))
    await ctx.send(f"Activité : En competition pour **{message}**.")

@bot.command(name="stream")
@commands.is_owner()
async def stream_cmd(ctx, *, message: str):
    await bot.change_presence(activity=discord.Streaming(name=message, url="https://twitch.tv/pocoyo"))
    await ctx.send(f"Activité : Stream **{message}**.")

@bot.command(name="mp")
@commands.is_owner()
async def mp_cmd(ctx, member: discord.Member, *, message: str):
    try: await member.send(message); await ctx.send(f"Message envoyé a **{member}**.")
    except discord.Forbidden: await ctx.send("Impossible d'envoyer un MP a ce membre.")

@bot.command(name="server_list")
async def server_list(ctx):
    if ctx.author.id not in OWNER_IDS:
        return await ctx.send("❌ Commande reservee au owner du bot.")
    guilds = bot.guilds
    if not guilds:
        return await ctx.send("Le bot n'est dans aucun serveur.")

    # Pagination : 10 serveurs par page
    per_page = 10
    pages    = [guilds[i:i+per_page] for i in range(0, len(guilds), per_page)]
    current  = [0]  # index de page mutable dans les callbacks

    def make_embed(page_idx):
        page  = pages[page_idx]
        e     = discord.Embed(title=f"🌐 Liste des serveurs ({len(guilds)})", color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
        lines = []
        for g in page:
            invite_link = ""
            lines.append(
                f"**{g.name}**\n└ ID: `{g.id}` • Membres: **{g.member_count}** • Owner: `{g.owner}`"
            )
        e.description = "\n\n".join(lines)
        e.set_footer(text=f"Page {page_idx+1}/{len(pages)} • Selectionnez un serveur pour le gérer")
        return e

    class ServerListView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.message = None
            self._build_select()

        def _build_select(self):
            # Nettoyer les anciens items sauf les boutons de nav
            for item in self.children[:]:
                if isinstance(item, discord.ui.Select):
                    self.remove_item(item)

            page   = pages[current[0]]
            select = discord.ui.Select(
                placeholder=f"⚙️ Choisir un serveur a gérer... (page {current[0]+1}/{len(pages)})",
                options=[
                    discord.SelectOption(
                        label=g.name[:25],
                        description=f"{g.member_count} membres • {g.id}",
                        value=str(g.id),
                        emoji="🌐"
                    ) for g in page
                ],
                custom_id="sl_select"
            )
            select.callback = self.server_select_cb
            self.add_item(select)

        @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="sl_prev")
        async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            if current[0] > 0:
                current[0] -= 1
                self._build_select()
                self.prev_btn.disabled = (current[0] == 0)
                self.next_btn.disabled = (current[0] == len(pages)-1)
            await interaction.response.edit_message(embed=make_embed(current[0]), view=self)

        @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="sl_next")
        async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            if current[0] < len(pages)-1:
                current[0] += 1
                self._build_select()
                self.prev_btn.disabled = (current[0] == 0)
                self.next_btn.disabled = (current[0] == len(pages)-1)
            await interaction.response.edit_message(embed=make_embed(current[0]), view=self)

        async def server_select_cb(self, interaction: discord.Interaction):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            gid   = int(interaction.data["values"][0])
            guild = bot.get_guild(gid)
            if not guild:
                return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)

            # Embed du serveur
            e = discord.Embed(title=f"⚙️ Gestion : {guild.name}", color=0x00bfff, timestamp=datetime.utcnow())
            if guild.icon: e.set_thumbnail(url=guild.icon.url)
            e.add_field(name="🆔 ID",          value=str(guild.id), inline=True)
            e.add_field(name="👤 Owner",        value=f"{guild.owner} (`{guild.owner_id}`)", inline=True)
            e.add_field(name="👥 Membres",      value=str(guild.member_count), inline=True)
            e.add_field(name="📌 Salons",       value=str(len(guild.channels)), inline=True)
            e.add_field(name="🏷️ Roles",        value=str(len(guild.roles)), inline=True)
            e.add_field(name="💎 Boosts",       value=str(guild.premium_subscription_count), inline=True)
            e.add_field(name="📅 Créé le",      value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
            e.add_field(name="🌍 Region",       value=str(guild.preferred_locale), inline=True)
            e.add_field(name="🔒 Vérification", value=str(guild.vérification_level), inline=True)
            e.set_footer(text="Choisissez une action ci-dessous")

            action_view = ServerActionView(guild, self)
            await interaction.response.edit_message(embed=e, view=action_view)

        async def on_timeout(self):
            try:
                for item in self.children: item.disabled = True
                if self.message: await self.message.edit(view=self)
            except: pass

    class ServerActionView(discord.ui.View):
        def __init__(self, guild, parent_view):
            super().__init__(timeout=60)
            self.guild       = guild
            self.parent_view = parent_view

        @discord.ui.button(label="Quitter le serveur", emoji="🚪", style=discord.ButtonStyle.danger, custom_id="sa_leave")
        async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            confirm_view = ServerLeaveConfirmView(self.guild, self.parent_view)
            e = discord.Embed(title="⚠️ Confirmer ?", description=f"Le bot va **quitter** le serveur `{self.guild.name}` (`{self.guild.id}`).\nCette action est irreversible.", color=0xff0000)
            await interaction.response.edit_message(embed=e, view=confirm_view)

        @discord.ui.button(label="Envoyer un message", emoji="💬", style=discord.ButtonStyle.primary, custom_id="sa_msg")
        async def msg_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            await interaction.response.send_modal(ServerMsgModal(self.guild))

        @discord.ui.button(label="Créer une invitation", emoji="🔗", style=discord.ButtonStyle.secondary, custom_id="sa_invite")
        async def invite_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            try:
                channel = self.guild.text_channels[0] if self.guild.text_channels else None
                if not channel:
                    return await interaction.response.send_message("Aucun salon texte disponible.", ephemeral=True)
                invite = await channel.create_invite(max_age=3600, max_uses=1, reason="Invite créée par owner bot")
                await interaction.response.send_message(f"🔗 Invitation : {invite.url}", ephemeral=True)
            except Exception as ex:
                await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

        @discord.ui.button(label="Voir les salons", emoji="📌", style=discord.ButtonStyle.secondary, custom_id="sa_channels")
        async def channels_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id not in OWNER_IDS:
                return await interaction.response.send_message("Non autorisé.", ephemeral=True)
            text_chs  = [f"#{c.name}" for c in self.guild.text_channels[:15]]
            voice_chs = [f"🔊 {c.name}" for c in self.guild.voice_channels[:10]]
            e = discord.Embed(title=f"📌 Salons de {self.guild.name}", color=get_color(self.guild.id))
            if text_chs:  e.add_field(name=f"Texte ({len(self.guild.text_channels)})",  value="\n".join(text_chs),  inline=True)
            if voice_chs: e.add_field(name=f"Vocal ({len(self.guild.voice_channels)})", value="\n".join(voice_chs), inline=True)
            await interaction.response.send_message(embed=e, ephemeral=True)

        @discord.ui.button(label="Retour", emoji="◀️", style=discord.ButtonStyle.secondary, custom_id="sa_back")
        async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(embed=make_embed(current[0]), view=self.parent_view)

    class ServerLeaveConfirmView(discord.ui.View):
        def __init__(self, guild, parent_view):
            super().__init__(timeout=30)
            self.guild       = guild
            self.parent_view = parent_view

        @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="✅")
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            name = self.guild.name
            try:
                await self.guild.leave()
                e = discord.Embed(title="✅ Serveur quitté", description=f"Le bot a quitté **{name}**.", color=0x00ff00)
                await interaction.response.edit_message(embed=e, view=None)
            except Exception as ex:
                await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

        @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(embed=make_embed(current[0]), view=self.parent_view)

    class ServerMsgModal(discord.ui.Modal, title="Envoyer un message"):
        message = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Message a envoyer dans le premier salon...", max_length=2000)
        def __init__(self, guild):
            super().__init__()
            self.guild = guild
        async def on_submit(self, interaction: discord.Interaction):
            try:
                channel = self.guild.text_channels[0] if self.guild.text_channels else None
                if not channel:
                    return await interaction.response.send_message("Aucun salon disponible.", ephemeral=True)
                await channel.send(str(self.message))
                await interaction.response.send_message(f"✅ Message envoyé dans **#{channel.name}**.", ephemeral=True)
            except Exception as ex:
                await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

    view = ServerListView()
    view.prev_btn.disabled = True
    view.next_btn.disabled = len(pages) <= 1
    msg = await ctx.send(embed=make_embed(0), view=view)
    view.message = msg

@bot.command(name="owner")
@commands.is_owner()
async def owner_cmd(ctx, member: discord.Member = None):
    cfg = get_guild("botconfig.json", 0); owners = cfg.get("owners",[])
    if not member:
        e = discord.Embed(title="Owners du bot", description="\n".join(f"- <@{oid}>" for oid in owners) or "*Aucun*", color=0xffd700)
        return await ctx.send(embed=e)
    if str(member.id) not in owners: owners.append(str(member.id))
    cfg["owners"] = owners; set_guild("botconfig.json", 0, cfg)
    await ctx.send(f"**{member}** est maintenant owner du bot.")

@bot.command(name="unowner")
@commands.is_owner()
async def unowner_cmd(ctx, member: discord.Member):
    cfg = get_guild("botconfig.json", 0); owners = cfg.get("owners",[])
    if str(member.id) in owners: owners.remove(str(member.id))
    cfg["owners"] = owners; set_guild("botconfig.json", 0, cfg)
    await ctx.send(f"**{member}** n'est plus owner du bot.")

@bot.command(name="clear_owners")
@commands.is_owner()
async def clear_owners_cmd(ctx):
    cfg = get_guild("botconfig.json", 0); cfg["owners"] = []; set_guild("botconfig.json", 0, cfg)
    await ctx.send("Tous les owners supprimés.")

@bot.command(name="bl")
@commands.is_owner()
async def bl_cmd(ctx, member: discord.Member = None, *, reason: str = "Aucune raison"):
    cfg = get_guild("botconfig.json", 0); bl = cfg.get("blacklist",{})
    if not member:
        if not bl: return await ctx.send("Blacklist vidé.")
        e = discord.Embed(title="Blacklist du bot", color=0xff0000)
        e.description = "\n".join(f"- <@{uid}> - {d.get('reason','?')}" for uid, d in list(bl.items())[:20])
        return await ctx.send(embed=e)
    bl[str(member.id)] = {"reason":reason,"date":datetime.utcnow().isoformat()}
    cfg["blacklist"] = bl; set_guild("botconfig.json", 0, cfg)
    await ctx.send(f"**{member}** ajouté a la blacklist. Raison : {reason}")

@bot.command(name="unbl")
@commands.is_owner()
async def unbl_cmd(ctx, member: discord.Member):
    cfg = get_guild("botconfig.json", 0); bl = cfg.get("blacklist",{})
    if str(member.id) in bl: del bl[str(member.id)]
    cfg["blacklist"] = bl; set_guild("botconfig.json", 0, cfg)
    await ctx.send(f"**{member}** retiré de la blacklist.")

@bot.command(name="blinfo")
@commands.is_owner()
async def blinfo_cmd(ctx, member: discord.Member):
    cfg = get_guild("botconfig.json", 0); bl = cfg.get("blacklist",{}); info = bl.get(str(member.id))
    if not info: return await ctx.send(f"**{member}** n'est pas dans la blacklist.")
    e = discord.Embed(title=f"Blacklist - {member}", color=0xff0000)
    e.add_field(name="Raison", value=info.get("reason","?")); e.add_field(name="Date", value=info.get("date","?")[:10])
    await ctx.send(embed=e)

@bot.command(name="clear_bl")
@commands.is_owner()
async def clear_bl(ctx):
    cfg = get_guild("botconfig.json", 0); cfg["blacklist"] = {}; set_guild("botconfig.json", 0, cfg)
    await ctx.send("Blacklist vidée.")

@bot.command(name="reset_server")
@commands.is_owner()
async def reset_server(ctx):
    for filename in ["logs.json","antiraid.json","modconfig.json","tickets.json","rolemenus.json","customs.json","joinsettings.json","leavesettings.json","suggestions.json"]:
        data = db_load(filename)
        if str(ctx.guild.id) in data: del data[str(ctx.guild.id)]; db_save(filename, data)
    await ctx.send("Tous les paramètres du bot réinitialisés sur ce serveur.")

@bot.command(name="resetall")
@commands.is_owner()
async def resetall(ctx):
    files = ["logs.json","antiraid.json","modconfig.json","tickets.json","rolemenus.json","customs.json","joinsettings.json","leavesettings.json","suggestions.json","giveaways.json","backups.json","sanctions.json"]
    for f in files: db_save(f, {})
    await ctx.send("Tous les paramètres du bot réinitialisés.")

@bot.command(name="permchannel")
async def permchannel(ctx, member: discord.Member):
    if ctx.author.id not in OWNER_IDS:
        return await ctx.send("Tu n'as pas la permission d'utiliser cette commande.")
    overwrite = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        send_messages_in_threads=True,
        create_public_threads=True,
        create_private_threads=True,
        embed_links=True,
        attach_files=True,
        add_reactions=True,
        use_external_emojis=True,
        use_external_stickers=True,
        mention_everyone=True,
        manage_messages=True,
        manage_threads=True,
        read_message_history=True,
        use_application_commands=True,
        manage_channels=True,
        manage_webhooks=True,
        manage_roles=True,
        mute_members=True,
        deafen_members=True,
        move_members=True,
        use_voice_activation=True,
        priority_speaker=True,
        stream=True,
        connect=True,
        speak=True,
        request_to_speak=True,
        manage_events=True,
    )
    msg = await ctx.send(f"Application des permissions sur tous les salons pour {member.mention}...")
    count = 0; errors = 0
    for channel in ctx.guild.channels:
        try:
            await channel.set_permissions(member, overwrite=overwrite)
            count += 1
        except:
            errors += 1
    e = discord.Embed(title="Permissions accordees - Tous les salons", color=0x00ff00, timestamp=datetime.utcnow())
    e.add_field(name="Membre",   value=member.mention, inline=True)
    e.add_field(name="Serveur",  value=ctx.guild.name, inline=True)
    e.add_field(name="Salons mis à jour", value=str(count), inline=True)
    if errors: e.add_field(name="Échecs", value=str(errors), inline=True)
    e.description = "Toutes les permissions ont ete cochees sur **tous les salons** du serveur."
    e.set_footer(text=f"Par {ctx.author}")
    await msg.edit(content=None, embed=e)


@bot.command(name="timer")
async def timer(ctx, duration: str, *, message: str = "Temps écoulé !"):
    delta = parse_dur(duration)
    if not delta:
        return await ctx.send("Durée invalide. Ex: `30s`, `5m`, `1h`")
    total_secs = int(delta.total_seconds())
    bar_len    = 10
    end_time   = datetime.utcnow() + delta

    e = discord.Embed(title="⏱️ Timer", color=0x00bfff)
    e.add_field(name="Message",   value=message, inline=False)
    e.add_field(name="Durée",     value=duration, inline=True)
    e.add_field(name="Fin",       value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
    e.description = f"`{'█'*0}{'░'*bar_len}` 0%"
    msg = await ctx.send(embed=e)

    steps     = min(bar_len, total_secs)
    step_time = total_secs / steps if steps > 0 else total_secs
    for i in range(1, steps + 1):
        await asyncio.sleep(step_time)
        filled = int((i / steps) * bar_len)
        pct    = int((i / steps) * 100)
        e.description = f"`{'█'*filled}{'░'*(bar_len-filled)}` {pct}%"
        try: await msg.edit(embed=e)
        except: break

    e.title       = "✅ Timer terminé !"
    e.color       = 0x00ff00
    e.description = f"`{'█'*bar_len}` 100%"
    try: await msg.edit(embed=e)
    except: pass
    await ctx.send(f"{ctx.author.mention} ⏰ {message}")

@bot.command(name="avatar")
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    e      = discord.Embed(color=get_color(ctx.guild.id))
    e.set_author(name=str(member), icon_url=member.display_avatar.url)
    e.set_image(url=member.display_avatar.url)
    e.set_footer(text=f"ID : {member.id}")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Ouvrir dans le navigateur", url=str(member.display_avatar.url), style=discord.ButtonStyle.link))
    await ctx.send(embed=e, view=view)

@bot.command(name="id")
async def id_cmd(ctx, *, target: str = None):
    if not target:
        await ctx.send(f"🆔 Ton ID : `{ctx.author.id}`")
        return
    # Essaye membre
    try:
        member = await commands.MemberConverter().convert(ctx, target)
        await ctx.send(f"🆔 ID de **{member}** : `{member.id}`")
        return
    except: pass
    # Essaye role
    try:
        role = await commands.RoleConverter().convert(ctx, target)
        await ctx.send(f"🆔 ID du role **{role.name}** : `{role.id}`")
        return
    except: pass
    # Essaye salon
    try:
        channel = await commands.TextChannelConverter().convert(ctx, target)
        await ctx.send(f"🆔 ID du salon **{channel.name}** : `{channel.id}`")
        return
    except: pass
    await ctx.send(f"Impossible de trouver `{target}`.")

@bot.command(name="inviteinfo")
async def inviteinfo(ctx, invite_link: str):
    try:
        invite = await bot.fetch_invite(invite_link)
        e      = discord.Embed(title="🔗 Informations sur l'invitation", color=get_color(ctx.guild.id), timestamp=datetime.utcnow())
        e.add_field(name="Serveur",       value=invite.guild.name if invite.guild else "Inconnu", inline=True)
        e.add_field(name="ID Serveur",    value=str(invite.guild.id) if invite.guild else "?", inline=True)
        e.add_field(name="Salon",         value=f"#{invite.channel.name}" if invite.channel else "?", inline=True)
        e.add_field(name="Inviteur",      value=str(invite.inviter) if invite.inviter else "Inconnu", inline=True)
        e.add_field(name="Membres",       value=str(invite.approximate_member_count or "?"), inline=True)
        e.add_field(name="En ligne",      value=str(invite.approximate_presence_count or "?"), inline=True)
        e.add_field(name="Utilisations",  value=str(invite.uses) if invite.uses is not None else "?", inline=True)
        e.add_field(name="Max utilisons", value=str(invite.max_uses) if invite.max_uses else "Illimite", inline=True)
        e.add_field(name="Expire",        value=f"<t:{int(invite.expires_at.timestamp())}:R>" if invite.expires_at else "Jamais", inline=True)
        if invite.guild and invite.guild.icon:
            e.set_thumbnail(url=invite.guild.icon.url)
        await ctx.send(embed=e)
    except discord.NotFound:
        await ctx.send("Invitation introuvable ou expiree.")
    except Exception as ex:
        await ctx.send(f"Erreur : {ex}")

@bot.command(name="nuke")
@commands.has_permissions(manage_channels=True)
async def nuke(ctx):
    channel  = ctx.channel
    name     = channel.name
    cat      = channel.category
    pos      = channel.position
    ow       = channel.overwrites
    topic    = channel.topic
    slowmode = channel.slowmode_delay
    nsfw     = channel.is_nsfw()

    confirm_view = NukeConfirmView(channel, name, cat, pos, ow, topic, slowmode, nsfw, ctx.author)
    e = discord.Embed(
        title="💣 Nuke - Confirmer ?",
        description=f"Le salon **#{name}** va etre supprimé et recree a l'identique.\nTous les messages seront **définitivement supprimes**.",
        color=0xff0000
    )
    await ctx.send(embed=e, view=confirm_view)

class NukeConfirmView(discord.ui.View):
    def __init__(self, channel, name, cat, pos, ow, topic, slowmode, nsfw, author):
        super().__init__(timeout=30)
        self.channel  = channel
        self.name     = name
        self.cat      = cat
        self.pos      = pos
        self.ow       = ow
        self.topic    = topic
        self.slowmode = slowmode
        self.nsfw     = nsfw
        self.author   = author

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        await self.channel.delete()
        new_ch = await interaction.guild.create_text_channel(
            self.name, category=self.cat, overwrites=self.ow,
            topic=self.topic, slowmode_delay=self.slowmode, nsfw=self.nsfw
        )
        await new_ch.edit(position=self.pos)
        e = discord.Embed(title="💣 Salon nuke !", description=f"**#{self.name}** a ete renouvele.", color=0xff4500, timestamp=datetime.utcnow())
        e.set_footer(text=f"Par {self.author}")
        await new_ch.send(embed=e)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        await interaction.response.edit_message(content="Nuke annule.", embed=None, view=None)

@bot.command(name="unhoist")
@commands.has_permissions(manage_nicknames=True)
async def unhoist(ctx):
    hoisted  = []
    special  = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    count    = 0
    for member in ctx.guild.members:
        name = member.display_name
        if name and name[0] in special:
            try:
                new_name = name.lstrip(special).strip() or "Membre"
                await member.edit(nick=new_name)
                hoisted.append(f"{member} → {new_name}")
                count += 1
            except: pass
    e = discord.Embed(title="✅ Unhoist terminé", color=0x00ff00, timestamp=datetime.utcnow())
    e.add_field(name="Membres modifiés", value=str(count), inline=True)
    if hoisted[:10]:
        e.add_field(name="Exemples", value="\n".join(hoisted[:10]), inline=False)
    await ctx.send(embed=e)

@bot.command(name="find")
@commands.has_permissions(manage_messages=True)
async def find(ctx, *, query: str):
    query   = query.lower()
    results = [m for m in ctx.guild.members if query in m.name.lower() or query in (m.nick or "").lower() or query in str(m.id)]
    if not results:
        return await ctx.send(f"Aucun membre trouvé pour `{query}`.")
    e = discord.Embed(title=f"🔍 Resultats pour \"{query}\" ({len(results)})", color=get_color(ctx.guild.id))
    e.description = "\n".join(f"- {m.mention} `{m}` `({m.id})`" for m in results[:20])
    if len(results) > 20:
        e.set_footer(text=f"Affichage des 20 premiers sur {len(results)}")
    await ctx.send(embed=e)

@bot.command(name="massban")
@commands.has_permissions(ban_members=True)
async def massban(ctx, *user_ids: int):
    if not user_ids:
        return await ctx.send("Usage : `+massban <ID1> <ID2> <ID3>...`")
    msg   = await ctx.send(f"Bannissement de **{len(user_ids)}** membre(s) en cours...")
    done  = 0
    fails = 0
    for uid in user_ids:
        try:
            await ctx.guild.ban(discord.Object(id=uid), reason=f"Massban par {ctx.author}")
            await add_sanction(ctx.guild.id, uid, "ban", f"Massban par {ctx.author}", ctx.author.id)
            done += 1
        except:
            fails += 1
    e = discord.Embed(title="🔨 Massban terminé", color=0xff0000, timestamp=datetime.utcnow())
    e.add_field(name="✅ Bannis",   value=str(done),  inline=True)
    e.add_field(name="❌ Échecs",   value=str(fails), inline=True)
    e.add_field(name="Par",         value=ctx.author.mention, inline=True)
    await msg.edit(content=None, embed=e)

@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def purge(ctx, target: str = "bots", amount: int = 100):
    if target.lower() == "bots":
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author.bot)
        msg = await ctx.send(f"✅ **{len(deleted)}** message(s) de bots supprimés.")
    elif target.lower() == "humans":
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: not m.author.bot)
        msg = await ctx.send(f"✅ **{len(deleted)}** message(s) d'humains supprimés.")
    elif target.lower() == "links":
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: "http://" in m.content or "https://" in m.content)
        msg = await ctx.send(f"✅ **{len(deleted)}** message(s) avec liens supprimés.")
    elif target.lower() == "images":
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: len(m.attachments) > 0)
        msg = await ctx.send(f"✅ **{len(deleted)}** message(s) avec images supprimés.")
    else:
        # Essaye de voir si c'est un nombre
        try:
            n       = int(target)
            deleted = await ctx.channel.purge(limit=n)
            msg     = await ctx.send(f"✅ **{len(deleted)}** message(s) supprimés.")
        except:
            return await ctx.send("Usage : `+purge bots/humans/links/images [nombre]` ou `+purge <nombre>`")
    await asyncio.sleep(3)
    try: await msg.delete()
    except: pass


@bot.command(name="autoupdate")
@commands.has_permissions(administrator=True)
async def autoupdate(ctx, action: str):
    cfg = get_guild("modconfig.json", ctx.guild.id)
    cfg["autoupdate"] = (action.lower() == "on")
    set_guild("modconfig.json", ctx.guild.id, cfg)
    await ctx.send(f"Autoupdate {'activé' if action.lower() == 'on' else 'désactivé'}.")

# Override du lock existant pour supporter une raison affichée

@bot.command(name="tempvoc")
@commands.has_permissions(manage_channels=True)
async def tempvoc(ctx):
    cfg = get_guild("modconfig.json", ctx.guild.id)
    e   = discord.Embed(title="🎙️ Vocaux temporaires", color=get_color(ctx.guild.id))
    cat_id = cfg.get("tempvoc_category")
    cat    = ctx.guild.get_channel(int(cat_id)) if cat_id else None
    hub_id = cfg.get("tempvoc_hub")
    hub    = ctx.guild.get_channel(int(hub_id)) if hub_id else None
    e.add_field(name="Catégorie",   value=cat.name if cat else "Non configuré", inline=True)
    e.add_field(name="Salon hub",   value=hub.mention if hub else "Non configuré", inline=True)
    e.add_field(name="Limit",       value=str(cfg.get("tempvoc_limit", 0)) + " membres", inline=True)
    e.set_footer(text="Quand un membre rejoint le hub, un vocal temp lui est créé.")
    view = TempvocView(ctx.guild.id)
    await ctx.send(embed=e, view=view)

class TempvocView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=120)
        self.guild_id = guild_id

    @discord.ui.button(label="Définir la catégorie", emoji="📁", style=discord.ButtonStyle.secondary)
    async def set_cat(self, interaction: discord.Interaction, button: discord.ui.Button):
        cats = interaction.guild.categories[:25]
        if not cats:
            return await interaction.response.send_message("Aucune catégorie.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Catégorie pour les vocaux temp",
            options=[discord.SelectOption(label=c.name[:25], value=str(c.id)) for c in cats]
        )
        async def cb(inter):
            cfg = get_guild("modconfig.json", self.guild_id)
            cfg["tempvoc_category"] = inter.data["values"][0]
            set_guild("modconfig.json", self.guild_id, cfg)
            await inter.response.send_message("✅ Catégorie définie.", ephemeral=True)
        sel.callback = cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="Définir le salon hub", emoji="🔊", style=discord.ButtonStyle.secondary)
    async def set_hub(self, interaction: discord.Interaction, button: discord.ui.Button):
        vcs = interaction.guild.voice_channels[:25]
        if not vcs:
            return await interaction.response.send_message("Aucun salon vocal.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Salon hub (rejoindre = créer un vocal)",
            options=[discord.SelectOption(label=v.name[:25], value=str(v.id)) for v in vcs]
        )
        async def cb(inter):
            cfg = get_guild("modconfig.json", self.guild_id)
            cfg["tempvoc_hub"] = inter.data["values"][0]
            set_guild("modconfig.json", self.guild_id, cfg)
            await inter.response.send_message("✅ Salon hub défini.", ephemeral=True)
        sel.callback = cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.send_message(view=v, ephemeral=True)

async def on_voice_state_update_tempvoc(member, before, after):
    cfg    = get_guild("modconfig.json", member.guild.id)
    hub_id = cfg.get("tempvoc_hub")
    if not hub_id: return
    # Membre rejoint le hub → créer un vocal temp
    if after.channel and str(after.channel.id) == hub_id:
        cat_id   = cfg.get("tempvoc_category")
        category = member.guild.get_channel(int(cat_id)) if cat_id else None
        limit    = cfg.get("tempvoc_limit", 0)
        # Permissions : le createur peut tout gerer sur son salon
        overwrites = {
            member.guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                manage_channels=True,    # renommer, changer la limite
                move_members=True,       # deplacer/expulser des membres
                mute_members=True,       # muter quelqu'un dans son vocal
                deafen_members=True,     # deafen quelqu'un dans son vocal
                manage_permissions=True, # gerer les permissions du salon
                priority_speaker=True,
                stream=True,
            ),
            member.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                manage_channels=True,
                move_members=True,
                manage_permissions=True,
            ),
        }
        vc = await member.guild.create_voice_channel(
            f"🎙️ {member.display_name[:20]}",
            category=category,
            user_limit=limit,
            overwrites=overwrites
        )
        # Sauvegarder le vocal temporaire
        tvocs = cfg.get("tempvocs", {}); tvocs[str(vc.id)] = str(member.id)
        cfg["tempvocs"] = tvocs; set_guild("modconfig.json", member.guild.id, cfg)
        try: await member.move_to(vc)
        except: pass
    # Vocal temp vidé → supprimer
    if before.channel and before.channel != after.channel:
        cfg2  = get_guild("modconfig.json", member.guild.id)
        tvocs = cfg2.get("tempvocs", {})
        if str(before.channel.id) in tvocs and len(before.channel.members) == 0:
            try: await before.channel.delete()
            except: pass
            tvocs.pop(str(before.channel.id), None)
            cfg2["tempvocs"] = tvocs; set_guild("modconfig.json", member.guild.id, cfg2)

@bot.command(name="translate")
async def translate(ctx, lang: str = "fr", *, text: str = None):
    if not text:
        return await ctx.send("Usage : `+translate <langue> <texte>` (ex: `+translate en Bonjour`)")
    # Utilise l'API gratuite de MyMemory
    try:
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair=auto|{lang}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                data = await r.json()
        result = data.get("responseData", {}).get("translatedText", "Traduction impossible.")
        e = discord.Embed(title="🌍 Traduction", color=get_color(ctx.guild.id))
        e.add_field(name="Original",   value=text[:1024], inline=False)
        e.add_field(name=f"→ {lang.upper()}", value=result[:1024], inline=False)
        await ctx.send(embed=e)
    except Exception as ex:
        await ctx.send(f"Erreur de traduction : {ex}")

@bot.command(name="reactionrole")
@commands.has_permissions(manage_roles=True)
async def reactionrole(ctx):
    """Panneau interactif pour créer un réaction role sur n'importe quel message."""
    e = discord.Embed(
        title="🎭 Réaction Role",
        description=(
            "**Comment ca marche :**\n"
            "1. Donne l'**ID du message** sur lequel ajouter la reaction\n"
            "2. Choisis le **role** a attribuer\n"
            "3. Donne l'**emoji** a utiliser\n\n"
            "Le bot ajouté la réaction et attribue le role automatiquement."
        ),
        color=get_color(ctx.guild.id)
    )
    view = ReactionRoleSetupView(ctx)
    msg  = await ctx.send(embed=e, view=view)
    view.msg = msg

class ReactionRoleSetupView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=120)
        self.ctx      = ctx
        self.msg      = None
        self.msg_id   = None
        self.role     = None
        self.emoji    = None

    @discord.ui.button(label="1. ID du message", emoji="🆔", style=discord.ButtonStyle.primary, custom_id="rr_msgid")
    async def set_msg_id(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        await interaction.response.send_modal(ReactionRoleMsgModal(self))

    @discord.ui.button(label="2. Choisir le role", emoji="🏷️", style=discord.ButtonStyle.primary, custom_id="rr_role")
    async def set_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed and r.position < interaction.guild.me.top_role.position][:25]
        if not roles:
            return await interaction.response.send_message("Aucun role disponible.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Choisir le role a attribuer...",
            options=[discord.SelectOption(label=r.name[:25], value=str(r.id), emoji="🏷️") for r in roles]
        )
        async def role_cb(inter):
            self.role = interaction.guild.get_role(int(inter.data["values"][0]))
            await self._refresh(inter)
        sel.callback = role_cb
        v = discord.ui.View(timeout=60); v.add_item(sel)
        await interaction.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="3. Emoji", emoji="😀", style=discord.ButtonStyle.primary, custom_id="rr_emoji")
    async def set_emoji(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        await interaction.response.send_modal(ReactionRoleEmojiModal(self))

    @discord.ui.button(label="✅ Confirmer", emoji="✅", style=discord.ButtonStyle.success, custom_id="rr_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        if not self.msg_id or not self.role or not self.emoji:
            return await interaction.response.send_message("Complete les 3 etapes d'abord !", ephemeral=True)
        # Cherche le message dans tous les salons
        target_msg = None
        for ch in interaction.guild.text_channels:
            try:
                target_msg = await ch.fetch_message(self.msg_id)
                break
            except: pass
        if not target_msg:
            return await interaction.response.send_message("Message introuvable. Verifie l'ID.", ephemeral=True)
        # Ajouté la réaction
        try:
            await target_msg.add_reaction(self.emoji)
        except Exception as ex:
            return await interaction.response.send_message(f"Emoji invalide : {ex}", ephemeral=True)
        # Sauvegardé
        data = get_guild("rolemenus.json", interaction.guild.id)
        data.setdefault(str(self.msg_id), {})[str(self.role.id)] = self.emoji
        set_guild("rolemenus.json", interaction.guild.id, data)

        e = discord.Embed(title="✅ Réaction Role créé !", color=0x00ff00, timestamp=datetime.utcnow())
        e.add_field(name="Message", value=f"[Aller au message]({target_msg.jump_url})", inline=True)
        e.add_field(name="Role",    value=self.role.mention, inline=True)
        e.add_field(name="Emoji",   value=self.emoji, inline=True)
        await interaction.response.edit_message(embed=e, view=None)
        self.stop()

    @discord.ui.button(label="❌ Annuler", style=discord.ButtonStyle.secondary, custom_id="rr_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("Ce n'est pas ta commande.", ephemeral=True)
        await interaction.response.edit_message(content="Annule.", embed=None, view=None)
        self.stop()

    async def _refresh(self, interaction):
        e = discord.Embed(title="🎭 Réaction Role", color=get_color(self.ctx.guild.id))
        e.add_field(name="🆔 Message ID", value=f"`{self.msg_id}`" if self.msg_id else "❌ Non défini", inline=True)
        e.add_field(name="🏷️ Role",       value=self.role.mention if self.role else "❌ Non défini", inline=True)
        e.add_field(name="😀 Emoji",      value=self.emoji if self.emoji else "❌ Non défini", inline=True)
        if self.msg_id and self.role and self.emoji:
            e.set_footer(text="Tout est pret ! Clique sur Confirmer.")
        await interaction.response.edit_message(embed=e, view=self)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.msg: await self.msg.edit(view=self)
        except: pass

class ReactionRoleMsgModal(discord.ui.Modal, title="ID du message"):
    msg_id = discord.ui.TextInput(label="ID du message", placeholder="Ex: 1234567890123456789", max_length=20)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.parent.msg_id = int(str(self.msg_id))
            await self.parent._refresh(interaction)
        except:
            await interaction.response.send_message("ID invalide.", ephemeral=True)

class ReactionRoleEmojiModal(discord.ui.Modal, title="Emoji"):
    emoji = discord.ui.TextInput(label="Emoji", placeholder="Ex: ✅ ou :nom_emoji:", max_length=50)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        self.parent.emoji = str(self.emoji).strip()
        await self.parent._refresh(interaction)

@bot.command(name="color")
async def color_cmd(ctx, hex_color: str):
    hex_clean = hex_color.replace("#", "").replace("0x", "").strip()
    if len(hex_clean) not in (3, 6) or not all(c in "0123456789abcdefABCDEF" for c in hex_clean):
        return await ctx.send("Couleur invalide. Ex: `+color ff0000` ou `+color #3498db`")
    if len(hex_clean) == 3:
        hex_clean = "".join(c*2 for c in hex_clean)
    color_int = int(hex_clean, 16)
    r = (color_int >> 16) & 255
    g = (color_int >> 8)  & 255
    b =  color_int        & 255
    # Calcule la luminosite pour choisir texte blanc ou noir
    luminance  = 0.299*r + 0.587*g + 0.114*b
    text_color = "Clair" if luminance > 128 else "Sombre"
    e = discord.Embed(title=f"🎨 #{hex_clean.upper()}", color=color_int)
    e.add_field(name="Hex",        value=f"`#{hex_clean.upper()}`", inline=True)
    e.add_field(name="RGB",        value=f"`rgb({r}, {g}, {b})`",  inline=True)
    e.add_field(name="Decimal",    value=f"`{color_int}`",          inline=True)
    e.add_field(name="Luminosite", value=text_color,                inline=True)
    e.add_field(name="Nuance",     value=_color_name(r, g, b),      inline=True)
    # Image de preview via placeholder
    e.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_clean}/100x100")
    await ctx.send(embed=e)

def _color_name(r, g, b):
    """Retourne une nuance approximative basee sur les composantes RGB."""
    if r > 200 and g > 200 and b > 200: return "Blanc / Tres clair"
    if r < 50  and g < 50  and b < 50:  return "Noir / Tres sombre"
    if r > 180 and g < 80  and b < 80:  return "Rouge"
    if r < 80  and g > 180 and b < 80:  return "Vert"
    if r < 80  and g < 80  and b > 180: return "Bleu"
    if r > 180 and g > 180 and b < 80:  return "Jaune"
    if r > 180 and g < 80  and b > 180: return "Violet / Magenta"
    if r < 80  and g > 180 and b > 180: return "Cyan"
    if r > 180 and g > 100 and b < 80:  return "Orange"
    if r > 120 and g > 120 and b > 120: return "Gris clair"
    return "Mixte"

# Caches sticky
sticky_tasks   = {}  # key -> last sticky msg id
sticky_counters = {} # key -> nb messages depuis dernier repost

def get_sticky_cfg(guild_id, channel_id):
    cfg    = get_guild("modconfig.json", guild_id)
    stickies = cfg.get("sticky_messages", {})
    return stickies.get(str(channel_id))

def save_sticky(guild_id, channel_id, data):
    cfg = get_guild("modconfig.json", guild_id)
    stickies = cfg.get("sticky_messages", {})
    if data is None:
        stickies.pop(str(channel_id), None)
    else:
        stickies[str(channel_id)] = data
    cfg["sticky_messages"] = stickies
    set_guild("modconfig.json", guild_id, cfg)

async def post_sticky(channel, guild_id):
    data = get_sticky_cfg(guild_id, channel.id)
    if not data: return
    key = f"{guild_id}:{channel.id}"
    # Supprimer l'ancien sticky
    old_id = sticky_tasks.get(key)
    if old_id:
        try:
            old_msg = await channel.fetch_message(old_id)
            await old_msg.delete()
        except: pass
    # Reposte
    await asyncio.sleep(0.3)
    txt    = data.get("message", "")
    color  = data.get("color", 0x1a0a2e)
    title  = data.get("title", "") or None
    footer = data.get("footer", "📌 Message épinglé") or "📌 Message épinglé"
    e      = discord.Embed(title=title, description=txt, color=color)
    e.set_footer(text=footer)
    sent = await channel.send(embed=e)
    sticky_tasks[key] = sent.id
    sticky_counters[key] = 0
    # Reinitialiser le timer si mode temps
    if data.get("mode") == "time" and data.get("interval"):
        task_key = f"sticky_timer_{key}"
        existing = sticky_tasks.get(task_key)
        if existing:
            existing.cancel()
        async def timer_loop():
            while True:
                await asyncio.sleep(data["interval"])
                cfg_check = get_sticky_cfg(guild_id, channel.id)
                if not cfg_check: break
                await post_sticky(channel, guild_id)
        t = asyncio.create_task(timer_loop())
        sticky_tasks[task_key] = t

@bot.event
async def on_message_sticky(message):
    if message.author.bot or not message.guild: return
    data = get_sticky_cfg(message.guild.id, message.channel.id)
    if not data: return
    key  = f"{message.guild.id}:{message.channel.id}"
    mode = data.get("mode", "message")

    if mode == "message":
        every = data.get("every", 1)
        sticky_counters[key] = sticky_counters.get(key, 0) + 1
        if sticky_counters[key] >= every:
            await post_sticky(message.channel, message.guild.id)

@bot.command(name="stickymsg")
@commands.has_permissions(manage_messages=True)
async def stickymsg(ctx):
    """Ouvre le panneau de configuration du message épinglé."""
    data = get_sticky_cfg(ctx.guild.id, ctx.channel.id)
    if not data:
        # Cree un sticky vide par defaut
        data = {
            "message":  "",
            "title":    "",
            "footer":   "📌 Message épinglé",
            "color":    get_color(ctx.guild.id),
            "mode":     "message",
            "every":    1,
            "interval": None,
        }
        save_sticky(ctx.guild.id, ctx.channel.id, data)
    e    = _sticky_embed(ctx.guild, ctx.channel, data)
    view = StickySettingsView(ctx.guild.id, ctx.channel)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg



def _sticky_embed(guild, channel, data):
    mode    = data.get("mode", "message")
    every   = data.get("every", 1)
    inter   = data.get("interval")
    color   = data.get("color", get_color(guild.id))
    title   = data.get("title") or "📌 Message épinglé"
    footer  = data.get("footer") or "📌 Message épinglé"
    message = data.get("message") or "*Aucun message défini*"

    e = discord.Embed(title=f"⚙️ Config Sticky — #{channel.name}", color=get_color(guild.id))
    e.add_field(name="📝 Titre",      value=title[:50] or "*Non défini*",       inline=True)
    e.add_field(name="🎨 Couleur",    value=hex(color),                          inline=True)
    e.add_field(name="📋 Footer",     value=footer[:50] or "*Non défini*",       inline=True)
    e.add_field(name="💬 Message",    value=message[:100] or "*Non défini*",     inline=False)
    if mode == "message":
        e.add_field(name="⚙️ Mode",      value=f"Après {every} message(s)", inline=True)
    else:
        seconds = inter or 0
        if seconds >= 86400:
            label = f"{seconds//86400}j"
        elif seconds >= 3600:
            label = f"{seconds//3600}h"
        else:
            label = f"{seconds//60}min"
        e.add_field(name="⚙️ Mode", value=f"Toutes les {label}", inline=True)
    active = bool(data.get("message"))
    e.add_field(name="📌 Statut", value="✅ Actif" if active else "❌ Pas encore envoyé", inline=True)
    e.set_footer(text="Configure puis clique sur Envoyer")
    return e

class StickySettingsView(discord.ui.View):
    def __init__(self, guild_id, channel):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.channel  = channel
        self.message  = None

    async def refresh(self, interaction):
        data = get_sticky_cfg(self.guild_id, self.channel.id)
        if not data:
            return await interaction.response.edit_message(content="Sticky supprimé.", embed=None, view=None)
        e = _sticky_embed(interaction.guild, self.channel, data)
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="✏️ Message", style=discord.ButtonStyle.primary, custom_id="sticky_edit_msg", row=0)
    async def edit_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyEditMsgModal(self.guild_id, self.channel, self))

    @discord.ui.button(label="📝 Titre", style=discord.ButtonStyle.primary, custom_id="sticky_title", row=0)
    async def edit_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyTitleModal(self.guild_id, self.channel, self))

    @discord.ui.button(label="📋 Footer", style=discord.ButtonStyle.primary, custom_id="sticky_footer", row=0)
    async def edit_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyFooterModal(self.guild_id, self.channel, self))

    @discord.ui.button(label="🎨 Couleur", style=discord.ButtonStyle.secondary, custom_id="sticky_color", row=0)
    async def edit_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyColorModal(self.guild_id, self.channel, self))

    @discord.ui.button(label="🔢 X messages", style=discord.ButtonStyle.secondary, custom_id="sticky_msg_mode", row=1)
    async def set_msg_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyMessageModeModal(self.guild_id, self.channel, self))

    @discord.ui.button(label="⏱️ Intervalle", style=discord.ButtonStyle.secondary, custom_id="sticky_time_mode", row=1)
    async def set_time_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StickyTimeModeModal(self.guild_id, self.channel, self))

    @discord.ui.button(label="📤 Envoyer", style=discord.ButtonStyle.success, custom_id="sticky_send", row=1)
    async def send_sticky(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = get_sticky_cfg(self.guild_id, self.channel.id)
        if not data or not data.get("message"):
            return await interaction.response.send_message("Définis un message d'abord.", ephemeral=True)
        await post_sticky(self.channel, self.guild_id)
        await interaction.response.send_message("Message épinglé envoyé !", ephemeral=True)

    @discord.ui.button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, custom_id="sticky_delete", row=1)
    async def delete_sticky(self, interaction: discord.Interaction, button: discord.ui.Button):
        save_sticky(self.guild_id, self.channel.id, None)
        key = f"{self.guild_id}:{self.channel.id}"
        sticky_tasks.pop(key, None)
        t = sticky_tasks.pop(f"sticky_timer_{key}", None)
        if t: t.cancel()
        await interaction.response.edit_message(content=f"Message épinglé supprimé de {self.channel.mention}.", embed=None, view=None)
        self.stop()

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class StickyEditMsgModal(discord.ui.Modal, title="Message épinglé"):
    new_msg = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, placeholder="Contenu du message épinglé...", max_length=2000)
    def __init__(self, guild_id, channel, parent):
        super().__init__(); self.guild_id = guild_id; self.channel = channel; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        data = get_sticky_cfg(self.guild_id, self.channel.id)
        if not data: return
        data["message"] = str(self.new_msg)
        save_sticky(self.guild_id, self.channel.id, data)
        await self.parent.refresh(interaction)

class StickyTitleModal(discord.ui.Modal, title="Titre du message épinglé"):
    new_title = discord.ui.TextInput(label="Titre", placeholder="Ex: Règles du serveur", max_length=256, required=False)
    def __init__(self, guild_id, channel, parent):
        super().__init__(); self.guild_id = guild_id; self.channel = channel; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        data = get_sticky_cfg(self.guild_id, self.channel.id)
        if not data: return
        data["title"] = str(self.new_title).strip()
        save_sticky(self.guild_id, self.channel.id, data)
        await self.parent.refresh(interaction)

class StickyFooterModal(discord.ui.Modal, title="Footer du message épinglé"):
    new_footer = discord.ui.TextInput(label="Footer", placeholder="Ex: 📌 Message épinglé", max_length=200, required=False)
    def __init__(self, guild_id, channel, parent):
        super().__init__(); self.guild_id = guild_id; self.channel = channel; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        data = get_sticky_cfg(self.guild_id, self.channel.id)
        if not data: return
        data["footer"] = str(self.new_footer).strip()
        save_sticky(self.guild_id, self.channel.id, data)
        await self.parent.refresh(interaction)

class StickyColorModal(discord.ui.Modal, title="Couleur du message épinglé"):
    hex_color = discord.ui.TextInput(label="Couleur (hex)", placeholder="Ex: ff0000 ou #3498db", max_length=7)
    def __init__(self, guild_id, channel, parent):
        super().__init__(); self.guild_id = guild_id; self.channel = channel; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            raw = str(self.hex_color).replace("#","").replace("0x","").strip()
            color = int(raw, 16)
            data  = get_sticky_cfg(self.guild_id, self.channel.id)
            if not data: return
            data["color"] = color
            save_sticky(self.guild_id, self.channel.id, data)
            await self.parent.refresh(interaction)
        except:
            await interaction.response.send_message("Couleur invalide. Ex: `ff0000`", ephemeral=True)

class StickyMessageModeModal(discord.ui.Modal, title="Après X messages"):
    every = discord.ui.TextInput(label="Reposte tous les X messages", placeholder="Ex: 5", max_length=4)
    def __init__(self, guild_id, channel, parent):
        super().__init__(); self.guild_id = guild_id; self.channel = channel; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            n    = max(1, int(str(self.every)))
            data = get_sticky_cfg(self.guild_id, self.channel.id)
            if not data: return
            data["mode"] = "message"; data["every"] = n
            save_sticky(self.guild_id, self.channel.id, data)
            t = sticky_tasks.pop(f"sticky_timer_{self.guild_id}:{self.channel.id}", None)
            if t: t.cancel()
            await self.parent.refresh(interaction)
        except:
            await interaction.response.send_message("Valeur invalide.", ephemeral=True)

class StickyTimeModeModal(discord.ui.Modal, title="Intervalle de temps"):
    jours   = discord.ui.TextInput(label="Jours",   placeholder="0", max_length=3, required=False, default="0")
    heures  = discord.ui.TextInput(label="Heures",  placeholder="0", max_length=3, required=False, default="0")
    minutes = discord.ui.TextInput(label="Minutes", placeholder="10", max_length=3, required=False, default="10")
    def __init__(self, guild_id, channel, parent):
        super().__init__(); self.guild_id = guild_id; self.channel = channel; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            j = int(str(self.jours) or "0"); h = int(str(self.heures) or "0"); m = int(str(self.minutes) or "10")
            seconds = j*86400 + h*3600 + m*60
            if seconds < 60:
                return await interaction.response.send_message("Minimum 1 minute.", ephemeral=True)
            data = get_sticky_cfg(self.guild_id, self.channel.id)
            if not data: return
            data["mode"] = "time"; data["interval"] = seconds
            save_sticky(self.guild_id, self.channel.id, data)
            key = f"{self.guild_id}:{self.channel.id}"
            t   = sticky_tasks.pop(f"sticky_timer_{key}", None)
            if t: t.cancel()
            channel = self.channel; guild_id = self.guild_id
            async def timer_loop():
                while True:
                    await asyncio.sleep(seconds)
                    cfg_check = get_sticky_cfg(guild_id, channel.id)
                    if not cfg_check or cfg_check.get("mode") != "time": break
                    await post_sticky(channel, guild_id)
            sticky_tasks[f"sticky_timer_{key}"] = asyncio.create_task(timer_loop())
            await self.parent.refresh(interaction)
        except:
            await interaction.response.send_message("Valeur invalide.", ephemeral=True)


class AutomodTimeoutDurationModal(discord.ui.Modal, title="Durée du timeout"):
    jours   = discord.ui.TextInput(label="Jours",   placeholder="0", max_length=2, required=False, default="0")
    heures  = discord.ui.TextInput(label="Heures",  placeholder="0", max_length=2, required=False, default="0")
    minutes = discord.ui.TextInput(label="Minutes", placeholder="10", max_length=3, required=False, default="10")

    def __init__(self, guild_id, punish_key, parent):
        super().__init__()
        self.guild_id   = guild_id
        self.punish_key = punish_key
        self.parent     = parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            j = int(str(self.jours)   or "0")
            h = int(str(self.heures)  or "0")
            m = int(str(self.minutes) or "10")
            seconds = j*86400 + h*3600 + m*60
            if seconds < 60:
                return await interaction.response.send_message("Minimum 1 minute.", ephemeral=True)
            cfg = get_guild("antiraid.json", self.guild_id)
            cfg["automod_timeout_duration"] = seconds
            set_guild("antiraid.json", self.guild_id, cfg)
            label = f"{j}j " if j else ""
            label += f"{h}h " if h else ""
            label += f"{m}min" if m else ""
            await interaction.response.send_message(f"✅ Timeout défini : **{label.strip()}**", ephemeral=True)
            await self.parent._refresh(interaction) if hasattr(self.parent, '_refresh') else None
        except:
            await interaction.response.send_message("Valeur invalide.", ephemeral=True)

@bot.command(name="automod")
@commands.has_permissions(administrator=True)
async def automod_settings(ctx):
    cfg = get_guild("antiraid.json", ctx.guild.id)
    e   = _automod_embed(ctx.guild, cfg)
    view = AutomodView(ctx.guild)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

def _automod_embed(guild, cfg):
    e = discord.Embed(title="🛡️ Automod - Configuration", color=get_color(guild.id), timestamp=datetime.utcnow())

    # Antispam
    spam_on = cfg.get("antispam", False)
    punish_spam = cfg.get("punish_antispam","mute")
    td_seconds  = cfg.get("automod_timeout_duration", 600)
    td_label    = f"{td_seconds//3600}h{(td_seconds%3600)//60}min" if td_seconds >= 3600 else f"{td_seconds//60}min"
    timeout_str = f" ({td_label})" if punish_spam == "timeout" else ""
    e.add_field(
        name="💬 Antispam",
        value=f"{'✅ Actif' if spam_on else '❌ Inactif'}\nLimite : `{cfg.get('antispam_limit',5)}` msgs / `{cfg.get('antispam_window',5)}s`\nPunition : `{punish_spam}{timeout_str}`",
        inline=True
    )
    # Antilink
    link_on = cfg.get("antilink", False)
    e.add_field(
        name="🔗 Antilink",
        value=f"{'✅ Actif' if link_on else '❌ Inactif'}\nMode : `{cfg.get('antilink_mode','all')}`\nPunition : `{cfg.get('punish_antilink','warn')}`",
        inline=True
    )
    # Antimassmention
    mention_on = cfg.get("antimassmention", False)
    e.add_field(
        name="📢 Anti mention spam",
        value=f"{'✅ Actif' if mention_on else '❌ Inactif'}\nLimite : `{cfg.get('antimassmention_limit',5)}` mentions\nPunition : `{cfg.get('punish_antimassmention','muté')}`",
        inline=True
    )
    # Antieveryone
    every_on = cfg.get("antieveryone", False)
    e.add_field(
        name="📣 Anti @everyone",
        value=f"{'✅ Actif' if every_on and every_on != 'off' else '❌ Inactif'}\nPunition : `{cfg.get('punish_antieveryone','warn')}`",
        inline=True
    )
    # Badwords
    bw_on = cfg.get("badwords", False)
    words = cfg.get("badwords_list", [])
    e.add_field(
        name="🚫 Mots interdits",
        value=f"{'✅ Actif' if bw_on else '❌ Inactif'}\n`{len(words)}` mot(s) configure(s)",
        inline=True
    )
    # Piconly
    mcfg    = get_guild("modconfig.json", guild.id)
    piconly = mcfg.get("piconly", [])
    e.add_field(
        name="🖼️ Piconly",
        value=f"`{len(piconly)}` salon(s) en mode photo",
        inline=True
    )
    # Whitelist
    wl = cfg.get("whitelist", [])
    e.add_field(
        name="✅ Whitelist",
        value=f"`{len(wl)}` membre(s) en whitelist",
        inline=True
    )
    # Création limit
    cl = cfg.get("creation_limit")
    e.add_field(
        name="🆕 Age minimum compte",
        value=f"`{cl}s` ({cl//86400}j)" if cl else "❌ Inactif",
        inline=True
    )
    e.set_footer(text="Utilisez le menu ci-dessous pour tout configurer")
    return e

class AutomodView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.guild   = guild
        self.message = None
        self._build()

    def _build(self):
        for item in self.children[:]:
            self.remove_item(item)

        # Menu 1 : Toggles
        s1 = discord.ui.Select(
            placeholder="⚙️ Activer / Désactiver",
            options=[
                discord.SelectOption(label="Antispam on/off",          emoji="💬", value="toggle_antispam"),
                discord.SelectOption(label="Antilink on/off",           emoji="🔗", value="toggle_antilink"),
                discord.SelectOption(label="Anti mention spam on/off",  emoji="📢", value="toggle_antimassmention"),
                discord.SelectOption(label="Anti @everyone on/off",     emoji="📣", value="toggle_antieveryone"),
                discord.SelectOption(label="Mots interdits on/off",     emoji="🚫", value="toggle_badwords"),
            ],
            custom_id="am_toggles"
        )
        s1.callback = self.cb_toggles
        self.add_item(s1)

        # Menu 2 : Reglages
        s2 = discord.ui.Select(
            placeholder="🔧 Règler les limites & punitions",
            options=[
                discord.SelectOption(label="Limite antispam",           emoji="💬", value="set_spam_limit"),
                discord.SelectOption(label="Mode antilink (all/invite)", emoji="🔗", value="set_link_mode"),
                discord.SelectOption(label="Limite mentions",           emoji="📢", value="set_mention_limit"),
                discord.SelectOption(label="Age minimum compte",        emoji="🆕", value="set_creation_limit"),
                discord.SelectOption(label="Punition antispam",         emoji="⚠️", value="punish_antispam"),
                discord.SelectOption(label="Punition antilink",         emoji="⚠️", value="punish_antilink"),
                discord.SelectOption(label="Punition mentions",         emoji="⚠️", value="punish_antimassmention"),
                discord.SelectOption(label="Punition @everyone",        emoji="⚠️", value="punish_antieveryone"),
                discord.SelectOption(label="Durée timeout automod",     emoji="⏱️", value="set_timeout_duration"),
            ],
            custom_id="am_settings"
        )
        s2.callback = self.cb_settings
        self.add_item(s2)

        # Menu 3 : Badwords & Whitelist
        s3 = discord.ui.Select(
            placeholder="🚫 Mots interdits & Whitelist",
            options=[
                discord.SelectOption(label="Ajouter un mot interdit",   emoji="➕", value="bw_add"),
                discord.SelectOption(label="Voir les mots interdits",   emoji="📋", value="bw_list"),
                discord.SelectOption(label="Supprimer un mot interdit", emoji="➖", value="bw_del"),
                discord.SelectOption(label="Vider la liste badwords",   emoji="🗑️", value="bw_clear"),
                discord.SelectOption(label="Voir la whitelist",         emoji="✅", value="wl_list"),
                discord.SelectOption(label="Ajouter a la whitelist",    emoji="➕", value="wl_add"),
                discord.SelectOption(label="Vider la whitelist",        emoji="🗑️", value="wl_clear"),
            ],
            custom_id="am_badwords"
        )
        s3.callback = self.cb_badwords
        self.add_item(s3)

    async def _refresh(self, interaction):
        cfg = get_guild("antiraid.json", self.guild.id)
        e   = _automod_embed(self.guild, cfg)
        await interaction.response.edit_message(embed=e, view=self)

    async def cb_toggles(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        cfg = get_guild("antiraid.json", self.guild.id)
        keys = {
            "toggle_antispam":       "antispam",
            "toggle_antilink":       "antilink",
            "toggle_antimassmention":"antimassmention",
            "toggle_antieveryone":   "antieveryone",
            "toggle_badwords":       "badwords",
        }
        key     = keys[val]
        cfg[key] = not bool(cfg.get(key, False))
        set_guild("antiraid.json", self.guild.id, cfg)
        await self._refresh(interaction)

    async def cb_settings(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]

        if val.startswith("punish_"):
            key = val.replace("punish_", "punish_")
            sel = discord.ui.Select(
                placeholder="Choisir la punition",
                options=[
                    discord.SelectOption(label="Supprimer le message", emoji="🗑️", value="delete",   description="Supprime seulement le message"),
                    discord.SelectOption(label="Warn",                 emoji="⚠️", value="warn",    description="Avertissement"),
                    discord.SelectOption(label="Timeout",              emoji="⏱️", value="timeout", description="Timeout configurable"),
                    discord.SelectOption(label="Mute",                 emoji="🔇", value="mute",    description="Ajoute le rôle muet"),
                    discord.SelectOption(label="Kick",                 emoji="👢", value="kick",    description="Expulse le membre"),
                    discord.SelectOption(label="Ban",                  emoji="🔨", value="ban",     description="Bannit le membre"),
                ]
            )
            parent = self
            pkey = key
            async def punish_cb(inter):
                chosen = inter.data["values"][0]
                cfg2   = get_guild("antiraid.json", self.guild.id)
                cfg2[pkey] = chosen
                set_guild("antiraid.json", self.guild.id, cfg2)
                if chosen == "timeout":
                    await inter.response.send_modal(AutomodTimeoutDurationModal(self.guild.id, pkey, parent))
                else:
                    await parent._refresh(inter)
            sel.callback = punish_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        if val == "set_link_mode":
            sel = discord.ui.Select(
                placeholder="Mode antilink",
                options=[
                    discord.SelectOption(label="Tous les liens (all)",           value="all"),
                    discord.SelectOption(label="Invitations seulement (invite)", value="invite"),
                ]
            )
            parent = self
            async def link_cb(inter):
                cfg2 = get_guild("antiraid.json", self.guild.id)
                cfg2["antilink_mode"] = inter.data["values"][0]
                set_guild("antiraid.json", self.guild.id, cfg2)
                await parent._refresh(inter)
            sel.callback = link_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        # Modals pour les valeurs numeriques
        modals = {
            "set_spam_limit":       AutomodNumberModal("Limite antispam", "antispam_limit",    "Nombre de messages avant sanction (ex: 5)", self),
            "set_mention_limit":    AutomodNumberModal("Limite mentions",  "antimassmention_limit", "Nombre de mentions avant sanction (ex: 5)", self),
            "set_creation_limit":   AutomodNumberModal("Age minimum (secondes)", "creation_limit", "Ex: 604800 = 7 jours", self),
            "set_timeout_duration": AutomodTimeoutDurationModal(self.guild.id, "automod_timeout_duration", self),
        }
        if val in modals:
            return await interaction.response.send_modal(modals[val])

    async def cb_badwords(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        val = interaction.data["values"][0]
        cfg = get_guild("antiraid.json", self.guild.id)

        if val == "bw_add":
            return await interaction.response.send_modal(BadwordAddModal(self))

        if val == "bw_list":
            words = cfg.get("badwords_list", [])
            e = discord.Embed(title="🚫 Mots interdits", color=get_color(self.guild.id))
            e.description = ", ".join(f"`{w}`" for w in words) if words else "*Aucun mot configure*"
            e.set_footer(text=f"{len(words)} mot(s)")
            return await interaction.response.send_message(embed=e, ephemeral=True)

        if val == "bw_del":
            words = cfg.get("badwords_list", [])
            if not words:
                return await interaction.response.send_message("Aucun mot a supprimer.", ephemeral=True)
            sel = discord.ui.Select(
                placeholder="Supprimer un mot",
                options=[discord.SelectOption(label=w[:25], value=w) for w in words[:25]]
            )
            parent = self
            async def del_cb(inter):
                cfg2  = get_guild("antiraid.json", self.guild.id)
                words2 = cfg2.get("badwords_list", [])
                word   = inter.data["values"][0]
                if word in words2: words2.remove(word)
                cfg2["badwords_list"] = words2
                set_guild("antiraid.json", self.guild.id, cfg2)
                await parent._refresh(inter)
            sel.callback = del_cb
            v = discord.ui.View(timeout=60); v.add_item(sel)
            return await interaction.response.edit_message(view=v)

        if val == "bw_clear":
            cfg["badwords_list"] = []
            set_guild("antiraid.json", self.guild.id, cfg)
            return await self._refresh(interaction)

        if val == "wl_list":
            wl      = cfg.get("whitelist", [])
            members = [self.guild.get_member(int(m)) for m in wl if self.guild.get_member(int(m))]
            e = discord.Embed(title="✅ Whitelist Automod", color=get_color(self.guild.id))
            e.description = "\n".join(f"- {m.mention}" for m in members) if members else "*Vide*"
            return await interaction.response.send_message(embed=e, ephemeral=True)

        if val == "wl_add":
            return await interaction.response.send_modal(WhitelistAddModal(self))

        if val == "wl_clear":
            cfg["whitelist"] = []
            set_guild("antiraid.json", self.guild.id, cfg)
            return await self._refresh(interaction)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class AutomodNumberModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Valeur", placeholder="Ex: 5", max_length=10)
    def __init__(self, title, cfg_key, placeholder, parent):
        super().__init__(title=title)
        self.cfg_key = cfg_key
        self.parent  = parent
        self.value.placeholder = placeholder
    async def on_submit(self, interaction: discord.Interaction):
        try:
            cfg = get_guild("antiraid.json", self.parent.guild.id)
            cfg[self.cfg_key] = int(str(self.value))
            set_guild("antiraid.json", self.parent.guild.id, cfg)
            await self.parent._refresh(interaction)
        except:
            await interaction.response.send_message("Valeur numerique invalide.", ephemeral=True)

class BadwordAddModal(discord.ui.Modal, title="Ajouter un mot interdit"):
    word = discord.ui.TextInput(label="Mot a interdire", placeholder="Ex: spam", max_length=50)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        cfg   = get_guild("antiraid.json", self.parent.guild.id)
        words = cfg.get("badwords_list", [])
        w     = str(self.word).lower().strip()
        if w not in words: words.append(w)
        cfg["badwords_list"] = words
        set_guild("antiraid.json", self.parent.guild.id, cfg)
        await self.parent._refresh(interaction)

class WhitelistAddModal(discord.ui.Modal, title="Ajouter a la whitelist"):
    member_id = discord.ui.TextInput(label="ID du membre", placeholder="Ex: 123456789012345678", max_length=20)
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            mid  = str(self.member_id).strip()
            cfg  = get_guild("antiraid.json", self.parent.guild.id)
            wl   = cfg.get("whitelist", [])
            if mid not in wl: wl.append(mid)
            cfg["whitelist"] = wl
            set_guild("antiraid.json", self.parent.guild.id, cfg)
            await self.parent._refresh(interaction)
        except:
            await interaction.response.send_message("ID invalide.", ephemeral=True)

#  ANTIRAID AVANCE - DETECTION + SANCTION PAR AUDIT LOG

# Caché pour compter les actions par user sur une fenetre de temps
from collections import defaultdict
_ar_cache = defaultdict(lambda: defaultdict(list))  # guild_id -> user_id -> [timestamps]

async def _ar_check(guild, user, action_key, limit_key, window_key, punish_key, label):
    """
    Verifie si un user a depasse la limite d'actions.
    Retourne True si sanctionné.
    """
    if not user or user.bot: return False
    cfg = get_guild("antiraid.json", guild.id)
    if not cfg.get(action_key): return False

    # Whitelist
    wl = cfg.get("whitelist", [])
    if str(user.id) in wl: return False

    # Compter les actions dans la fenetre
    limit  = cfg.get(limit_key, 3)
    window = cfg.get(window_key, 10)
    now    = datetime.utcnow().timestamp()
    caché  = _ar_cache[guild.id][f"{user.id}_{action_key}"]
    caché.append(now)
    _ar_cache[guild.id][f"{user.id}_{action_key}"] = [t for t in caché if now - t < window]

    if len(_ar_cache[guild.id][f"{user.id}_{action_key}"]) >= limit:
        _ar_cache[guild.id][f"{user.id}_{action_key}"] = []

        # Punir
        punishment = cfg.get(punish_key, "kick")
        member     = guild.get_member(user.id)
        if member:
            try:
                if punishment == "ban":
                    await guild.ban(member, reason=f"Antiraid - {label}")
                elif punishment == "kick":
                    await member.kick(reason=f"Antiraid - {label}")
                elif punishment == "muté":
                    r = await get_mute_role(guild)
                    await member.add_roles(r, reason=f"Antiraid - {label}")
                elif punishment == "derank":
                    roles = [r for r in member.roles if r != guild.default_role and r.position < guild.me.top_role.position]
                    await member.remove_roles(*roles, reason=f"Antiraid - {label}")
            except: pass

        # Log
        e = discord.Embed(
            title=f"🚨 Antiraid - {label}",
            description=f"{user.mention} a effectue **{limit}** actions `{label}` en `{window}s`.\nSanction : **{punishment}**",
            color=0xff0000,
            timestamp=datetime.utcnow()
        )
        e.set_thumbnail(url=user.display_avatar.url if hasattr(user, "display_avatar") else discord.Embed.Empty)
        e.add_field(name="👤 Utilisateur", value=f"{user.mention} `({user.id})`", inline=True)
        e.add_field(name="⚠️ Action",      value=label, inline=True)
        e.add_field(name="🔨 Sanction",    value=punishment.upper(), inline=True)

        # Ping raidping
        cfg2    = get_guild("antiraid.json", guild.id)
        ping_id = cfg2.get("raidping")
        if ping_id:
            role_ping = guild.get_role(int(ping_id))
            if role_ping:
                await send_log(guild, "raidlog", e)
                for ch in guild.text_channels:
                    cid = get_guild("logs.json", guild.id).get("raidlog")
                    if cid and str(ch.id) == cid:
                        try: await ch.send(role_ping.mention)
                        except: pass
                        break
        else:
            await send_log(guild, "raidlog", e)

        return True
    return False

@bot.event
async def on_guild_channel_delete_antiraid(channel):
    cfg = get_guild("antiraid.json", channel.guild.id)
    if not cfg.get("anti_delete_channel"): return
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(channel.guild, entry.user, "anti_delete_channel",
                    "anti_delete_channel_limit", "anti_delete_channel_window",
                    "punish_anti_delete_channel", "Suppression de salons")
                if sanctionne:
                    # Recreer le salon dans la meme categorie avec les memes permissions
                    try:
                        new_ch = await channel.guild.create_text_channel(
                            channel.name,
                            category=channel.category,
                            overwrites=channel.overwrites,
                            topic=channel.topic if hasattr(channel, "topic") else None,
                            position=channel.position,
                        )
                        e = discord.Embed(title="♻️ Salon recréé automatiquement", color=0x00ff00, timestamp=datetime.utcnow())
                        e.add_field(name="📌 Salon", value=f"#{new_ch.name}", inline=True)
                        e.add_field(name="📁 Catégorie", value=channel.category.name if channel.category else "Aucune", inline=True)
                        e.add_field(name="🛡️ Raison", value="Anti-delete channel déclenché", inline=False)
                        await new_ch.send(embed=e)
                        await send_log(channel.guild, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_delete_channel] Erreur recreation: {ex}")
    except: pass

@bot.event
async def on_guild_channel_create_antiraid(channel):
    cfg = get_guild("antiraid.json", channel.guild.id)
    if not cfg.get("anti_create_channel"): return
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(channel.guild, entry.user, "anti_create_channel",
                    "anti_create_channel_limit", "anti_create_channel_window",
                    "punish_anti_create_channel", "Création de salons")
                if sanctionne:
                    # Supprimer le salon créé
                    try:
                        await channel.delete(reason="Anti-create channel déclenché")
                        e = discord.Embed(title="🗑️ Salon supprimé automatiquement", color=0xff4500, timestamp=datetime.utcnow())
                        e.add_field(name="📌 Salon", value=f"#{channel.name}", inline=True)
                        e.add_field(name="🛡️ Raison", value="Anti-create channel déclenché", inline=False)
                        await send_log(channel.guild, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_create_channel] Erreur suppression: {ex}")
    except: pass

@bot.event
async def on_guild_channel_update_antiraid(before, after):
    cfg = get_guild("antiraid.json", after.guild.id)
    if not cfg.get("anti_manage_channel"): return
    try:
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(after.guild, entry.user, "anti_manage_channel",
                    "anti_manage_channel_limit", "anti_manage_channel_window",
                    "punish_anti_manage_channel", "Modification de salons")
                if sanctionne:
                    # Revenir aux parametres d'avant
                    try:
                        edit_kwargs = {}
                        if before.name != after.name:
                            edit_kwargs["name"] = before.name
                        if hasattr(before, "topic") and before.topic != after.topic:
                            edit_kwargs["topic"] = before.topic
                        if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
                            edit_kwargs["slowmode_delay"] = before.slowmode_delay
                        if hasattr(before, "nsfw") and before.nsfw != after.nsfw:
                            edit_kwargs["nsfw"] = before.nsfw
                        if edit_kwargs:
                            await after.edit(**edit_kwargs, reason="Anti-manage channel — modifications annulées")
                        e = discord.Embed(title="↩️ Modifications annulées", color=0xff8c00, timestamp=datetime.utcnow())
                        e.add_field(name="📌 Salon", value=after.mention, inline=True)
                        e.add_field(name="🛡️ Raison", value="Anti-manage channel déclenché", inline=False)
                        await send_log(after.guild, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_manage_channel] Erreur revert: {ex}")
    except: pass

@bot.event
async def on_guild_role_delete_antiraid(role):
    # Sauvegarder les infos du role AVANT suppression
    role_backup = {
        "name":        role.name,
        "color":       role.color.value,
        "permissions": role.permissions.value,
        "hoist":       role.hoist,
        "mentionable": role.mentionable,
        "position":    role.position,
    }
    cfg = get_guild("antiraid.json", role.guild.id)
    if not cfg.get("anti_delete_role"): return
    try:
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(role.guild, entry.user, "anti_delete_role",
                    "anti_delete_role_limit", "anti_delete_role_window",
                    "punish_anti_delete_role", "Suppression de roles")
                if sanctionne:
                    # Recreer le role avec ses anciennes proprietes
                    try:
                        new_role = await role.guild.create_role(
                            name=role_backup["name"],
                            color=discord.Color(role_backup["color"]),
                            permissions=discord.Permissions(role_backup["permissions"]),
                            hoist=role_backup["hoist"],
                            mentionable=role_backup["mentionable"],
                            reason="Anti-delete role — rôle recréé automatiquement"
                        )
                        e = discord.Embed(title="♻️ Rôle recréé automatiquement", color=0x00ff00, timestamp=datetime.utcnow())
                        e.add_field(name="🏷️ Rôle", value=new_role.mention, inline=True)
                        e.add_field(name="🛡️ Raison", value="Anti-delete role déclenché", inline=False)
                        await send_log(role.guild, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_delete_role] Erreur recreation: {ex}")
    except: pass

@bot.event
async def on_guild_role_update_antiraid(before, after):
    cfg = get_guild("antiraid.json", after.guild.id)
    if not cfg.get("anti_manage_role"): return
    try:
        async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(after.guild, entry.user, "anti_manage_role",
                    "anti_manage_role_limit", "anti_manage_role_window",
                    "punish_anti_manage_role", "Modification de roles")
                if sanctionne:
                    # Revenir aux proprietes d'avant
                    try:
                        edit_kwargs = {}
                        if before.name != after.name:
                            edit_kwargs["name"] = before.name
                        if before.color != after.color:
                            edit_kwargs["color"] = before.color
                        if before.permissions != after.permissions:
                            edit_kwargs["permissions"] = before.permissions
                        if before.hoist != after.hoist:
                            edit_kwargs["hoist"] = before.hoist
                        if before.mentionable != after.mentionable:
                            edit_kwargs["mentionable"] = before.mentionable
                        if edit_kwargs:
                            await after.edit(**edit_kwargs, reason="Anti-manage role — modifications annulées")
                        e = discord.Embed(title="↩️ Modifications rôle annulées", color=0xff8c00, timestamp=datetime.utcnow())
                        e.add_field(name="🏷️ Rôle", value=after.mention, inline=True)
                        e.add_field(name="🛡️ Raison", value="Anti-manage role déclenché", inline=False)
                        await send_log(after.guild, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_manage_role] Erreur revert: {ex}")
    except: pass

@bot.event
async def on_member_update_antirank(before, after):
    cfg = get_guild("antiraid.json", before.guild.id)
    if not cfg.get("anti_rank"): return
    added = [r for r in after.roles if r not in before.roles]
    if not added: return
    dangerous_perms = ["administrator","manage_guild","ban_members","kick_members","manage_roles","manage_channels","mention_everyone"]
    dangerous = any(
        any(getattr(r.permissions, p, False) for p in dangerous_perms)
        for r in added
    )
    if not dangerous: return
    try:
        async for entry in before.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(before.guild, entry.user, "anti_rank",
                    "anti_rank_limit", "anti_rank_window",
                    "punish_anti_rank", "Attribution de roles dangereux")
                if sanctionne:
                    # Retirer les roles dangereux attribués
                    try:
                        await after.remove_roles(*added, reason="Anti-rank — rôles dangereux retirés")
                        e = discord.Embed(title="↩️ Rôles dangereux retirés", color=0xff0000, timestamp=datetime.utcnow())
                        e.add_field(name="👤 Membre", value=after.mention, inline=True)
                        e.add_field(name="🏷️ Rôles retirés", value=" ".join(r.mention for r in added), inline=True)
                        await send_log(before.guild, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_rank] Erreur retrait roles: {ex}")
    except: pass

@bot.event
async def on_guild_update_antiraid(before, after):
    cfg = get_guild("antiraid.json", after.id)
    if not cfg.get("anti_manage_server"): return
    try:
        async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                sanctionne = await _ar_check(after, entry.user, "anti_manage_server",
                    "anti_manage_server_limit", "anti_manage_server_window",
                    "punish_anti_manage_server", "Modification du serveur")
                if sanctionne:
                    # Revenir aux parametres d'avant
                    try:
                        edit_kwargs = {}
                        if before.name != after.name:
                            edit_kwargs["name"] = before.name
                        if before.verification_level != after.verification_level:
                            edit_kwargs["verification_level"] = before.verification_level
                        if before.default_notifications != after.default_notifications:
                            edit_kwargs["default_notifications"] = before.default_notifications
                        if edit_kwargs:
                            await after.edit(**edit_kwargs, reason="Anti-manage server — modifications annulées")
                        e = discord.Embed(title="↩️ Modifications serveur annulées", color=0xff8c00, timestamp=datetime.utcnow())
                        e.add_field(name="🛡️ Raison", value="Anti-manage server déclenché", inline=False)
                        await send_log(after, "raidlog", e)
                    except Exception as ex:
                        print(f"[anti_manage_server] Erreur revert: {ex}")
    except: pass

@bot.event
async def on_webhooks_update_antiraid(channel):
    cfg = get_guild("antiraid.json", channel.guild.id)
    if not cfg.get("anti_webhook_create"): return
    try:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                await _ar_check(channel.guild, entry.user, "anti_webhook_create",
                    "anti_webhook_limit", "anti_webhook_window",
                    "punish_anti_webhook", "Création de webhook")
                # Supprimer le webhook automatiquement
                try:
                    webhooks = await channel.guild.webhooks()
                    for wh in webhooks:
                        age = (datetime.utcnow() - wh.created_at.replace(tzinfo=None)).total_seconds()
                        if age < 5:
                            await wh.delete(reason="Antiraid - webhook supprimé automatiquement")
                except: pass
    except: pass

# On les injecte dans les events existants via monkey-patching propre


@bot.event
async def on_member_remove_antikick(member):
    cfg = get_guild("antiraid.json", member.guild.id)
    if not cfg.get("anti_kick"): return
    try:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                await _ar_check(member.guild, entry.user, "anti_kick",
                    "anti_kick_limit", "anti_kick_window",
                    "punish_anti_kick", "Expulsion de membres")
    except: pass

@bot.event
async def on_member_ban_antiraid(guild, user):
    cfg = get_guild("antiraid.json", guild.id)
    if not cfg.get("anti_ban"): return
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                await _ar_check(guild, entry.user, "anti_ban",
                    "anti_ban_limit", "anti_ban_window",
                    "punish_anti_ban", "Bannissement de membres")
    except: pass

@bot.event
async def on_voice_state_update_antiraid(member, before, after):
    cfg = get_guild("antiraid.json", member.guild.id)
    try:
        # Anti muté
        if cfg.get("anti_mute") and not before.muté and after.muté:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                    await _ar_check(member.guild, entry.user, "anti_mute",
                        "anti_mute_limit", "anti_mute_window",
                        "punish_anti_mute", "Muté vocal en masse")
                    break
        # Anti deafen
        if cfg.get("anti_deafen") and not before.deaf and after.deaf:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                    await _ar_check(member.guild, entry.user, "anti_deafen",
                        "anti_deafen_limit", "anti_deafen_window",
                        "punish_anti_deafen", "Deafen vocal en masse")
                    break
        # Anti move member
        if cfg.get("anti_move_member") and before.channel and after.channel and before.channel != after.channel:
            async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_move):
                if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                    await _ar_check(member.guild, entry.user, "anti_move_member",
                        "anti_move_member_limit", "anti_move_member_window",
                        "punish_anti_move_member", "Deplacement de membres en masse")
                    break
    except: pass

@bot.event
async def on_member_remove_antiprune(member):
    cfg = get_guild("antiraid.json", member.guild.id)
    if not cfg.get("anti_prune"): return
    try:
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_prune):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 3:
                await _ar_check(member.guild, entry.user, "anti_prune",
                    "anti_prune_limit", "anti_prune_window",
                    "punish_anti_prune", "Prune de membres")
    except: pass

bot.add_listener(on_guild_channel_delete_antiraid, "on_guild_channel_delete")
bot.add_listener(on_guild_channel_create_antiraid, "on_guild_channel_create")
bot.add_listener(on_guild_channel_update_antiraid, "on_guild_channel_update")
bot.add_listener(on_guild_role_delete_antiraid,    "on_guild_role_delete")
bot.add_listener(on_guild_role_update_antiraid,    "on_guild_role_update")
bot.add_listener(on_member_update_antirank,        "on_member_update")
bot.add_listener(on_guild_update_antiraid,         "on_guild_update")
bot.add_listener(on_webhooks_update_antiraid,      "on_webhooks_update")
bot.add_listener(on_member_remove_antikick,        "on_member_remove")
bot.add_listener(on_member_remove_antiprune,       "on_member_remove")
bot.add_listener(on_member_ban_antiraid,           "on_member_ban")
bot.add_listener(on_voice_state_update_antiraid,   "on_voice_state_update")
bot.add_listener(on_voice_state_update_tempvoc,     "on_voice_state_update")

ANTIRAID_MODULES = {
    "anti_delete_channel":  {"label": "Anti delete channel",  "emoji": "🗑️", "default_limit": 3,  "default_window": 10, "default_punish": "derank"},
    "anti_create_channel":  {"label": "Anti create channel",  "emoji": "📁", "default_limit": 5,  "default_window": 10, "default_punish": "derank"},
    "anti_manage_channel":  {"label": "Anti manage channel",  "emoji": "✏️", "default_limit": 5,  "default_window": 10, "default_punish": "derank"},
    "anti_delete_role":     {"label": "Anti delete role",     "emoji": "🏷️", "default_limit": 3,  "default_window": 10, "default_punish": "derank"},
    "anti_manage_role":     {"label": "Anti manage role",     "emoji": "✏️", "default_limit": 5,  "default_window": 10, "default_punish": "derank"},
    "anti_rank":            {"label": "Anti rank",            "emoji": "⬆️", "default_limit": 3,  "default_window": 10, "default_punish": "derank"},
    "anti_manage_server":   {"label": "Anti manage server",   "emoji": "⚙️", "default_limit": 3,  "default_window": 10, "default_punish": "derank"},
    "anti_webhook_create":  {"label": "Anti webhook",         "emoji": "🔗", "default_limit": 2,  "default_window": 10, "default_punish": "derank"},
    "anti_kick":            {"label": "Anti kick",            "emoji": "👢", "default_limit": 3,  "default_window": 10, "default_punish": "derank"},
    "anti_ban":             {"label": "Anti ban",             "emoji": "🔨", "default_limit": 3,  "default_window": 10, "default_punish": "derank"},
    "anti_mute":            {"label": "Anti muté",            "emoji": "🔇", "default_limit": 5,  "default_window": 10, "default_punish": "derank"},
    "anti_deafen":          {"label": "Anti deafen",          "emoji": "🔕", "default_limit": 5,  "default_window": 10, "default_punish": "derank"},
    "anti_move_member":     {"label": "Anti move member",     "emoji": "↩️", "default_limit": 5,  "default_window": 10, "default_punish": "derank"},
    "anti_prune":           {"label": "Anti prune",           "emoji": "✂️", "default_limit": 1,  "default_window": 30, "default_punish": "derank"},
}

@bot.command(name="antiraid_settings")
@commands.has_permissions(administrator=True)
async def antiraid_settings(ctx):
    cfg  = get_guild("antiraid.json", ctx.guild.id)
    e    = _antiraid_embed(ctx.guild, cfg)
    view = AntiraidSettingsView(ctx.guild)
    msg  = await ctx.send(embed=e, view=view)
    view.message = msg

def _antiraid_embed(guild, cfg):
    e = discord.Embed(title="🛡️ Antiraid Avance - Configuration", color=get_color(guild.id), timestamp=datetime.utcnow())
    for key, info in ANTIRAID_MODULES.items():
        activé  = cfg.get(key, False)
        limit   = cfg.get(f"{key}_limit",  info["default_limit"])
        window  = cfg.get(f"{key}_window", info["default_window"])
        punish  = cfg.get(f"punish_{key}", info["default_punish"])
        e.add_field(
            name=f"{info['emoji']} {info['label']}",
            value=f"{'✅ Actif' if activé else '❌ Inactif'}\n`{limit}` actions / `{window}s` → **{punish}**",
            inline=True
        )
    e.set_footer(text="Utilisez le menu ci-dessous pour configurer chaque module")
    return e

class AntiraidSettingsView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.guild   = guild
        self.message = None
        self._build()

    def _build(self):
        for item in self.children[:]: self.remove_item(item)

        # Menu toggle
        s1 = discord.ui.Select(
            placeholder="⚙️ Activer / Désactiver un module",
            options=[
                discord.SelectOption(label=info["label"], emoji=info["emoji"], value=key)
                for key, info in ANTIRAID_MODULES.items()
            ],
            custom_id="ars_toggle"
        )
        s1.callback = self.cb_toggle
        self.add_item(s1)

        # Menu reglages
        s2 = discord.ui.Select(
            placeholder="🔧 Règler limite / fenetre / punition",
            options=[
                discord.SelectOption(label=info["label"], emoji=info["emoji"], value=key)
                for key, info in ANTIRAID_MODULES.items()
            ],
            custom_id="ars_settings"
        )
        s2.callback = self.cb_settings
        self.add_item(s2)

        # Bouton reset
        btn = discord.ui.Button(label="♻️ Reset tous les modules", style=discord.ButtonStyle.danger, custom_id="ars_reset")
        btn.callback = self.cb_reset
        self.add_item(btn)

    async def _refresh(self, interaction):
        cfg = get_guild("antiraid.json", self.guild.id)
        e   = _antiraid_embed(self.guild, cfg)
        await interaction.response.edit_message(embed=e, view=self)

    async def cb_toggle(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        key = interaction.data["values"][0]
        cfg = get_guild("antiraid.json", self.guild.id)
        cfg[key] = not cfg.get(key, False)
        # Initialise les valeurs par defaut si premiere activation
        if cfg[key]:
            info = ANTIRAID_MODULES[key]
            cfg.setdefault(f"{key}_limit",  info["default_limit"])
            cfg.setdefault(f"{key}_window", info["default_window"])
            cfg.setdefault(f"punish_{key}", info["default_punish"])
        set_guild("antiraid.json", self.guild.id, cfg)
        await self._refresh(interaction)

    async def cb_settings(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        key  = interaction.data["values"][0]
        info = ANTIRAID_MODULES[key]
        await interaction.response.send_modal(AntiraidModuleModal(key, info, self))

    async def cb_reset(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Permission refusée.", ephemeral=True)
        cfg = get_guild("antiraid.json", self.guild.id)
        for key in ANTIRAID_MODULES:
            cfg[key] = False
        set_guild("antiraid.json", self.guild.id, cfg)
        await self._refresh(interaction)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class AntiraidModuleModal(discord.ui.Modal):
    limit_  = discord.ui.TextInput(label="Limite (nb actions)", placeholder="Ex: 3",  max_length=3)
    window_ = discord.ui.TextInput(label="Fenetre (secondes)",  placeholder="Ex: 10", max_length=5)
    punish_ = discord.ui.TextInput(label="Punition (warn/mute/kick/ban/derank)", placeholder="kick", max_length=10)

    def __init__(self, key, info, parent):
        super().__init__(title=f"⚙️ {info['label']}")
        self.key    = key
        self.parent = parent
        cfg = get_guild("antiraid.json", parent.guild.id)
        self.limit_.default  = str(cfg.get(f"{key}_limit",  info["default_limit"]))
        self.window_.default = str(cfg.get(f"{key}_window", info["default_window"]))
        self.punish_.default = str(cfg.get(f"punish_{key}", info["default_punish"]))

    async def on_submit(self, interaction: discord.Interaction):
        cfg = get_guild("antiraid.json", self.parent.guild.id)
        try:    cfg[f"{self.key}_limit"]  = max(1, int(str(self.limit_)))
        except: pass
        try:    cfg[f"{self.key}_window"] = max(1, int(str(self.window_)))
        except: pass
        punish = str(self.punish_).lower().strip()
        if punish in ("warn","muté","kick","ban","derank","tempban"):
            cfg[f"punish_{self.key}"] = punish
        set_guild("antiraid.json", self.parent.guild.id, cfg)
        await self.parent._refresh(interaction)


@bot.command(name="timeout")
@commands.has_permissions(moderate_members=True)
async def timeout_cmd(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison"):
    delta = parse_dur(duration)
    if not delta:
        return await ctx.send("Duree invalide. Ex: `10m`, `2h`, `1d` (max 28 jours)")
    if delta.total_seconds() > 28 * 86400:
        return await ctx.send("Duree maximum : **28 jours**.")
    try:
        until = discord.utils.utcnow() + delta
        await member.timeout(until, reason=reason)
        await add_sanction(ctx.guild.id, member.id, "timeout", f"{duration} - {reason}", ctx.author.id)
        await ctx.send(f"{member.mention} a ete mis en timeout pour {duration}. Raison : {reason} (fin <t:{int(until.timestamp())}:R>)")
        await log_mod(ctx.guild, "timeout", member, ctx.author, reason, extra={"⏱️ Durée": duration, "🕐 Fin": f"<t:{int(until.timestamp())}:R>"})
    except discord.Forbidden:
        await ctx.send("Je n'ai pas la permission de timeout ce membre.")
    except Exception as ex:
        await ctx.send(f"Erreur : {ex}")

@bot.command(name="untimeout")
@commands.has_permissions(moderate_members=True)
async def untimeout_cmd(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.send(f"{member.mention} n'est plus en timeout.")
    except discord.Forbidden:
        await ctx.send("Je n'ai pas la permission.")
    except Exception as ex:
        await ctx.send(f"Erreur : {ex}")

@bot.command(name="softban")
@commands.has_permissions(ban_members=True)
async def softban(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    try:
        await add_sanction(ctx.guild.id, member.id, "softban", reason, ctx.author.id)
        await ctx.guild.ban(member, reason=f"Softban par {ctx.author} - {reason}", delete_message_days=7)
        await ctx.guild.unban(member, reason="Softban - unban automatique")
        await ctx.send(f"{member} a ete softbanni (messages supprimes, peut revenir). Raison : {reason}")
        await log_mod(ctx.guild, "softban", member, ctx.author, reason, extra={"📝 Type": "Softban — peut revenir"})
    except discord.Forbidden:
        await ctx.send("Je n'ai pas la permission de bannir ce membre.")
    except Exception as ex:
        await ctx.send(f"Erreur : {ex}")


@bot.command(name="vocal")
async def vocal_cmd(ctx):
    """Gere ton salon vocal temporaire."""
    cfg   = get_guild("modconfig.json", ctx.guild.id)
    tvocs = cfg.get("tempvocs", {})
    # Trouver le vocal temp du membre
    vc_id = next((vid for vid, owner in tvocs.items() if owner == str(ctx.author.id)), None)
    if not vc_id:
        return await ctx.send("Tu n'as pas de salon vocal temporaire actif.")
    vc = ctx.guild.get_channel(int(vc_id))
    if not vc:
        return await ctx.send("Ton salon vocal temporaire est introuvable.")
    view = TempVocalView(ctx.author, vc)
    e = discord.Embed(title=f"🎙️ Ton salon : {vc.name}", color=get_color(ctx.guild.id))
    e.add_field(name="👥 Limite",   value=str(vc.user_limit) if vc.user_limit else "Aucune", inline=True)
    e.add_field(name="🔒 Statut",   value="Privé" if vc.overwrites_for(ctx.guild.default_role).connect is False else "Public", inline=True)
    e.add_field(name="👤 Membres",  value=str(len(vc.members)), inline=True)
    e.set_footer(text="Utilise les boutons pour gérer ton salon")
    msg = await ctx.send(embed=e, view=view)
    view.message = msg

class TempVocalView(discord.ui.View):
    def __init__(self, owner, vc):
        super().__init__(timeout=60)
        self.owner   = owner
        self.vc      = vc
        self.message = None

    async def check(self, interaction):
        if interaction.user != self.owner:
            await interaction.response.send_message("Ce n'est pas ton salon.", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction):
        vc = interaction.guild.get_channel(self.vc.id)
        if not vc:
            return await interaction.response.edit_message(content="Salon introuvable.", view=None)
        e = discord.Embed(title=f"🎙️ Ton salon : {vc.name}", color=get_color(interaction.guild.id))
        e.add_field(name="👥 Limite",   value=str(vc.user_limit) if vc.user_limit else "Aucune", inline=True)
        e.add_field(name="🔒 Statut",   value="Privé" if vc.overwrites_for(interaction.guild.default_role).connect is False else "Public", inline=True)
        e.add_field(name="👤 Membres",  value=str(len(vc.members)), inline=True)
        e.set_footer(text="Utilise les boutons pour gérer ton salon")
        await interaction.response.edit_message(embed=e, view=self)

    @discord.ui.button(label="🔓 Public", style=discord.ButtonStyle.success, custom_id="tv_public")
    async def set_public(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        try:
            await self.vc.set_permissions(interaction.guild.default_role, connect=True, view_channel=True)
            await interaction.channel.send(f"🔓 **{self.vc.name}** est maintenant **public**.", delete_after=5)
            await self.refresh(interaction)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

    @discord.ui.button(label="🔒 Privé", style=discord.ButtonStyle.danger, custom_id="tv_private")
    async def set_private(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        try:
            await self.vc.set_permissions(interaction.guild.default_role, connect=False, view_channel=True)
            await interaction.channel.send(f"🔒 **{self.vc.name}** est maintenant **privé**.", delete_after=5)
            await self.refresh(interaction)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

    @discord.ui.button(label="✏️ Renommer", style=discord.ButtonStyle.primary, custom_id="tv_rename")
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        await interaction.response.send_modal(TempVocalRenameModal(self.vc, self))

    @discord.ui.button(label="👥 Limite", style=discord.ButtonStyle.secondary, custom_id="tv_limit")
    async def set_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        await interaction.response.send_modal(TempVocalLimitModal(self.vc, self))

    @discord.ui.button(label="🚫 Expulser", style=discord.ButtonStyle.danger, custom_id="tv_kick")
    async def kick_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        vc = interaction.guild.get_channel(self.vc.id)
        members = [m for m in vc.members if m != self.owner]
        if not members:
            return await interaction.response.send_message("Aucun membre a expulser.", ephemeral=True)
        sel = discord.ui.Select(
            placeholder="Choisir un membre a expulser",
            options=[discord.SelectOption(label=m.display_name[:25], value=str(m.id)) for m in members[:25]]
        )
        async def kick_cb(inter):
            m = interaction.guild.get_member(int(inter.data["values"][0]))
            if m and m.voice and m.voice.channel == vc:
                await m.move_to(None)
                await inter.response.send_message(f"**{m.display_name}** a ete expulse du salon.", ephemeral=True)
            else:
                await inter.response.send_message("Membre introuvable dans le salon.", ephemeral=True)
        sel.callback = kick_cb
        v = discord.ui.View(timeout=30); v.add_item(sel)
        await interaction.response.send_message(view=v, ephemeral=True)

    async def on_timeout(self):
        try:
            for item in self.children: item.disabled = True
            if self.message: await self.message.edit(view=self)
        except: pass

class TempVocalRenameModal(discord.ui.Modal, title="Renommer le salon"):
    name = discord.ui.TextInput(label="Nouveau nom", placeholder="Ex: Salon de jeu", max_length=50)
    def __init__(self, vc, parent):
        super().__init__()
        self.vc = vc; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.vc.edit(name=str(self.name))
            await self.parent.refresh(interaction)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)

class TempVocalLimitModal(discord.ui.Modal, title="Limite de membres"):
    limit = discord.ui.TextInput(label="Limite (0 = aucune limite)", placeholder="Ex: 5", max_length=2)
    def __init__(self, vc, parent):
        super().__init__()
        self.vc = vc; self.parent = parent
    async def on_submit(self, interaction: discord.Interaction):
        try:
            lim = max(0, int(str(self.limit)))
            await self.vc.edit(user_limit=lim)
            await self.parent.refresh(interaction)
        except Exception as ex:
            await interaction.response.send_message(f"Erreur : {ex}", ephemeral=True)



@bot.command(name="warnlist")
@commands.has_permissions(manage_messages=True)
async def warnlist(ctx):
    """Affiche tous les membres ayant des avertissements sur le serveur."""
    data = db_load("sanctions.json").get(str(ctx.guild.id), {})
    # Filtrer les membres avec au moins 1 warn
    warned = []
    for mid, mdata in data.items():
        warns = [s for s in mdata.get("list", []) if s["type"] in ("warn", "avertissement")]
        if warns:
            member = ctx.guild.get_member(int(mid))
            name   = str(member) if member else f"Inconnu ({mid})"
            warned.append((name, mid, warns))

    if not warned:
        return await ctx.send("Aucun membre avec des avertissements sur ce serveur.")

    # Trier par nb de warns decroissant
    warned.sort(key=lambda x: len(x[2]), reverse=True)

    per_page = 10
    pages    = [warned[i:i+per_page] for i in range(0, len(warned), per_page)]
    total    = len(warned)

    def make_embed(page_idx):
        e = discord.Embed(
            title=f"⚠️ Membres avertis ({total})",
            color=0xffd700,
            timestamp=datetime.utcnow()
        )
        for name, mid, warns in pages[page_idx]:
            last = warns[-1]
            e.add_field(
                name=f"⚠️ {name}",
                value=f"`{len(warns)}` warn(s) | Dernier : {last['reason']} — {last['date'][:10]}",
                inline=False
            )
        e.set_footer(text=f"Page {page_idx+1}/{len(pages)} • {total} membre(s) avertis")
        return e

    class WarnListView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.page    = 0
            self.message = None
            self._update_buttons()

        def _update_buttons(self):
            self.prev_btn.disabled = (self.page == 0)
            self.next_btn.disabled = (self.page == len(pages) - 1)

        @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="wl_prev")
        async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page > 0:
                self.page -= 1
                self._update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="wl_next")
        async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
            if self.page < len(pages) - 1:
                self.page += 1
                self._update_buttons()
            await interaction.response.edit_message(embed=make_embed(self.page), view=self)

        async def on_timeout(self):
            try:
                for item in self.children: item.disabled = True
                if self.message: await self.message.edit(view=self)
            except: pass

    view = WarnListView()
    msg  = await ctx.send(embed=make_embed(0), view=view)
    view.message = msg



@bot.command(name="create")
@commands.has_permissions(manage_emojis=True)
async def create_cmd(ctx, *args):
    import re
    emoji_pattern = re.compile(r"<(a?):(\w+):(\d+)>")
    found = emoji_pattern.findall(ctx.message.content)

    if not found:
        e = discord.Embed(title="Copier des emojis", color=get_color(ctx.guild.id))
        e.add_field(name="Usage", value=(
            "`+create :emoji:` — Copie avec le nom original\n"
            "`+create :emoji: nom` — Copie avec un nom personnalise\n"
            "`+create :emoji1: :emoji2: :emoji3:` — Copie plusieurs emojis"
        ), inline=False)
        return await ctx.send(embed=e)

    # Nom custom si un seul emoji + texte apres
    custom_name = None
    if len(found) == 1:
        match = emoji_pattern.search(ctx.message.content)
        after = ctx.message.content[match.end():].strip()
        if after:
            custom_name = re.sub(r"[^a-zA-Z0-9_]", "_", after)[:32] or None

    msg = await ctx.send(f"Copie de **{len(found)}** emoji(s) en cours...")
    success = []
    errors  = []

    for animated, name, emoji_id in found:
        final_name = custom_name if (custom_name and len(found) == 1) else name
        ext  = "gif" if animated else "png"
        url  = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    data = await r.read()
            new_emoji = await ctx.guild.create_custom_emoji(name=final_name, image=data)
            success.append(str(new_emoji))
        except discord.HTTPException as ex:
            errors.append(f":{name}: — {ex}")
        except Exception as ex:
            errors.append(f":{name}: — Erreur")

    e = discord.Embed(
        title="Copie d'emojis",
        color=0x00ff00 if success else 0xff0000,
        timestamp=datetime.utcnow()
    )
    if success:
        e.add_field(name=f"Copies ({len(success)})", value=" ".join(success), inline=False)
    if errors:
        e.add_field(name=f"Echecs ({len(errors)})", value="\n".join(errors[:5]), inline=False)
    e.set_footer(text=f"Par {ctx.author}")
    await msg.edit(content=None, embed=e)

bot.run(TOKEN)
