import discord
from discord.ext import commands
from datetime import datetime
import pandas as pd
import random
from cache_manager import CacheManager
import threading

# 1. Google Sheets Setup
SHEET_ID = "1BcSxlAv1vOdIXDdnivXHmfsP_tTnv0dzdb0fxCWN2FY"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

MATCHES_WORKSHEET_NAME = "Matches"
MATCHES_TOTAL_COLUMNS = 10 

matches_manager = CacheManager(
    worksheet=MATCHES_WORKSHEET_NAME,
    columns=MATCHES_TOTAL_COLUMNS
)

STANDINGS_WORKSHEET_NAME = "Standings"
STANDINGS_TOTAL_COLUMNS = 10 

standings_manager = CacheManager(
    worksheet=STANDINGS_WORKSHEET_NAME,
    columns=STANDINGS_TOTAL_COLUMNS
)

BUILDS_WORKSHEET_NAME = "Builds"
BUILDS_TOTAL_COLUMNS = 5 

builds_manager = CacheManager(
    worksheet=BUILDS_WORKSHEET_NAME,
    columns=BUILDS_TOTAL_COLUMNS
)

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

def already_played_build(player, build):
    try:
        records = matches_manager.get_records()
        headers = records[0]
        data = records[1:]
        df = pd.DataFrame(data, columns=headers)

        p1_name_col = "Player A"
        p2_name_col = "Player B"
        p1_pool_col = "A pool"
        p2_pool_col = "B pool"

        name_condition = (df[p1_name_col] == player) | (df[p2_name_col] == player)
        pool_condition = (df[p1_pool_col] == build) | (df[p2_pool_col] == build)
        
        matching_rows = df[name_condition & pool_condition]
        
        # 3. Check if *any* row matched the criteria
        return not matching_rows.empty
        
    except Exception as e:
        print(f"Error checking whether players have played: {e}")
        return None

def already_played(val1, val2):
    try:
        records = matches_manager.get_records()
        
        # If your columns have headers, use records[0] as columns, and records[1:] as data
        headers = records[0]
        data = records[1:]
        df = pd.DataFrame(data, columns=headers)
        
        col1_name = "Player A"
        col2_name = "Player B"
        
        exists = (((df[col1_name] == str(val1)) & (df[col2_name] == str(val2))).any() or ((df[col1_name] == str(val2)) & (df[col2_name] == str(val1))).any())
        
        return exists
    except Exception as e:
        print(f"Error checking whether players have played: {e}")
        return None

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
            # Determine column based on player position
            # A wins is Column 4 (D), B wins is Column 7 (G)
            col_num = 4 if self.is_player_a else 7
            matches_manager.queue_change(self.sheet_row, col_num, wins_reported)
            
            # Update end time column (Column 2 / B) to track when reporting finished
            end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            matches_manager.queue_change(self.sheet_row, 2, end_time)
            
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
        # Current timestamp format: 2026-09-14 16:54:22
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row_index = matches_manager.new_row()
        arp = f"=D{row_index}-SUMIF(Builds!B:B,E{row_index},Builds!E:E)"
        brp = f"=G{row_index}-SUMIF(Builds!B:B,H{row_index},Builds!E:E)"

        matches_manager.queue_change(row_index,0,start_time)      # Start time
        matches_manager.queue_change(row_index,2,p1_name)         # Player A
        matches_manager.queue_change(row_index,4,p1_matched_pool) # A pool
        matches_manager.queue_change(row_index,5,p2_name)         # Player B
        matches_manager.queue_change(row_index,7,p2_matched_pool) # B pool
        matches_manager.queue_change(row_index,8,arp)             # A formula
        matches_manager.queue_change(row_index,9,brp)             # B formula
        
        return row_index

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
        user_id_str = str(interaction.user.id)
        
        if any(row[0] == user_id_str for row in standings_manager.get_records() if len(row) > 1):
            return True  # User found!
        return False     # User not registered
        
    except Exception as e:
        print(f"Queue verification error: {e}")
        return False

async def get_user_activities(player_id: int) -> set:
    """Returns a set of activities (e.g., {'SOS', 'ECL'}) that the user selected 'Yes' for."""
    try:
        row_index = next((row_num for row_num, row in enumerate(data, start=1) 
                    if len(row) > 1 and row[1] == player_id), None)
        row_values = standings_manager.get_records()[row_index]
        
        # Assuming Columns layout: A=ID, B=Name, C=Input, D=FIN, E=EOE, F=TLA, G=FRA
        activities = ["FIN", "EOE", "TLA", "FRA"]
        user_yes_activities = set()
        
        for i, activity in enumerate(activities):
            # Safe check in case row_values is shorter than expected
            if len(row_values) > (3 + i) and row_values[3 + i] == "Yes":
                user_yes_activities.add(activity)
                
        return user_yes_activities
    except Exception as e:
        print(f"Error fetching user activities: {e}")
        return set()

async def get_paired_builds(p1, p2, activity_sets) -> tuple:
    """
    Finds a random pair of rows from the 'Builds' tab matching the given set.
    Returns a tuple of two links: (build_1_url, build_2_url).
    """
    try:
        # Fetch all rows from the sheet (skipping headers)
        all_rows = builds_manager.get_records()[1:]
        
        # Filter rows matching the desired set (Column C / index 2)
        matching_rows = []
        for row in all_rows:
            for activity_set in activity_sets:
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
            if(already_played_build(p1, matching_rows[i]) or already_played_build(p2, matching_rows[i])):
                continue
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

        try:
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
            
            for queued_player_id in queue:
                if already_played(player_id, queued_player_id):
                    continue
                
                opponent_activities = await get_user_activities(queued_player_id)
                shared_activities = player_activities & opponent_activities
                
                if shared_activities:
                    opponent_id = queued_player_id
                    # Grab the first matching activity name (e.g., 'SOS')
                    build_p1, build_p2 = await get_paired_builds(str(player_id), str(opponent_id), list(shared_activities))
                    break
        
            status_channel = bot.get_channel(STATUS_CHANNEL_ID) if STATUS_CHANNEL_ID else None
        
            # 6. Handle Matchmaking Results
            if opponent_id and build_p1 and build_p2: 
                queue.remove(opponent_id)
                await interaction.followup.send("🔄 Match found! Generating alerts and builds...", ephemeral=True)
                
                # Get users profiles to read their exact server display names
                opponent_user = await bot.fetch_user(opponent_id)
                p1_name = str(player_id)
                p2_name = str(opponent_id)
                
                # 📝 WRITE TO GOOGLE SHEETS & CAPTURE ROW ID
                match_row = await record_match_start(p1_name, p2_name, build_p1, build_p2)
                
                if status_channel:
                    await status_channel.send(
                        f"⚔️ **Match Found!** <@{player_id}> vs <@{opponent_id}>. Check your DMs for your custom builds!"
                    )
                    
                # Deliver Build + Score Dropdown to Player 1 (Player A)
                try:
                    p1_view = ScoreReportingView(sheet_row=match_row, is_player_a=True)
                    await interaction.user.send(
                        content=(
                            f"⚔️ Your match is ready!\n"
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
                            f"⚔️ Your match is ready!\n"
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
        finally:
            # 🔓 ALWAYS release the processing lock at the very end, regardless of success or failure
            if player_id in processing_players:
                processing_players.remove(player_id)
    
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
            await status_channel.send(f"❌ A waiting player left the queue. ({len(queue)} in queue)")

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
        row_index = standings_manager.new_row()
        standings_manager.queue_change(row_index,0,str(interaction.user.id))
        standings_manager.queue_change(row_index,1,interaction.user.display_name)
        standings_manager.queue_change(row_index,2,self.name_input.value)
        standings_manager.queue_change(row_index,3,self.selections.get("FIN", "No"))
        standings_manager.queue_change(row_index,4,self.selections.get("EOE", "No"))
        standings_manager.queue_change(row_index,5,self.selections.get("TLA", "No"))
        standings_manager.queue_change(row_index,6,self.selections.get("FRA", "No"))
        standings_manager.queue_change(row_index,7,f"=SUMIF(Matches!C:C, A{row_index}, Matches!D:D)+SUMIF(Matches!F:F, A{row_index}, Matches!G:G)")
        standings_manager.queue_change(row_index,8,f"=SUMIF(Matches!C:C, A{row_index}, Matches!I:I)+SUMIF(Matches!F:F, A{row_index}, Matches!J:J)")
        standings_manager.queue_change(row_index,9,f"=COUNTIF(Matches!C:C, A{row_index})+COUNTIF(Matches!F:F, A{row_index})")

        await interaction.response.send_message(
            f"✅ Thank you, {user_name}! Your participation has been recorded in the spreadsheet.",
            ephemeral=True
        )

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
        self.selections = {"FIN": "No", "EOE": "No", "TLA": "No", "FRA": "No"}
        
        # Add the four dropdowns
        self.add_item(ActivityDropdown("FIN"))
        self.add_item(ActivityDropdown("EOE"))
        self.add_item(ActivityDropdown("TLA"))
        self.add_item(ActivityDropdown("FRA"))

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

def standings_loop():
    while(true):
        standings_manager.flush_updates_to_sheet()
        standings_manager.refresh_values()
        sleep(10)

def matches_loop():
    while(true):
        matches_manager.flush_updates_to_sheet()
        matches_manager.refresh_values()
        sleep(30)

def run_my_bot():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN environment variable is missing!")
        return
    
    print("Starting standings refresher thread")
    standings_thread = threading.Thread(target=standings_loop, daemon=True)
    standings_thread.start()    
    
    print("Starting matches refresher thread")
    matches_thread = threading.Thread(target=matches_loop, daemon=True)
    matches_thread.start()    
    
    print("Refreshing builds")
    builds_manager.refresh_values()

    print("Running bot")
    bot.run(token)
