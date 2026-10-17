import os
import gspread
import time
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

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
                break
            last_row_index -= 1
        
        first_empty_row = last_row_index + 1
        index = first_empty_row + self.new_records
        self.new_records = self.new_records + 1
        return index

    def get_records(self):
        return self.records

    def flush_updates_to_sheet(self):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                if self.update_queue:
                    try:
                        self.update_in_progress = True
                        updates = []
                
                        for (row,col) in self.update_queue.keys():
                            cell_id = gspread.utils.rowcol_to_a1(row, col + 1)
                            updates.append({'range': self.worksheet_name + "!" + cell_id, 'values': [[self.update_queue[(row, col)]]]})
                
                        self.update_queue.clear()
                        self.new_records = 0
                        self.sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": updates})
                    finally:
                        self.update_in_progress = False
                self.refresh_values()
            except APIError as e:
                if attempt == max_retries - 1:
                    print(f"Max retries ({max_retries}) reached. Raising error.")
                    raise e
                sleep(7)
            except Exception as e:
                # Fail immediately on non-API errors (e.g., SyntaxError, ValueError)
                raise e
