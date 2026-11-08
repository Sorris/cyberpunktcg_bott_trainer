import re, sys, json, os, glob
pages, out = sys.argv[1], sys.argv[2]
dec = json.JSONDecoder()
KEEP = ["id","name","card_type","color","ram_cost","ram_provided","eddie_cost","power","has_sell_tag",
        "street_cred_requirement","classification","keywords","triggers","has_spend_ability","ability_text",
        "flavor_text","set_code","set_name","card_number","rarity","version","legality","updated_at","base_card_id"]
def rsc(h):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', h, re.S)
    return ''.join(json.loads('"'+c+'"') for c in chunks)
def rulings(s):
    i = s.find('"Official rulings"')
    if i < 0: return []
    seg = s[i:i+60000]
    end = re.search(r'"children":"(Printings|Decks|Prices|Price history|Appears in)', seg)
    if end: seg = seg[:end.start()]
    qs = []
    for m in re.finditer(r'\["\$","h3",null,\{"className":"[^"]*","children":(".*?")\}\],\["\$","p",null,\{"className":"[^"]*","children":(".*?")\}\]', seg):
        qs.append({"q": json.loads(m.group(1)), "a": json.loads(m.group(2))})
    return qs
cards, errs = [], []
for f in sorted(glob.glob(os.path.join(pages, '*.html'))):
    slug = os.path.basename(f)[:-5]
    try:
        s = rsc(open(f, encoding='utf-8').read())
        i = s.find('"canonical":')
        obj, _ = dec.raw_decode(s, i + len('"canonical":'))
        c = {k: obj.get(k) for k in KEEP}
        c["slug"] = slug
        c["rulings"] = rulings(s)
        cards.append(c)
    except Exception as e:
        errs.append((slug, repr(e)))
json.dump(cards, open(out, 'w'), indent=1, ensure_ascii=False)
print(len(cards), "cards;", len(errs), "errors", errs[:5])
