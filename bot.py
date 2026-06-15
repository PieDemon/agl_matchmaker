import discord
import os
from discord.ext import commands

# Initialize bot with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global list to track players in queue
queue = []

class MatchmakingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Keeps the button working indefinitely

    @discord.ui.button(label="Join 1v1 Queue", style=discord.ButtonStyle.green, custom_id="join_queue")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player_id = interaction.user.id
        player_name = interaction.user.mention

        # 1. Check if player is already in queue
        if player_id in queue:
            await interaction.response.send_message("You are already in the queue!", ephemeral=True)
            return

        # 2. Add player to queue
        queue.append(player_id)
        
        # 3. Check if a match is made
        if len(queue) >= 2:
            player1 = queue.pop(0)
            player2 = queue.pop(0)
            
            # Announce the match publicly
            await interaction.response.send_message(
                f"🎮 **Match Found!** <@{player1}> vs <@{player2}>. Get ready!",
                ephemeral=False
            )
        else:
            # Acknowledge joining without making a match yet
            await interaction.response.send_message(
                f"✅ {player_name} joined the queue! ({len(queue)}/2)",
                ephemeral=False
            )

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_matchmaking(ctx):
    """Sends the persistent matchmaking button message to a channel."""
    embed = discord.Embed(
        title="🥊 1v1 Matchmaking Lobby", 
        description="Click the button below to enter the pool. Matches launch automatically as soon as 2 players join.",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=MatchmakingView())

# Run the bot with your token
bot.run(os.environ.get("DISCORD_TOKEN"))
