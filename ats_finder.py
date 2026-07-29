import json
import re
import concurrent.futures
import requests

COMPANIES = [
    "Google", "Microsoft", "Amazon", "Apple", "Meta", "Adobe", "Salesforce", "Oracle",
    "SAP Labs", "ServiceNow", "Atlassian", "VMware", "Cisco", "Intel", "NVIDIA",
    "Qualcomm", "AMD", "Broadcom", "IBM", "Dell Technologies", "HP", "LinkedIn",
    "Uber", "Airbnb", "Stripe", "PayPal", "Netflix", "Dropbox", "GitHub", "Cloudflare",
    "Databricks", "Snowflake", "MongoDB", "Confluent", "Elastic", "Twilio", "Okta",
    "Red Hat", "Nutanix", "Rubrik", "Cohesity", "Akamai", "Citrix", "Expedia",
    "Booking.com", "Autodesk", "Synopsys", "Cadence", "Siemens EDA", "MathWorks",
    "Arm", "Canonical", "Zoho", "Freshworks", "BrowserStack", "Postman", "Druva",
    "InMobi", "Hasura", "Whatfix", "Chargebee", "Kissflow", "Zoho Mail", "LeadSquared",
    "Gupshup", "HighRadius", "Innovaccer", "Wingify", "Profit.co", "Darwinbox",
    "Unacademy", "upGrad", "PhysicsWallah", "Razorpay", "PhonePe", "CRED", "Groww",
    "Jupiter", "Fi Money", "Open", "Pine Labs", "Zeta", "Slice", "BharatPe", "Cashfree",
    "Perfios", "M2P Fintech", "Jar", "Fyle", "Paytm", "CoinDCX", "CoinSwitch", "Zerodha",
    "Upstox", "Angel One", "PolicyBazaar", "Flipkart", "Meesho", "Myntra", "Ajio",
    "BigBasket", "Zepto", "Blinkit", "Nykaa", "FirstCry", "Pepperfry", "Lenskart",
    "Boat", "Purplle", "JioMart", "Swiggy", "Zomato", "Ola", "Rapido", "Porter",
    "Delhivery", "Dunzo", "Rebel Foods", "CleverTap", "MoEngage", "Capillary Technologies",
    "WebEngage", "Yellow.ai", "Haptik", "Sarvam AI", "Krutrim AI", "Fractal Analytics",
    "Quantiphi", "Mad Street Den", "Arya.ai", "SigTuple", "Observe.AI", "Dream11",
    "MPL", "Games24x7", "Nazara Technologies", "WinZO", "JioHotstar", "Pocket FM",
    "Practo", "PharmEasy", "1mg", "Healthify", "MediBuddy"
]

# Deduplicate
COMPANIES = sorted(list(set(COMPANIES)))

def get_slugs(name):
    # 'Sarvam AI' -> 'sarvamai', 'sarvam', 'sarvam-ai'
    base = name.lower()
    base = re.sub(r'[^a-z0-9\s-]', '', base)
    slug1 = base.replace(' ', '')
    slug2 = base.split()[0]
    slug3 = base.replace(' ', '-')
    
    slugs = [slug1]
    if slug2 not in slugs: slugs.append(slug2)
    if slug3 not in slugs: slugs.append(slug3)
    return slugs

def check_ats(name):
    slugs = get_slugs(name)
    session = requests.Session()
    
    for slug in slugs:
        # Greenhouse
        gh = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            r = session.get(gh, timeout=5)
            if r.status_code == 200 and 'jobs' in r.json():
                return {"name": name, "url": f"https://boards.greenhouse.io/{slug}", "type": "greenhouse"}
        except: pass
        
        # Lever
        lv = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            r = session.get(lv, timeout=5)
            if r.status_code == 200 and isinstance(r.json(), list):
                return {"name": name, "url": f"https://jobs.lever.co/{slug}", "type": "lever"}
        except: pass
        
        # Ashby
        ah = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        try:
            r = session.get(ah, timeout=5)
            if r.status_code == 200 and 'jobs' in r.json():
                return {"name": name, "url": f"https://jobs.ashbyhq.com/{slug}", "type": "ashby"}
        except: pass
    
    # Fallback to custom
    slug = slugs[0]
    return {"name": name, "url": f"https://careers.{slug}.com", "type": "custom"}

results = []
print(f"Checking ATS for {len(COMPANIES)} companies...")

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(check_ats, name): name for name in COMPANIES}
    for future in concurrent.futures.as_completed(futures):
        res = future.result()
        print(f"Resolved: {res['name']} -> {res['type']}")
        results.append(res)

with open('config/companies.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Saved config/companies.json!")
