import discord
from discord.ext import commands
import os
import gspread
from google.oauth2.service_account import Credentials

# 1. Google Sheets Setup
SHEET_ID = "1BcSxlAv1vOdIXDdnivXHmfsP_tTnv0dzdb0fxCWN2FY"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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

# 3. The Registration Modal (Phase 2)
class RegistrationModal(discord.ui.Modal, title="Complete Registration"):
    name_input = discord.ui.TextInput(
        label="Your Name & Tag",
        placeholder="Arthur R // bionicbunny#12345",
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )

    def __init__(self, selections):
        super().__init__()
        self.selections = selections  # Dictionary holding {'SOS': 'Yes'/'No', ...}

    async def on_submit(self, interaction: discord.Interaction):
        user_name = self.name_input.value
        
        # Count how many "Yes" choices they made
        yes_count = sum(1 for val in self.selections.values() if val == "Yes")
        
        if yes_count < 2:
            await interaction.response.send_message(
                f"❌ Registration failed. You must select **Yes** for at least 2 activities. (You selected {yes_count})",
                ephemeral=True
            )
            return

        # Prepare data row for Google Sheets
        # Format: [Discord Username, Custom Name Input, SOS, MSH, ECL, ATL]
        row_data = [
            str(interaction.user),
            user_name,
            self.selections.get("SOS", "No"),
            self.selections.get("MSH", "No"),
            self.selections.get("ECL", "No"),
            self.selections.get("ATL", "No")
        ]

        try:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
            gc = gspread.authorize(creds)
            sheet = gc.open_by_key(SHEET_ID).worksheet("Standings")
        except Exception as e:
            print(f"Error connecting to Google Sheets: {e}")

        try:
            sheet.append_row(row_data)
            await interaction.response.send_message(
                f"✅ Thank you, {user_name}! Your participation has been recorded in the spreadsheet.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ There was an error saving your data to the spreadsheet. Please contact an admin.",
                ephemeral=True
            )
            print(f"Sheet Write Error: {e}")

# 4. The Activity Dropdown Component
class ActivityDropdown(discord.ui.Select):
    def __init__(self, activity_name):
        self.activity_name = activity_name
        options = [
            discord.SelectOption(label="Yes", description=f"Participate in {activity_name}", emoji="✅"),
            discord.SelectOption(label="No", description=f"Skip {activity_name}", emoji="❌")
        ]
        super().__init__(
            placeholder=f"Participate in {activity_name}?", 
            min_values=1, 
            max_values=1, 
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # Save selection to the parent view state
        self.view.selections[self.activity_name] = self.values[0]
        # Defer interaction so the dropdown doesn't show "interaction failed"
        await interaction.response.defer()

# 5. The Parent View containing Dropdowns + Submit Button (Phase 1)
class ActivitySelectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent view
        self.selections = {"SOS": "No", "MSH": "No", "ECL": "No", "ATL": "No"}
        
        # Add the four dropdowns
        self.add_item(ActivityDropdown("SOS"))
        self.add_item(ActivityDropdown("MSH"))
        self.add_item(ActivityDropdown("ECL"))
        self.add_item(ActivityDropdown("ATL"))

    @discord.ui.button(label="Submit & Enter Name", style=discord.ButtonStyle.green, row=4)
    async def submit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Open the name modal and pass the selections down to it
        await interaction.response.send_modal(RegistrationModal(self.selections))

# 6. Command to deploy the interface
@bot.command()
@commands.has_permissions(administrator=True)
async def setup_signup(ctx):
    embed = discord.Embed(
        title="🌟 Tournament Activity Registration",
        description=(
            "Please select your participation status for the activities below.\n"
            "⚠️ **Requirement:** You must opt into **at least two (2)** activities.\n\n"
            "Once selections are made, click the green button to enter your name."
        ),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=ActivitySelectionView())

def run_my_bot():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is missing!")
        return
    bot.run(token)
