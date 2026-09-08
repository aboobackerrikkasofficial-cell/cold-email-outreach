import csv
import os
import config
import message_writer

def run_backfill():
    csv_paths = [
        config.INDIA_LEADS_CSV,
        getattr(config, "INTERNATIONAL_CONTACTS_CSV", "data/international_contacts.csv")
    ]
    
    for csv_path in csv_paths:
        if not os.path.exists(csv_path):
            print(f"File not found: {csv_path}")
            continue

        # Read existing rows
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames

        # Ensure column exists in case this is run on an old file version
        if "whatsapp_message" not in fieldnames:
            fieldnames.append("whatsapp_message")

        total_rows = len(rows)
        # Identify how many need backfilling
        to_backfill = [
            i for i, r in enumerate(rows) 
            if not r.get("whatsapp_message") 
            or r.get("whatsapp_message").strip() == "-" 
            or r.get("whatsapp_message").strip() == ""
        ]
        
        print(f"Found {total_rows} total rows in {csv_path}.")
        print(f"{len(to_backfill)} rows are missing a WhatsApp message and will be generated.")
        print("-" * 40)

        count = 0
        for idx in to_backfill:
            count += 1
            row = rows[idx]
            business_name = row.get("business_name", "")
            print(f"Generating message {count}/{len(to_backfill)} in {os.path.basename(csv_path)}: {business_name}")

            # Reconstruct the lead dictionary expected by message_writer
            lead = {
                "name": business_name,
                "category": row.get("category", ""),
                "location": row.get("location", ""),
                "rating": row.get("rating", ""),
                "review_count": row.get("review_count", ""),
            }
            suggested_need = row.get("suggested_need", "")
            
            # Call the existing generation logic with a retry loop for network flakes
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    msg = message_writer.write_whatsapp_message(lead)
                    row["whatsapp_message"] = msg
                    break # Success, break out of retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        import time
                        print(f"  [!] Attempt {attempt+1} failed for {business_name}: {e}. Retrying in 3s...")
                        time.sleep(3)
                    else:
                        print(f"  [!] Failed for {business_name} after {max_retries} attempts: {e}")
                        row["whatsapp_message"] = ""
                
            # Write back to CSV on every loop to ensure progress is saved if stopped
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        print("-" * 40)
        print(f"Backfill complete for {csv_path}.\n")

if __name__ == "__main__":
    run_backfill()
