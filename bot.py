import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

queue = []

class MatchmakingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join 1v1 Queue", style=discord.ButtonStyle.green, custom_id="join_queue")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player_id = interaction.user.id

        # 1. Check if player is already in queue
        if player_id in queue:
            await interaction.response.send_message("❌ You are already in the queue!", ephemeral=True)
            return

        # 2. Add player to queue
        queue.append(player_id)
        
        # 3. Check if a match is made
        if len(queue) >= 2:
            # Acknowledge the button click instantly to prevent Discord timeout errors
            await interaction.response.send_message("🔄 Match found! Sending DMs...", ephemeral=True)
            
            p1_id = queue.pop(0)
            p2_id = queue.pop(0)
            
            # Fetch user objects to send DMs
            player1 = await bot.fetch_user(p1_id)
            player2 = await bot.fetch_user(p2_id)
            
            # Send DM to Player 1
            try:
                await player1.send(f"🎮 **Match Found!** You are playing against **{player2.name}**. Good luck!")
            except discord.Forbidden:
                print(f"Could not DM {player1.name}. DMs might be closed.")
                
            # Send DM to Player 2
            try:
                await player2.send(f"🎮 **Match Found!** You are playing against **{player1.name}**. Good luck!")
            except discord.Forbidden:
                print(f"Could not DM {player2.name}. DMs might be closed.")
        else:
            # Tell the player they joined, but make it hidden from everyone else
            await interaction.response.send_message(
                f"✅ You joined the queue! Current players waiting: {len(queue)}/2", 
                ephemeral=True
            )

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_matchmaking(ctx):
    embed = discord.Embed(
        title="🥊 1v1 Matchmaking", 
        description="Click the button below to enter the queue. Matches are handled entirely via private DMs.",
        color=discord.Color.purple()
    )
    await ctx.send(embed=embed, view=MatchmakingView())

# --- THE FIX: Wrap the blocking command inside a function ---
def run_my_bot():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is missing!")
        return
    bot.run(token)
