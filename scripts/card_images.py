"""Build data/card_images.json (card id -> picture URL and artist) from ripperdeck.gg pages.

    bash scripts/fetch.sh ripperdeck_dl      # downloads the card pages, 2 s apart
    python scripts/card_images.py ripperdeck_dl/pages data/card_images.json

Only the links are kept in the repo, not the pictures. The play page fetches each
picture once and keeps it in .card_art/ on your machine (see scripts/play.py).
Card art belongs to CD PROJEKT RED / WeirdCo; it's used here for personal play only.
"""
import glob
import json
import os
import re
import sys

dec = json.JSONDecoder()


def rsc(h):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', h, re.S)
    return "".join(json.loads('"' + c + '"') for c in chunks)


def main(pages, out):
    found, errs = {}, []
    for f in sorted(glob.glob(os.path.join(pages, "*.html"))):
        slug = os.path.basename(f)[:-5]
        try:
            s = rsc(open(f, encoding="utf-8").read())
            i = s.find('"canonical":')
            obj, _ = dec.raw_decode(s, i + len('"canonical":'))
            if obj.get("image_url"):
                found[obj["id"]] = {"slug": slug, "url": obj["image_url"], "artist": obj.get("artist")}
            else:
                errs.append((slug, "no image_url"))
        except Exception as e:  # noqa: BLE001
            errs.append((slug, repr(e)))
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(found.items())), fh, indent=1, ensure_ascii=False)
    print(len(found), "pictures;", len(errs), "errors", errs[:5])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
