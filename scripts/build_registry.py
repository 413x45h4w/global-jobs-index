#!/usr/bin/env python3
"""Build data/boards.yaml and data/boards.csv from verified seeds plus the catalog.

The catalog is the CC0 board directory in data/discovery/. Manual seeds are
boards this project checked against the vendor API. Lever is included in full
because that source is small. Workable and Recruitee are a verified-shaped
sample of non-staffing boards. Workday is a short list of employers whose
public CXS endpoint answered.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobdir.discover import load_catalog, parse_board_url  # noqa: E402
from jobdir.models import Board  # noqa: E402
from jobdir.yamlreg import dump_boards  # noqa: E402

CATALOG = ROOT / "data" / "discovery" / "cc0-board-directory.csv"
YAML_PATH = ROOT / "data" / "boards.yaml"
CSV_PATH = ROOT / "data" / "boards.csv"

# token, company, sector. Names were read from the public Greenhouse board endpoint.
GREENHOUSE = """
21shares	21shares	crypto
6sense	6sense	tech
a16z	a16z	crypto
adyen	Adyen	fintech
affirm	Affirm	fintech
airbnb	Airbnb	tech
airtable	Airtable	tech
akunacapital	Akuna Capital	trading
alpaca	Alpaca	fintech
andurilindustries	Anduril Industries	tech
anthropic	Anthropic	tech
aquaticcapitalmanagement	Aquatic Capital Management	trading
asana	Asana	tech
b2c2	B2C2	trading
betterment	Betterment	fintech
binance	Binance	crypto
bitgo	BitGo	crypto
bitmex	BitMEX	crypto
blend	Blend	fintech
block	Block	fintech
braze	Braze	tech
brex	Brex	fintech
bridgewater89	Bridgewater Associates	trading
bybit	Bybit	crypto
carta	Carta	fintech
cbinsights	CB Insights	tech
chicagotrading	Chicago Trading Company	trading
chime	Chime	fintech
cloudflare	Cloudflare	tech
cockroachlabs	Cockroach Labs	tech
coherehealth	Cohere Health	health
coinbase	Coinbase	crypto
copperco	Copper	crypto
coupang	Coupang	tech
current	Current	fintech
databricks	Databricks	tech
datadog	Datadog	tech
discord	Discord	tech
drivewealth	DriveWealth	fintech
dropbox	Dropbox	tech
drweng	DRW	trading
duolingo	Duolingo	tech
dvtrading	DV Trading	trading
elastic	Elastic	tech
engineersgate	Engineers Gate	trading
epicgames	Epic Games	tech
equityzen	EquityZen	fintech
exoduspoint	ExodusPoint	trading
faire	Faire	tech
falconx	FalconX	crypto
fanduel	FanDuel	markets
fastly	Fastly	tech
figma	Figma	tech
figment	Figment	crypto
figure	Figure	fintech
fireblocks	Fireblocks	crypto
fiveringsllc	Five Rings	trading
fivetran	Fivetran	tech
flexport	Flexport	tech
flowdesk	Flowdesk	trading
flowtraders	Flow Traders	trading
galaxydigitalservices	Galaxy Digital	crypto
galileo	Galileo	fintech
gemini	Gemini	crypto
genevatrading	Geneva Trading	trading
gitlab	GitLab	tech
godaddy	GoDaddy	tech
grayscaleinvestments	Grayscale	crypto
gusto	Gusto	fintech
headlandsresearch	Headlands Research	health
headlandstechnologiesllc	Headlands Technologies	trading
highnote	Highnote	fintech
imc	IMC	trading
instacart	Instacart	tech
janestreet	Jane Street	trading
jfrog	JFrog	tech
joinparadigm	Paradigm	crypto
jumpcrypto	Jump Crypto	crypto
jumptrading	Jump Trading	trading
justworks	Justworks	tech
kalshi	Kalshi	markets
lattice	Lattice	tech
launchdarkly	LaunchDarkly	tech
lithic	Lithic	fintech
lyft	Lyft	tech
mercury	Mercury	fintech
messari	Messari	crypto
mixpanel	Mixpanel	tech
mongodb	MongoDB	tech
monzo	Monzo	fintech
n26	N26	fintech
nasdaq	Nasdaq	markets
netlify	Netlify	tech
nubank	Nubank	fintech
okta	Okta	tech
okx	OKX	crypto
optiver	Optiver	trading
optiverus	Optiver	trading
pdtpartners	PDT Partners	trading
pinterest	Pinterest	tech
point72	Point72	trading
polychaincapital	Polychain Capital	crypto
proshares	ProShares	crypto
public	Public	fintech
pulley	Pulley	fintech
reddit	Reddit	tech
relativity	Relativity Space	tech
ripple	Ripple	crypto
robinhood	Robinhood	fintech
roblox	Roblox	tech
salesloft	Salesloft	tech
samsara	Samsara	tech
scaleai	Scale AI	tech
schonfeld	Schonfeld	trading
securitize	Securitize	crypto
sezzle	Sezzle	fintech
sofi	SoFi	fintech
spacex	SpaceX	tech
squarepointcapital	Squarepoint Capital	trading
squarespace	Squarespace	tech
stabilityai	Stability AI	tech
stripe	Stripe	fintech
sumup	SumUp	fintech
toast	Toast	tech
towerresearchcapital	Tower Research Capital	trading
transmarketgroup	TransMarket Group	trading
treasuryprime	Treasury Prime	fintech
twilio	Twilio	tech
upstart	Upstart	fintech
vercel	Vercel	tech
virtu	Virtu Financial	trading
webflow	Webflow	tech
worldquant	WorldQuant	trading
zscaler	Zscaler	tech
"""

ASHBY = """
airbyte	Airbyte	tech
alchemy	Alchemy	crypto
amplitude	Amplitude	tech
ashby	Ashby	tech
atomic	Atomic	fintech
baseten	Baseten	tech
binance.us	Binance.US	crypto
blockdaemon	Blockdaemon	crypto
cerebras	Cerebras Systems	tech
chainalysis-careers	Chainalysis	crypto
character	Character.AI	tech
circle	Circle	crypto
clerk	Clerk	tech
cohere	Cohere	tech
column	Column	fintech
consensys	Consensys	crypto
cursor	Cursor	tech
drivewealth	DriveWealth	fintech
dune	Dune	crypto
elevenlabs	ElevenLabs	tech
elliptic	Elliptic	crypto
freetrade	Freetrade	fintech
harvey	Harvey	tech
hex	Hex	tech
hightouch	Hightouch	tech
jane	Jane	tech
juicebox	Juicebox	tech
jump	Jump	other
kalshi	Kalshi	markets
lambda	Lambda	tech
ledger	Ledger	crypto
lightspeed	Lightspeed	tech
linear	Linear	tech
magiceden	Magic Eden	crypto
maven	Maven	tech
midjourney	Midjourney	tech
modal	Modal	tech
moderntreasury	Modern Treasury	fintech
mollie	Mollie	fintech
motherduck	MotherDuck	tech
neon	Neon	tech
notion	Notion	tech
nubank	Nubank	fintech
omni	Omni	tech
openai	OpenAI	tech
opensea	OpenSea	crypto
paradigm	Paradigm	crypto
paraform	Paraform	tech
paxos	Paxos	crypto
perplexity	Perplexity	tech
phantom	Phantom	crypto
physicalintelligence	Physical Intelligence	tech
pika	Pika	tech
plaid	Plaid	fintech
plain	Plain	tech
polymarket	Polymarket	markets
posthog	PostHog	tech
prefect	Prefect	tech
pylon	Pylon	tech
railway	Railway	tech
ramp	Ramp	fintech
render	Render	tech
replit	Replit	tech
resend	Resend	tech
runway	Runway	tech
safe	Safe Software	tech
sentry	Sentry	tech
sequoia	Sequoia	tech
smarkets	Smarkets	markets
snowflake	Snowflake	tech
supabase	Supabase	tech
tiger	Tiger	tech
trading212	Trading 212	fintech
uniswap	Uniswap	crypto
unit	Unit	fintech
vanta	Vanta	tech
ycombinator	Y Combinator	tech
"""

SMARTRECRUITERS = """
BoschGroup	Bosch Group	industrial
AbbVie	AbbVie	health
ServiceNow	ServiceNow	tech
Intuitive	Intuitive	health
DeliveryHero	Delivery Hero	tech
Continental	Continental	industrial
Sixt	SIXT	other
Grab	Grab	tech
Wise	Wise	fintech
KPN	KPN	tech
Palantir	Palantir	tech
Microchip	Microchip	tech
Thales	Thales	industrial
smartrecruiters	SmartRecruiters	tech
"""

WORKDAY = """
nvidia	NVIDIA	tech	nvidia.wd5.myworkdayjobs.com	nvidia	NVIDIAExternalCareerSite	https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
salesforce	Salesforce	tech	salesforce.wd12.myworkdayjobs.com	salesforce	External_Career_Site	https://salesforce.wd12.myworkdayjobs.com/External_Career_Site
adobe	Adobe	tech	adobe.wd5.myworkdayjobs.com	adobe	external_experienced	https://adobe.wd5.myworkdayjobs.com/external_experienced
cisco	Cisco	tech	cisco.wd5.myworkdayjobs.com	cisco	Cisco_Careers	https://cisco.wd5.myworkdayjobs.com/Cisco_Careers
intel	Intel	tech	intel.wd1.myworkdayjobs.com	intel	External	https://intel.wd1.myworkdayjobs.com/External
workday	Workday	tech	workday.wd5.myworkdayjobs.com	workday	Workday	https://workday.wd5.myworkdayjobs.com/Workday
"""

STAFFING = re.compile(
    r"staff|recruit|talent|hiring|outsourc|workforce|headhunt|volunteer|agency|job-board|jobsboard",
    re.I,
)


def parse_table(text: str, source: str) -> list[Board]:
    boards = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        token, company, sector = parts[0], parts[1].strip(), parts[2].strip()
        careers = ""
        extra = {}
        if source == "greenhouse":
            careers = f"https://job-boards.greenhouse.io/{token}"
        elif source == "ashby":
            careers = f"https://jobs.ashbyhq.com/{token}"
        elif source == "smartrecruiters":
            careers = f"https://jobs.smartrecruiters.com/{token}"
        elif source == "workday":
            extra = {
                "workday_host": parts[3],
                "workday_tenant": parts[4],
                "workday_site": parts[5],
            }
            careers = parts[6]
        boards.append(
            Board(
                company=company,
                source=source,
                board_id=token,
                sector=sector,
                careers_url=careers,
                **extra,
            )
        )
    return boards


def pretty_token(token: str) -> str:
    text = token.replace("-", " ").replace("_", " ").replace(".", " ")
    return " ".join(part.capitalize() for part in text.split())


def from_catalog(rows: list[dict], platform: str, *, limit: int | None, low: int, high: int, extras: set[str]) -> list[Board]:
    ranked = []
    forced = []
    for row in rows:
        if (row.get("platform") or "") != platform:
            continue
        try:
            count = int(row.get("open_roles") or 0)
        except ValueError:
            continue
        if count <= 0:
            continue
        token = row.get("token") or ""
        company = (row.get("company") or token).strip()
        if token in extras:
            forced.append(row)
            continue
        if limit is None:
            ranked.append((count, row))
            continue
        if not (low <= count <= high):
            continue
        if STAFFING.search(token) or STAFFING.search(company):
            continue
        ranked.append((count, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen = [row for _, row in ranked[:limit]] if limit is not None else [row for _, row in ranked]
    seen = {row.get("token") for row in chosen}
    for row in forced:
        if row.get("token") not in seen:
            chosen.append(row)
    boards = []
    for row in chosen:
        parsed = parse_board_url(row.get("api_url") or "") or parse_board_url(row.get("board_url") or "")
        if parsed is None:
            continue
        token = parsed.board_id
        parsed.company = pretty_token(row.get("company") or token)
        parsed.sector = guess_sector(parsed.company, parsed.board_id)
        parsed.careers_url = row.get("board_url") or parsed.careers_url
        parsed.expected_count = str(count)
        if platform == "lever":
            api = row.get("api_url") or ""
            if "api.eu.lever.co" in api:
                parsed.api_base = "https://api.eu.lever.co"
            elif "api.lever.co" in api:
                parsed.api_base = "https://api.lever.co"
        boards.append(parsed)
    return boards


def guess_sector(company: str, token: str) -> str:
    blob = f"{company} {token}".lower()
    rules = (
        ("markets", ("kalshi", "polymarket", "smarkets", "draftkings", "fanduel", "nasdaq", "cme group", "cboe")),
        ("trading", ("jane street", "jump trading", "optiver", "flow traders", "tower research", "akuna", "five rings", "point72", "worldquant", "drw", "virtu", "bridgewater", "pdt")),
        ("crypto", ("coinbase", "binance", "kraken", "gemini", "ripple", "fireblocks", "uniswap", "opensea", "chainalysis", "circle", "ledger")),
        ("fintech", ("stripe", "plaid", "robinhood", "chime", "sofi", "nubank", "wise", "adyen", "brex", "ramp", "block")),
        ("health", ("health", "pharma", "clinic", "hospital", "medical", "therapeut")),
    )
    for sector, keys in rules:
        if any(key in blob for key in keys):
            return sector
    return "other"


def main() -> None:
    rows = load_catalog(str(CATALOG))
    manual = []
    manual.extend(parse_table(GREENHOUSE, "greenhouse"))
    manual.extend(parse_table(ASHBY, "ashby"))
    manual.extend(parse_table(SMARTRECRUITERS, "smartrecruiters"))
    overrides = {board.key: board for board in manual}
    workday_names = {}
    for line in WORKDAY.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 6:
            continue
        _token, company, sector, _host, tenant, site = parts[:6]
        workday_names[f"{tenant}__{site}"] = (company, sector)
    boards = []
    for platform in ("greenhouse", "ashby", "lever", "workable", "recruitee", "workday", "personio", "rippling"):
        boards.extend(from_catalog(rows, platform, limit=None, low=1, high=10**9, extras=set()))
    for board in boards:
        override = overrides.get(board.key)
        if override:
            board.company = override.company
            board.sector = override.sector
        elif board.source == "workday" and board.board_id in workday_names:
            board.company, board.sector = workday_names[board.board_id]
    have = {board.key for board in boards}
    for board in manual:
        if board.key not in have:
            boards.append(board)
    deduped = []
    seen = set()
    for board in boards:
        if not board.board_id or board.key in seen:
            continue
        seen.add(board.key)
        deduped.append(board)
    deduped.sort(key=lambda board: (board.source, board.company.lower(), board.board_id.lower()))
    YAML_PATH.write_text(dump_boards(deduped), encoding="utf-8")
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "company",
                "source",
                "board_id",
                "sector",
                "careers_url",
                "api_base",
                "workday_host",
                "workday_tenant",
                "workday_site",
                "expected_count",
            ],
        )
        writer.writeheader()
        for board in deduped:
            writer.writerow({field: getattr(board, field) for field in writer.fieldnames})
    from collections import Counter

    print(f"wrote {len(deduped)} boards")
    print(Counter(board.source for board in deduped))


if __name__ == "__main__":
    main()
