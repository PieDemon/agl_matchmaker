import os
import gspread
import time
from google.oauth2.service_account import Credentials

# 1. Google Sheets Setup
SHEET_ID = "1BcSxlAv1vOdIXDdnivXHmfsP_tTnv0dzdb0fxCWN2FY"
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
        self.worksheet_name = worksheet
        self.ws = self.sh.worksheet(worksheet)
        self.worksheet_id = self.ws.id
        self.max_columns = columns
        self.records = self.ws.get_all_values() #values allows row/column indexing
        self.new_records = 0
        self.update_queue = {} # {(row, col): value}
        self.update_in_progress = False

    def queue_change(self, row, col, value):
        while(self.update_in_progress):
            time.sleep(1)
        #print(f"DEBUG: queueing change for row {row} col {col} value {value}")
        self.update_queue[(row, col)] = value

    #get_all_values returns a list of list which can be indexed by row/column
    #get_all_records returns a list of dictionaries
    def refresh_values(self):
        self.records = self.ws.get_all_values()

    def new_row(self):
        while(self.update_in_progress):
            time.sleep(1)

        last_row_index = len(self.records)
        for row in reversed(self.records):
            # Check if the row contains anything other than empty strings
            if any(cell.strip() for cell in row):
                index = 0
                for cell in row:
                    if cell.strip():
                        print(f"debug: nonempty cell in row {last_row_index} with contents |{cell}|")
                    index = index + 1
                break
            last_row_index -= 1
        
        first_empty_row = last_row_index + 1
        index = first_empty_row + self.new_records
        self.new_records = self.new_records + 1
        return index

    def get_records(self):
        return self.records

    def flush_updates_to_sheet(self):
        if not self.update_queue:
            print("No pending updates to flush.")
            return
        try:
            self.update_in_progress = True
    
            updates = []
    
            for (row,col) in self.update_queue.keys():
               # if row and col: #col = 0 caused this to be false
                cell_id = gspread.utils.rowcol_to_a1(row, col + 1)
                #print(f"DEBUG: pushing update for row {row} col {col} value {self.update_queue[(row, col)]} to cell {cell_id}")
                updates.append({'range': self.worksheet_name + "!" + cell_id, 'values': [[self.update_queue[(row, col)]]]})
    
            self.update_queue.clear()
            self.new_records = 0
            self.sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": updates})
            self.refresh_values()
        finally:
            self.update_in_progress = False
        print("Flush complete.")
