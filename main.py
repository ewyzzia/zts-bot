import discord
import asyncio
import ctypes
import time
import io
import nacl.secret
import nacl.utils
import os
from discord.ext import commands
from discord import app_commands, opus
from discord.app_commands import Choice
from google.cloud import texttospeech
import re
import json
import bcp47
from pydub import AudioSegment
import math

intents = discord.Intents.all()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("$"),
    description='yeah',
    intents=intents,
)

cloud_tts_client = texttospeech.TextToSpeechClient()
raw_voices = cloud_tts_client.list_voices()
cloud_tts_voices = {voice.name: True for voice in raw_voices.voices}

raw_substitutions = {
    "brb": "be right back",
    "gtg": "gotta go",
    "wtf": "what the fuck",
    "wth": "what the heck",
    "mfw": "my face when",
    "ai": "A I",
    "wpm": "words per minute",
    "yk": "you know",
    "mfw": "my face when",
    "lmao": "lemao",
    "lmfao": "lemfao",
    ":3": ", meow? ",
    ":3c": ", meow? ", 
    "e+?r+?h+?m+?": "errrrrrm,",
    "imo": "in my opinion",
    "btw": "by the way",
    "nvm": "nevermind",
    "stfu": "shut the fuck up",
    "irl": "in real life",
    "ez": "easy",
    "ngl": "not gonna lie",
    "ikr": "i know right",
    "idk": "i don't know",
    "idc": "i don't care",
    "idgaf": "i don't give a fuck",
    "tw": "trigger warning",
    "tf": "the fuck",
    "fym": "fuck you mean",
    "cya": "see ya",
    "ily": "i love you",
    "lmk": "let me know",
    "omg": "oh my god",
    "omw": "on my way",
    "tbh": "to be honest",
    "stg": "swear to god",
    "ykw": "you know what",
    "hw": "homework",
    "ofc": "of course",
    "ragequit": "rage quit",
    "cesar": "caesar",
    "cezar": "caesar",
    "api": "A P I",
    "jfc": "jesus fucking christ",
    "mf": "motherfucker",
    "mfs": "em eff's",
    "idfk": "i don't fucking know",
    "yw": "you're welcome",
    "dnc": "do not care",
    "rn": "right now",
    "af": "as fuck",
    "asf": "as fuck",
    "asl": "as hell",
    "fr": "for real",
    "dms": "DM's",
    "wdym": "what do you mean",
}

ssml_substitutions = {
    '"': "&quot;",
    "'": "&apos;",
    "<": "&lt;",
    ">": "&gt;"
}

substitutions = {}
for original, substitute in raw_substitutions.items():
    key = f'''(^|[' "])({original})($|[' ",.?!;:*/])'''
    if type(substitute) == str:
        substitutions[key] = r"\1" + substitute + r"\3"
    
default_user_settings = {
    "lang": "en-US",
    "voice": "en-US-Wavenet-A",
    "speed": 1.0,
    "pitch": 1.0,
    "voice_enabled": True,
    "mute_next_message": False
}
settings = None
if os.path.exists(os.path.join(os.getcwd(), "settings.json")):
    print("cool! we got settings")
    with open("settings.json", "r") as f:
        settings = json.load(f)
else:
    settings = {
        "guilds": {}
    }

def get_sfx_list():
    sounds = [filename[0:-4] for filename in os.listdir(os.path.join(os.getcwd(), "sfx"))]
    return sounds

def save_settings():
    with open("settings.json", "w") as f:
        json.dump(settings, f)

def get_user_setting(user: discord.User, setting):
    if not setting in default_user_settings:
        raise Exception("Attempt to get a per-user setting that doesn't exist")
    uid = str(user.id)
    if uid in settings and setting in settings[uid]:
        return settings[uid][setting]
    else:
        return default_user_settings[setting]
    
def set_user_setting(user: discord.User, setting: str, value: str):
    
    if not setting in default_user_settings:
        raise Exception("Attempt to set a per-user setting that doesn't exist")
    uid = str(user.id)
    if not uid in settings:
        settings[uid] = {}
    try:
        if setting == "lang" and value not in bcp47.tags:
            return -1
        if setting == "voice" and value not in cloud_tts_voices:
            return -1

        settings[uid][setting] = type(default_user_settings[setting])(value)
        save_settings()
        return 0
    except (TypeError, ValueError) as e:
        print("Attempt to set a setting to an invalid value")
    return -1

source_queues = {} # indexed by voice client
async def queuedSourcesPlayer():
    while True:
        markedForRemoval = []
        for voice_client, queue in source_queues.items():
            if not voice_client.is_connected():
                print("you're going down buddy")
                markedForRemoval.append(voice_client)
                continue
            if not voice_client.is_playing() and len(queue) > 0:
                voice_client.play(queue.pop(0))
        for voice_client in markedForRemoval:
            print(voice_client)
            voice_client.stop()
            del source_queues[voice_client]
            print(voice_client in source_queues)
        await asyncio.sleep(0.05)

def add_source_to_queue(voice_client: discord.VoiceClient, source: discord.AudioSource):
    if voice_client not in source_queues:
        source_queues[voice_client] = []
    source_queues[voice_client].append(source)

def get_voice_client_in_guild(id):
    for client_to_check in bot.voice_clients:
        if client_to_check.guild.id == id:
            return client_to_check
    return None

def deEmojify(text):
    regrex_pattern = re.compile(pattern = "["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                           "]+", flags = re.UNICODE)
    return regrex_pattern.sub(r'',text)

def read_message(message, voice_client):
    try:
        user_speed = get_user_setting(message.author, "speed")
        user_pitch = get_user_setting(message.author, "pitch")

        readable_text = message.content.lower()
        for original, substitute2 in substitutions.items():
            readable_text = re.sub(original, substitute2, readable_text)
        readable_text = re.sub("<a?:.+?:\d+?>", ".", readable_text)
        readable_text = re.sub("<@(\d+?)>", lambda match: "at " + message.guild.get_member(int(match.group(1))).display_name, readable_text)
        readable_text = re.sub("(\?!|!\?|[.?!;:])[.?!;:]+", r"\1", readable_text)
        readable_text = re.sub("https?://.+?( |$)", ", a link, ", readable_text)
        readable_text = deEmojify(readable_text)
        if re.sub("[^A-Za-z0-9]", "", readable_text) == "":
            print("No readable text")
            return
        
        def repeated_chars(match):
            word = match.group(2)
            print(word)
            repeated_chars = re.findall(r'(([a-zA-Z])\2\2+)', word)
            word_without_repetition = re.sub(r'([a-zA-Z])\1\1+', r"\1", word)
            repetition_amnt = 0
            for chars in repeated_chars:
                repetition_amnt += len(chars[0])
            print(repetition_amnt)
            if repetition_amnt >= 3:
                return fr'{match.group(1)}<prosody rate="{str(round(user_speed * (1/math.pow(repetition_amnt, 1/2.8)) * 100))}%" pitch="{str(round(user_pitch * 100 - 100))}%">{word_without_repetition}</prosody>'
            else:
                return match.group(0)

        # SSML conversion
        readable_text = re.sub("&", "&amp;", readable_text)
        for original, substitute in ssml_substitutions.items():
            readable_text = re.sub(original, substitute, readable_text)
        print(readable_text)
        readable_text = re.sub(r'''(^|&amp;|&quot;| )([a-zA-Z&;]+)''', repeated_chars, readable_text)
        print(readable_text)
        readable_text = re.sub(r"(^| )\*(.+?)\*($| )", fr'\1<prosody rate="{round(user_speed * 0.6 * 100)}%" range="x-high" pitch="{round(user_pitch * 1.125 * 100 - 100)}%">\2</prosody>\3', readable_text)
        readable_text = re.sub(r"(^| )_(.+?)_($| )", fr'\1<prosody rate="{round(user_speed * 0.6 * 100)}%" range="x-high" pitch="{round(user_pitch * 0.875 * 100 - 100)}%">\2</prosody>\3', readable_text)
        readable_text = re.sub(r"(^| )~~(.+?)~~($| )", fr'\1<prosody volume="soft" range="x-low" pitch={str(round(user_speed * 100))} rate="{round(user_speed * 1.5 * 100)}%">\2</prosody>\3', readable_text)
        readable_text = re.sub(r"(^|</prosody>)(.+?)($|<prosody)", fr'\1<prosody rate="{round(user_speed * 100)}%" pitch="{round(user_pitch * 100 - 100)}%">\2</prosody>\3', readable_text)
        
        print(readable_text)
        readable_text = f'<speak>{readable_text}</speak>'
        print(readable_text)

        synthesis_input = texttospeech.SynthesisInput(ssml=readable_text)
        voice_params = texttospeech.VoiceSelectionParams(
            language_code=get_user_setting(message.author, "lang"), name=get_user_setting(message.author, "voice")
        ) 
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.OGG_OPUS
        )
        response = cloud_tts_client.synthesize_speech(
            input=synthesis_input, voice=voice_params, audio_config=audio_config
        )
        with open("temp.ogg", "wb") as out:
            out.write(response.audio_content)

        audio = AudioSegment.from_ogg("temp.ogg")
        audio = audio + 5
        audio.export("temp.ogg")
        
        add_source_to_queue(voice_client, discord.FFmpegOpusAudio("temp.ogg"))
    except Exception as e: 
        print(e)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    print("Ready")
    print('------')

@bot.event
async def on_voice_state_update(member: discord.Member, before, after):
    client = get_voice_client_in_guild(member.guild.id)
    if client and len(client.channel.members) == 1:
        await client.disconnect()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if not message.author.voice:
        return

    is_message_muted = get_user_setting(message.author, "mute_next_message")
    set_user_setting(message.author, "mute_next_message", False)
    if is_message_muted:
        return

    if message.content.startswith('hi'):
        await message.channel.send('pikmin')

    target_channel = settings["guilds"][str(message.guild.id)]["channel"] if str(message.guild.id) in settings["guilds"] and "channel" in settings["guilds"][str(message.guild.id)] else None

    if message.content == "~!off":
        set_user_setting(message.author, "voice_enabled", False)
        return
    
    if message.content == "~!on":
        set_user_setting(message.author, "voice_enabled", True)
        return

    voice_client = get_voice_client_in_guild(message.guild.id)
    if (voice_client and not message.content.startswith("~!") and get_user_setting(message.author, "voice_enabled") == True):

        inCorrectVoiceChannel = voice_client.channel.id == message.author.voice.channel.id
        inCorrectTextChannel = target_channel and str(message.channel.id) == target_channel or not target_channel

        if not (inCorrectVoiceChannel and inCorrectTextChannel):
            return
        
        read_message(message, voice_client)
    await bot.process_commands(message) 

@bot.command()
async def sync_tree(ctx):
    await ctx.send("syncing")
    await bot.tree.sync()
    await ctx.send("done")

@bot.tree.command()
async def leave(interaction: discord.Interaction):
    client = get_voice_client_in_guild(interaction.guild.id)
    if client and client.is_connected():
        await client.disconnect()
        await interaction.response.send_message(f"bye")
    else:
        await interaction.response.send_message(f"what")

@bot.tree.command()
async def join(interaction: discord.Interaction):
    channel = interaction.user.voice.channel
    if (channel != None):
        client = get_voice_client_in_guild(interaction.guild.id)
        if client:
            await client.disconnect()
        else:
            print("no client cool")
        try:
            await channel.connect()
        except err:
            print(err)
        await interaction.response.send_message(f"hi")
    else:
        await interaction.response.send_message(f"not in a channel dummy")

@bot.tree.command()
async def set_channel(interaction: discord.Interaction, channel: str):
    gid = str(interaction.guild_id)
    guild_settings = settings["guilds"][gid] if gid in settings["guilds"] else {}
    guild_settings["channel"] = channel
    settings["guilds"][gid] = guild_settings
    save_settings()
    await interaction.response.send_message(f"ok")

@bot.tree.command()
async def remove_channel(interaction: discord.Interaction, channel: str):
    gid = str(interaction.guild_id)
    guild_settings = settings["guilds"][gid] if gid in settings["guilds"] else {}
    del guild_settings["channel"]
    settings["guilds"][gid] = guild_settings
    save_settings()
    await interaction.response.send_message(f"ok")

@bot.tree.command()
async def list_sfx(interaction: discord.Interaction, effect: str):
    str = ""
    for sfx in get_sfx_list():
        str += sfx + "\n"
    await interaction.response.send_message(str, ephemeral=True)

@bot.tree.command()
async def voice_toggle(interaction: discord.Interaction):
    set_user_setting(interaction.user, "voice_enabled", not get_user_setting(interaction.user, "voice_enabled"))
    await interaction.response.send_message("ok", ephemeral=True)

@bot.tree.command()
async def voice_on(interaction: discord.Interaction):
    set_user_setting(interaction.user, "voice_enabled", True)
    await interaction.response.send_message("ok", ephemeral=True)

@bot.tree.command()
async def voice_off(interaction: discord.Interaction):
    set_user_setting(interaction.user, "voice_enabled", False)
    await interaction.response.send_message("ok", ephemeral=True)

@bot.tree.command()
async def sfx(interaction: discord.Interaction, sound: str):
    
    if not sound in get_sfx_list():
        return
    voice_client = get_voice_client_in_guild(interaction.guild_id)
    if voice_client:
        print(sound)
        add_source_to_queue(voice_client, discord.FFmpegPCMAudio("sfx/" + sound + ".mp3"))
    await interaction.response.send_message(f"ok", ephemeral=True, delete_after=2)

@bot.tree.command()
async def set_setting(interaction: discord.Interaction, setting: str, value: str):
    
    setting_response = set_user_setting(interaction.user, setting, value)
    if setting_response == 0:
        await interaction.response.send_message(f"set you setting {setting} to {value}")
    else:
        await interaction.response.send_message(f"bad value stupid")

@bot.tree.command(description="Prevents the next message sent from being read")
async def mute_next(interaction: discord.Interaction):
    set_user_setting(interaction.user, "mute_next_message", True)
    await interaction.response.send_message(f"ok", ephemeral=True, delete_after=1)

@app_commands.context_menu(name="Read Message")
async def read_cmd(interaction: discord.Interaction, message: discord.Message):
    if (message.author.id != interaction.user.id):
        await interaction.response.send_message(f"you can only read your own messages", ephemeral=True, delete_after=5)
        return

    voice_client = get_voice_client_in_guild(message.guild.id)
    if (not voice_client):
        await interaction.response.send_message(f"bot isn't in vc", ephemeral=True, delete_after=5)
        return

    inCorrectVoiceChannel = message.author.voice and voice_client.channel.id == message.author.voice.channel.id

    if (not inCorrectVoiceChannel):
        await interaction.response.send_message(f"you're not in vc", ephemeral=True, delete_after=5)
        return
        
    read_message(message, voice_client)
    await interaction.response.send_message(f"ok", ephemeral=True, delete_after=5)

bot.tree.add_command(read_cmd)

async def main():
    opus.load_opus(ctypes.util.find_library("opus"))
    loop =  asyncio.get_event_loop()
    loop.create_task(queuedSourcesPlayer())
    await bot.start('bot token here')

asyncio.run(main())
