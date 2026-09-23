# README — Cookies_Vault Architecture
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Har campaign ka apna alag cookie folder hai.
# Jab Manager.py kisi campaign ke liye upload karega,
# toh woh is vault se us campaign ke cookies uthayega.
#
# HOW TO ADD A NEW CAMPAIGN:
# 1. Naya folder bana: Cookies_Vault/<Campaign_Name>/
# 2. Usme in 4 files daal (jo lagu hon):
#      - youtube_cookie.json
#      - tiktok_cookie.json
#      - ig_cookie.json
#      - whop_cookie.json
# 3. queue.txt mein us campaign ka naam use karo.
#    Manager automatically us folder ke cookies use karega!
#
# CURRENT CAMPAIGNS:
# ┌─────────────────────┬───────────────────────────────────┐
# │ Folder              │ Campaign Name in queue.txt        │
# ├─────────────────────┼───────────────────────────────────┤
# │ TJR_campaign/       │ TJR_trader, TJR_trader_new, etc.  │
# │ Double_Coverage/    │ Double_Coverage_Podcast           │
# └─────────────────────┴───────────────────────────────────┘
