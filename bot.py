import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global queue list
queue = []

# ID of the dedicated channel where match logs and status updates go
# You will set this via the command inside Discord!
STATUS_CHANNEL_ID = None 

class MatchmakingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.green, custom_id="join_queue")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global STATUS_CHANNEL_ID
        player_id = interaction.user.id

        if player_id in queue:
            await interaction.response.send_message("❌ You are already in the queue!", ephemeral=True)
            return

        queue.append(player_id)
        
        # Pull the status updates channel object
        status_channel = bot.get_channel(STATUS_CHANNEL_ID) if STATUS_CHANNEL_ID else None

        if len(queue) >= 2:
            # Match is found!
            await interaction.response.send_message("🔄 Match found! Generating alert...", ephemeral=True)
            
            p1_id = queue.pop(0)
            p2_id = queue.pop(0)
            
            if status_channel:
                await status_channel.send(
                    f"⚔️ **Match Found!** <@{p1_id}> vs <@{p2_id}>. Go fight!"
                )
        else:
            # First person joined
            await interaction.response.send_message("✅ You have joined the queue.", ephemeral=True)
            if status_channel:
                await status_channel.send("👥 A player has entered the matchmaking queue! Waiting for an opponent... (1/2)")

    @discord.ui.button(label="Leave Queue", style=discord.ButtonStyle.red, custom_id="leave_queue")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global STATUS_CHANNEL_ID
        player_id = interaction.user.id

        if player_id not in queue:
            await interaction.response.send_message("❌ You aren't even in the queue!", ephemeral=True)
            return

        queue.remove(player_id)
        await interaction.response.send_message("👋 You have left the queue.", ephemeral=True)
        
        # Send an anonymous update that the queue is empty again
        status_channel = bot.get_channel(STATUS_CHANNEL_ID) if STATUS_CHANNEL_ID else None
        if status_channel:
            await status_channel.send("❌ The waiting player left the queue. (0/2)")

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_matchmaking(ctx, status_channel: discord.TextChannel):
    """
    Usage: !setup_matchmaking #match-updates
    Run this in the clean lobby channel, tagging the updates channel as a parameter.
    """
    global STATUS_CHANNEL_ID
    STATUS_CHANNEL_ID = status_channel.id
    
    embed = discord.Embed(
        title="🥊 1v1 Matchmaking Lobby", 
        description="Click the buttons below to manage your queue status. All pairing updates are posted in the logged updates channel.",
        color=discord.Color.dark_gray()
    )
    await ctx.send(embed=embed, view=MatchmakingView())

# --- THE FIX: Wrap the blocking command inside a function ---
def run_my_bot():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is missing!")
        return
    bot.run(token)
