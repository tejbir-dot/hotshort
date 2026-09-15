import os
from viral_finder.groq_cortex import analyze_narrative_roles

os.environ["HS_GROQ_CORTEX_ENABLED"] = "1"
os.environ["HS_GROQ_NARRATIVE_ROLES"] = "1"

# We must have an API key in .env or environment.
# Let's see if we can load dotenv.
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

transcript = [
    {"text": "Did you know that 90% of startups fail?"},
    {"text": "The reason is not building a product."},
    {"text": "It's because they can't get customers."},
    {"text": "I tried building 5 apps last year."},
    {"text": "None of them worked until I learned marketing."},
    {"text": "So you have to learn distribution first."}
]

try:
    print(f"API Key present: {bool(os.environ.get('GROQ_API_KEY'))}")
    roles = analyze_narrative_roles(transcript)
    print("ROLES MAP:", roles)
except Exception as e:
    import traceback
    traceback.print_exc()
