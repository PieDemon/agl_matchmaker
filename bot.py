import discord
from discord.ext import commands
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

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
processing_players = set()

# ID of the dedicated channel where match logs and status updates go
# You will set this via the command inside Discord!
STATUS_CHANNEL_ID = None 

class ScoreDropdown(discord.ui.Select):
    def __init__(self, sheet_row: int, is_player_a: bool):
        self.sheet_row = sheet_row
        self.is_player_a = is_player_a  # True if they are Player A, False if Player B
        
        options = [
            discord.SelectOption(label="0 Wins", value="0", description="I won 0 games"),
            discord.SelectOption(label="1 Win", value="1", description="I won 1 game"),
            discord.SelectOption(label="2 Wins", value="2", description="I won 2 games"),
            discord.SelectOption(label="3 Wins", value="3", description="I won 3 games"),
        ]
        super().__init__(placeholder="Select your total game wins...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wins_reported = self.values[0]
        
        try:
            creds_json_string = os.environ.get("GOOGLE_CREDENTIALS_JSON")
            if creds_json_string:
                creds_data = json.loads(creds_json_string)
                creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
            else:
                creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
            
            gc = gspread.authorize(creds)
            sheet = gc.open_by_key(SHEET_ID).worksheet("Matches")
            
            # Determine column based on player position
            # A wins is Column 4 (D), B wins is Column 7 (G)
            col_num = 4 if self.is_player_a else 7
            sheet.update_cell(self.sheet_row, col_num, wins_reported)
            
            # Update end time column (Column 2 / B) to track when reporting finished
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.update_cell(self.sheet_row, 2, end_time)
            
            # Disable dropdown after selection so they can't double-submit
            self.disabled = True
            await interaction.edit_original_response(
                content=f"✅ **Results Submitted!** Your score of **{wins_reported} wins** has been logged.",
                view=self.view
            )
            
        except Exception as e:
            print(f"Error submitting scores: {e}")
            await interaction.followup.send("❌ An error occurred while writing your score to the spreadsheet.", ephemeral=True)

class ScoreReportingView(discord.ui.View):
    def __init__(self, sheet_row: int, is_player_a: bool):
        super().__init__(timeout=None) # Keeps the buttons functional indefinitely
        self.add_item(ScoreDropdown(sheet_row, is_player_a))

async def record_match_start(p1_name: str, p2_name: str, p1_matched_pool: str, p2_matched_pool: str) -> int:
    """Inserts a new match record into the 'Matches' sheet and returns its row number."""
    try:
        creds_json_string = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json_string:
            creds_data = json.loads(creds_json_string)
            creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).worksheet("Matches")
        
        # Current timestamp format: 2026-09-14 16:54:22
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Columns: Start time, End time, Player A, A wins, A pool, Player B, B wins, B pool
        # Leave "End time", "A wins", and "B wins" blank initially
        row_data = [
            start_time,   # Start time
            "",           # End time (Pending)
            p1_name,      # Player A
            "",           # A wins (Pending)
            p1_matched_pool, # A pool
            p2_name,      # Player B
            "",           # B wins (Pending)
            p2_matched_pool  # B pool
        ]
        
        # Append the row and get the row index
        result = sheet.append_row(row_data)
        
        # Parse out the updated range to extract the exact row number
        # gspread returns a dictionary where updates['updatedRange'] looks like "Matches!A15:H15"
        updated_range = result.get('updates', {}).get('updatedRange', '')
        row_num = int(''.join(filter(str.isdigit, updated_range.split(':')[-1])))
        return row_num

    except Exception as e:
        print(f"Error recording match start: {e}")
        return None
        
async def can_dm_user(user_id: int) -> bool:
    """Attempts to create a DM channel with a user to verify if their settings allow it."""
    try:
        user = await bot.fetch_user(user_id)
        # Creating a DM channel does not send a message, but fails if DMs are blocked
        await user.create_dm()
        return True
    except discord.Forbidden:
        return False
    except Exception:
        return False

async def check_if_registered(interaction: discord.Interaction) -> bool:
    """Helper function to verify if a user's Discord ID exists in Column A."""
    try:
        # Re-authorize to prevent token timeout issues
        creds_json_string = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json_string:
            creds_data = json.loads(creds_json_string)
            creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).worksheet("Standings")
        
        # 🎯 Look for the user's ID string strictly in Column 1
        user_id_str = str(interaction.user.id)
        cell = sheet.find(user_id_str, in_column=1)
        
        if cell:
            return True  # User found!
        return False     # User not registered
        
    except Exception as e:
        print(f"Queue verification error: {e}")
        return False

async def get_user_activities(player_id: int) -> set:
    """Returns a set of activities (e.g., {'SOS', 'ECL'}) that the user selected 'Yes' for."""
    try:
        # Standard re-authorization block
        creds_json_string = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json_string:
            creds_data = json.loads(creds_json_string)
            creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).worksheet("Standings")
        
        # Find the user's row
        cell = sheet.find(str(player_id), in_column=1)
        if not cell:
            return set()
            
        row_values = sheet.row_values(cell.row)
        # Assuming Columns layout: A=ID, B=Name, C=Input, D=SOS, E=MSH, F=ECL, G=TLA
        # index 3=SOS, 4=MSH, 5=ECL, 6=TLA
        activities = ["SOS", "MSH", "ECL", "TLA"]
        user_yes_activities = set()
        
        for i, activity in enumerate(activities):
            # Safe check in case row_values is shorter than expected
            if len(row_values) > (3 + i) and row_values[3 + i] == "Yes":
                user_yes_activities.add(activity)
                
        return user_yes_activities
    except Exception as e:
        print(f"Error fetching user activities: {e}")
        return set()

import random

async def get_paired_builds(activity_set: str) -> tuple:
    """
    Finds a random pair of rows from the 'Builds' tab matching the given set.
    Returns a tuple of two links: (build_1_url, build_2_url).
    """
    try:
        # Standard re-authorization block
        creds_json_string = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json_string:
            creds_data = json.loads(creds_json_string)
            creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(SHEET_ID).worksheet("Builds")
        
        # Fetch all rows from the sheet (skipping headers)
        all_rows = sheet.get_all_values()[1:]
        
        # Filter rows matching the desired set (Column C / index 2)
        matching_rows = []
        for row in all_rows:
            if len(row) >= 3 and row[2].strip().upper() == activity_set.upper():
                # We want the 'Build' link which is in Column B (index 1)
                matching_rows.append(row[1])
        
        # Ensure we have at least one complete pair (2 rows)
        if len(matching_rows) < 2:
            print(f"Warning: Not enough builds found for set '{activity_set}'. Found {len(matching_rows)}")
            return None, None
            
        # Group adjacent matching rows into explicit pairs
        # (e.g. index 0 & 1 is Pair 1, index 2 & 3 is Pair 2)
        pairs = []
        for i in range(0, len(matching_rows) - 1, 2):
            pairs.append((matching_rows[i], matching_rows[i+1]))
            
        if not pairs:
            return None, None
            
        # Select one pair at random
        selected_pair = random.choice(pairs)
        return selected_pair
        
    except Exception as e:
        print(f"Error fetching paired builds: {e}")
        return None, None

class MatchmakingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Join Queue", style=discord.ButtonStyle.green, custom_id="join_queue")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        global STATUS_CHANNEL_ID
        await interaction.response.defer(ephemeral=True)
        
        player_id = interaction.user.id

        # 🚨 LOCK 1: Is the bot currently processing an active click from this user?
        if player_id in processing_players:
            # Respond instantly WITHOUT deferring to save performance
            await interaction.response.send_message("⏳ Please wait, your request is already being processed!", ephemeral=True)
            return
    
        # 🚨 LOCK 2: Are they already safely waiting inside the queue?
        if player_id in queue:
            await interaction.response.send_message("❌ You are already in the queue!", ephemeral=True)
            return
    
        # Activate the optimistic lock instantly before deferring
        processing_players.add(player_id)
            
        is_registered = await check_if_registered(interaction)
        if not is_registered:
            await interaction.followup.send(
                "⚠️ **Access Denied:** You must complete your **Tournament Registration** before you can join the queue!",
                ephemeral=True
            )
            return
    
        # 🚨 3. DM Security Check: Are their DMs open right now?
        dms_are_open = await can_dm_user(player_id)
        if not dms_are_open:
            # Disallow them from joining and alert them ephemerally
            await interaction.followup.send(
                "❌ **Queue Entry Denied:** The bot could not establish a Direct Message connection with you.", 
                ephemeral=True
            )
            
            # Publicly warn them in the server channel so they know how to fix it
            if status_channel:
                await status_channel.send(
                    f"⚠️ <@{player_id}> tried to join the matchmaking queue but has **Direct Messages closed**! "
                    f"Please update your Discord Privacy Settings to allow server DMs so the bot can send you builds."
                )
            return  # Stop execution here; they are NOT added to the queue array
        
        player_activities = await get_user_activities(player_id)
        if not player_activities:
            await interaction.followup.send("⚠️ **Error:** Could not retrieve your activity choices.", ephemeral=True)
            return
    
        # Matchmaking loop
        opponent_id = None
        matched_set = None
        
        for queued_player_id in queue:
            opponent_activities = await get_user_activities(queued_player_id)
            shared_activities = player_activities & opponent_activities
            
            if shared_activities:
                opponent_id = queued_player_id
                # Grab the first matching activity name (e.g., 'SOS')
                matched_set = list(shared_activities)[0]
                break
    
        status_channel = bot.get_channel(STATUS_CHANNEL_ID) if STATUS_CHANNEL_ID else None
    
        # 6. Handle Matchmaking Results
        if opponent_id and matched_set:
            queue.remove(opponent_id)
            await interaction.followup.send("🔄 Match found! Generating alerts and builds...", ephemeral=True)
            
            # Fetch the build data
            build_p1, build_p2 = await get_paired_builds(matched_set)
            
            # Get users profiles to read their exact server display names
            opponent_user = await bot.fetch_user(opponent_id)
            p1_name = interaction.user.display_name
            p2_name = opponent_user.display_name
            
            # 📝 WRITE TO GOOGLE SHEETS & CAPTURE ROW ID
            match_row = await record_match_start(p1_name, p2_name, build_p1, build_p2)
            
            if status_channel:
                await status_channel.send(
                    f"⚔️ **Match Found ({matched_set})!** <@{player_id}> vs <@{opponent_id}>. Check your DMs for your custom builds!"
                )
                
            # Deliver Build + Score Dropdown to Player 1 (Player A)
            try:
                p1_view = ScoreReportingView(sheet_row=match_row, is_player_a=True)
                await interaction.user.send(
                    content=(
                        f"⚔️ Your match is ready for the set **{matched_set}**!\n"
                        f"🔗 **Your Build Link:** {build_p1 if build_p1 else 'No link found'}\n\n"
                        f"🏆 **Report Results:** Once you finish playing all 3 games, select your total wins using the dropdown below:"
                    ),
                    view=p1_view
                )
            except Exception as e:
                print(f"Failed DM to Player 1: {e}")
                
            # Deliver Build + Score Dropdown to Player 2 (Player B)
            try:
                p2_view = ScoreReportingView(sheet_row=match_row, is_player_a=False)
                await opponent_user.send(
                    content=(
                        f"⚔️ Your match is ready for the set **{matched_set}**!\n"
                        f"🔗 **Your Build Link:** {build_p2 if build_p2 else 'No link found'}\n\n"
                        f"🏆 **Report Results:** Once you finish playing all 3 games, select your total wins using the dropdown below:"
                    ),
                    view=p2_view
                )
            except Exception as e:
                print(f"Failed DM to Player 2: {e}")
        else:
            # No match found, join queue normally
            queue.append(player_id)
            await interaction.followup.send("✅ You have joined the queue.", ephemeral=True)
            if status_channel:
                await status_channel.send(f"👥 A player has entered the matchmaking queue! Waiting for an opponent... ({len(queue)} in queue)")

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
        # Format: [Discord Username, Custom Name Input, SOS, MSH, ECL, TLA]
        row_data = [
            str(interaction.user.id),
            interaction.user.display_name,
            user_name,
            self.selections.get("SOS", "No"),
            self.selections.get("MSH", "No"),
            self.selections.get("ECL", "No"),
            self.selections.get("TLA", "No")
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
        self.selections = {"SOS": "No", "MSH": "No", "ECL": "No", "TLA": "No"}
        
        # Add the four dropdowns
        self.add_item(ActivityDropdown("SOS"))
        self.add_item(ActivityDropdown("MSH"))
        self.add_item(ActivityDropdown("ECL"))
        self.add_item(ActivityDropdown("TLA"))

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
