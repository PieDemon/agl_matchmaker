import os
import gspread

# 1. Google Sheets Setup
SHEET_ID = "1BcSxlAv1vOdIXDdnivXHmfsP_tTnv0dzdb0fxCWN2FY"
STANDINGS_WORKSHEET_NAME = "Standings"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class CacheManager:
    def __init__(self, worksheet, columns):
        creds_json_string = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json_string:
            creds_data = json.loads(creds_json_string)
            creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        
        self.gc = gspread.authorize(creds)
        self.sh = self.gc.open_by_key(SHEET_ID)
        self.ws = self.sh.worksheet(worksheet)
        self.worksheet_id = self.ws.id
        self.max_columns = columns

        self.records = self.ws.get_all_values() #values allows row/column indexing
        self.new_records = 0
        
        self.update_queue = {} # {(row, col): value}

    def queue_change(self, row, col, value):
        self.update_queue[(row, col)] = value

    #get_all_values returns a list of list which can be indexed by row/column
    #get_all_records returns a list of dictionaries
    def refresh_values(self):
        self.records = self.ws.get_all_values()

    def new_row(self):
        index = len(self.records) + self.new_records
        self.new_records = self.new_records + 1
        return index

    def get_records(self):
        return self.records

    def flush_updates_to_sheet(self):
        if not self.update_queue:
            print("No pending updates to flush.")
            return
        
        # 1. Determine the absolute boundaries of our single rectangle
        all_rows = [row for (row, col) in self.update_queue.keys()]
        min_row = min(all_rows)
        max_row = max(all_rows)

        # 2. Build the grid of rows for this rectangle
        rows_payload = []
        
        # Loop sequentially through every single row from the top to bottom of our box
        for current_row in range(min_row, max_row + 1):
            # Create a blank row template filled with 10 empty cell dicts (skips by default)
            row_cells = [{} for _ in range(self.max_columns)]
            
            # Populate cells ONLY if we have an active queued update for this exact row
            for col in range(1, self.max_columns + 1):
                if (current_row, col) in self.update_queue:
                    value = self.update_queue[(current_row, col)]
                    if isinstance(value, str) and value.startswith('='):
                        val_type = "formulaValue"
                    elif isinstance(value, (int, float)):
                        val_type = "numberValue"
                    else:
                        val_type = "stringValue"
                    row_cells[col - 1] = {
                        "userEnteredValue": {
                            val_type: value
                        }
                    }
            
            # Add this row's array to our grid
            rows_payload.append({"values": row_cells})

        # 3. Construct exactly ONE updateCells block covering the whole bounding box
        single_rectangle_request = {
            "updateCells": {
                "range": {
                    "sheetId": self.worksheet_id,
                    "startRowIndex": min_row - 1,    # Inclusive start (0-indexed)
                    "endRowIndex": max_row,          # Exclusive end
                    "startColumnIndex": 0,           # Column A
                    "endColumnIndex": self.max_columns  # Column J
                },
                "rows": rows_payload,
                "fields": "userEnteredValue"         # Tells Google to ignore all the {} cells
            }
        }

        # 4. Ship the single request to the API
        print(f"Sending exactly 1 rectangular request covering rows {min_row} to {max_row}...")
        self.sh.batch_update({"requests": [single_rectangle_request]})
        
        self.update_queue.clear()
        self.refresh_values()
        self.new_records = 0
        print("Flush complete.")
