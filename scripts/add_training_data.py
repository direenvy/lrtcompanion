"""
Appends 80 new labelled examples to train_labeled.csv, focused on
underrepresented classes: breakdown (was 17), positive (was 1), crowding (was 3).
"""
import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAIN_CSV = PROJECT_ROOT / "data" / "nlp" / "final" / "train_labeled.csv"

NEW_EXAMPLES = [
    # ── BREAKDOWN (negative) — was only 17, adding 28 more ─────────────────
    ("Kelana Jaya line breakdown at KLCC, stuck 40 mins!", "negative", "breakdown"),
    ("LRT broke down between Masjid Jamek and Dang Wangi, no movement for 30 minutes", "negative", "breakdown"),
    ("MRT Kajang line faulty train at Bukit Dukung, passengers stranded on platform", "negative", "breakdown"),
    ("Train fault at Ampang Park station, all services suspended both directions", "negative", "breakdown"),
    ("Kelana Jaya line malfunction near Taman Jaya, stuck inside train for 45 mins", "negative", "breakdown"),
    ("Total breakdown on KJ line, signal failure at Universiti station causing massive delay", "negative", "breakdown"),
    ("LRT stopped working at Bangsar station, doors won't open, we are stuck inside", "negative", "breakdown"),
    ("Rapid KL train broke down at Asia Jaya station, no announcement from staff at all", "negative", "breakdown"),
    ("Sri Petaling line fault again, train halted between Bukit Jalil and Awan Besar", "negative", "breakdown"),
    ("KJ line faulty track switch near Taman Bahagia, service completely halted", "negative", "breakdown"),
    ("LRT train broken down between two stations, no movement for over an hour now", "negative", "breakdown"),
    ("Ampang line train malfunction, stranded at Dato Keramat station for 50 minutes", "negative", "breakdown"),
    ("MRT Putrajaya train fault at Kwasa Damansara, stuck on platform cannot board", "negative", "breakdown"),
    ("Train engine failure on KJ line, all trains cancelled from Kelana Jaya to KLCC", "negative", "breakdown"),
    ("LRT breakdown again at Taman Paramount, this is the 3rd time this month", "negative", "breakdown"),
    ("Signal system failure Kelana Jaya line, single track operation causing huge delays", "negative", "breakdown"),
    ("Rapid KL complete service suspension due to train fault, no ETA given at all", "negative", "breakdown"),
    ("Train door malfunction at Putra Heights, cannot close, whole line disrupted", "negative", "breakdown"),
    ("KJ line train broke down at peak hour, platform dangerously overcrowded now", "negative", "breakdown"),
    ("Monorail breakdown at Bukit Nanas, stranded for 1 hour no alternative bus provided", "negative", "breakdown"),
    ("Kajang MRT line train fault near Serdang, 2 trains cancelled, platform packed", "negative", "breakdown"),
    ("LRT faulty train removed from service, causing 15 minute gaps between trains", "negative", "breakdown"),
    ("Rapid KL breakdown alert Ampang line, passengers asked to leave train at Cempaka", "negative", "breakdown"),
    ("Train at Dang Wangi station broken, waiting on platform 35 mins already ridiculous", "negative", "breakdown"),
    ("KJ LRT train stopped mid-journey between Taman Jaya and Asia Jaya, no explanation", "negative", "breakdown"),
    ("Overhead equipment failure causing LRT service disruption on Kelana Jaya line", "negative", "breakdown"),
    ("Train fault during peak hour KL Sentral MRT, hundreds stranded missing meetings", "negative", "breakdown"),
    ("Power failure at Masjid Jamek station, all platforms closed LRT completely down", "negative", "breakdown"),

    # ── DELAY (negative) — adding 15 more with clear language ───────────────
    ("LRT delayed 20 minutes at KLCC station, no announcement from staff whatsoever", "negative", "delay"),
    ("Kelana Jaya line severely delayed, waited 4 trains before I could board", "negative", "delay"),
    ("KJ line headway 15 minutes during peak hour, platform packed like sardines", "negative", "delay"),
    ("MRT Kajang delayed every morning this week, hopeless service", "negative", "delay"),
    ("Train late again from Putra Heights, made me late for work third time this month", "negative", "delay"),
    ("Ampang line running 25 minutes behind schedule, no updates from Rapid KL", "negative", "delay"),
    ("Sri Petaling line delayed because of earlier breakdown, passengers overflowing", "negative", "delay"),
    ("LRT waiting time 18 minutes at Bangsar station, unacceptable during rush hour", "negative", "delay"),
    ("Rapid KL always delayed at peak hours, paying RM150 My50 for this terrible service", "negative", "delay"),
    ("Train gaps more than 12 minutes on KJ line, platform overcrowded and dangerous", "negative", "delay"),
    ("Monorail delay 30 minutes Bukit Bintang station, hundreds of people waiting outside", "negative", "delay"),
    ("MRT delayed from Kwasa Damansara, been waiting 20 minutes no train in sight", "negative", "delay"),
    ("Kelana Jaya line slow service, 5 trains passed full cannot board, late for exam", "negative", "delay"),
    ("LRT running at reduced frequency due to earlier incident, expect longer waiting times", "negative", "delay"),
    ("BRT Sunway severely delayed this morning, bus 40 minutes late not acceptable", "negative", "delay"),

    # ── CROWDING (negative) — was only 3, adding 15 more ───────────────────
    ("KLCC LRT platform dangerously overcrowded, people pushing to get on train", "negative", "crowding"),
    ("Can't board at KL Sentral again, 4 trains passed all completely packed", "negative", "crowding"),
    ("Kelana Jaya line morning rush hour unbearable, sardine conditions every day", "negative", "crowding"),
    ("Masjid Jamek interchange so crowded I nearly fainted, need more trains please", "negative", "crowding"),
    ("MRT Kajang platform at Bukit Bintang overflowing, safety hazard during peak hour", "negative", "crowding"),
    ("Rapid KL train packed beyond capacity, could not breathe inside the coach", "negative", "crowding"),
    ("Platform so full at Dang Wangi during lunch hour, waited 3 trains to board", "negative", "crowding"),
    ("Ampang line train way too crowded, passengers hanging at doors cannot close properly", "negative", "crowding"),
    ("KL Sentral during peak hour is a nightmare, trains all full nobody can board", "negative", "crowding"),
    ("Too many people on the LRT platform at Bangsar, this is a safety issue", "negative", "crowding"),
    ("Sri Petaling line sardine packed every morning, need bigger trains urgently", "negative", "crowding"),
    ("Monorail always full during lunch hour, cannot board for 4 consecutive trains", "negative", "crowding"),
    ("After the breakdown everyone rushing same trains, extreme overcrowding at KLCC now", "negative", "crowding"),
    ("Putrajaya MRT line dangerously overcrowded at Pavilion station, very uncomfortable", "negative", "crowding"),
    ("Weekend service too infrequent causing massive crowding, Rapid KL please add trains", "negative", "crowding"),

    # ── POSITIVE (positive) — was only 1, adding 15 more ──────────────────
    ("Great service on KJ line today, trains on time and not too crowded", "positive", "other"),
    ("Rapid KL staff at KL Sentral very helpful today, assisted elderly passenger", "positive", "staff_service"),
    ("LRT running smoothly this morning, arrived on time feeling good", "positive", "other"),
    ("MRT Kajang service excellent today, air cond working great and punctual", "positive", "other"),
    ("Kelana Jaya line perfectly on schedule today, impressed with the improvement", "positive", "other"),
    ("Really appreciate Rapid KL installing more benches at Masjid Jamek station", "positive", "other"),
    ("Train arrived exactly on time today, no delays or issues, thank you Rapid KL", "positive", "other"),
    ("New Putrajaya MRT line very comfortable and fast, great addition to KL transit", "positive", "other"),
    ("LRT staff very professional handling the crowd today, well done Rapid KL", "positive", "staff_service"),
    ("Smooth ride from Putra Heights to KLCC today, trains clean and comfortable", "positive", "other"),
    ("Rapid KL finally fixed the air con at Bangsar station, much more comfortable now", "positive", "other"),
    ("Impressed by how quickly Rapid KL resumed service after the earlier disruption", "positive", "other"),
    ("My50 pass is great value, using LRT every day saving a lot on travel costs", "positive", "information"),
    ("Train service much improved this month, keep it up Rapid KL", "positive", "other"),
    ("Kudos to Rapid KL for adding extra trains during the concert event at Stadium Merdeka", "positive", "other"),

    # ── NEUTRAL / INFORMATION — adding 7 to keep balance ──────────────────
    ("Rapid KL announces temporary single track operation on KJ line this weekend", "neutral", "information"),
    ("My50 pass monthly renewal now available at all LRT MRT Monorail stations", "neutral", "information"),
    ("Rapid KL scheduled maintenance work on Ampang line this Sunday 11pm to 5am", "neutral", "information"),
    ("New fare structure for LRT MRT Monorail effective next month check website", "neutral", "information"),
    ("Rapid KL adds 2 new stations on Putrajaya MRT line opening next quarter", "neutral", "information"),
    ("Touch n Go card required for all LRT MRT Monorail and BRT services in Klang Valley", "neutral", "information"),
    ("Rapid KL free shuttle bus service available during LRT maintenance works this weekend", "neutral", "information"),
]

def main():
    # Read existing data
    with open(TRAIN_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"Existing rows: {len(rows)}")

    # Find max sample number
    existing_ids = [r["sample_id"] for r in rows if r["sample_id"].startswith("S")]
    max_num = max(int(s[1:]) for s in existing_ids if s[1:].isdigit())

    # Build new rows
    new_rows = []
    for i, (text, sentiment, issue_type) in enumerate(NEW_EXAMPLES):
        sample_id = f"S{max_num + i + 1:03d}"
        row = {k: "" for k in fieldnames}
        row["sample_id"]    = sample_id
        row["cleaned_text"] = text
        row["sentiment"]    = sentiment
        row["issue_type"]   = issue_type
        row["relevance"]    = "relevant"
        row["lang"]         = "en"
        row["source_dataset"] = "synthetic_augmentation"
        row["notes"]        = "added_for_retraining"
        new_rows.append(row)

    # Append to CSV
    with open(TRAIN_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerows(new_rows)

    print(f"Added {len(new_rows)} new examples.")
    print(f"Total rows now: {len(rows) + len(new_rows)}")

    # Show new distribution
    all_rows = rows + new_rows
    from collections import Counter
    print("\nNew sentiment distribution:", dict(Counter(r["sentiment"] for r in all_rows)))
    print("New issue_type distribution:", dict(Counter(r["issue_type"] for r in all_rows)))


if __name__ == "__main__":
    main()
