#!/usr/bin/env python3
"""
Export WaniKani's radical/kanji/vocabulary curriculum into a standalone
Anki deck (.apkg). Run once — the resulting file has no further connection
to your WaniKani account or token.

Usage:
    1. Paste your token into the TOKEN variable right below these imports.
    2. Run: python3 anki.py
"""

import sys
import time
import html
import requests
import genanki

# ---- Paste your WaniKani API token between the quotes below ----
TOKEN = "Your WaniKani API token"
# ------------------------------------------------------------------

API_BASE = "https://api.wanikani.com/v2"


def get_token():
    if not TOKEN or TOKEN == "your-token-here":
        sys.exit("Please paste your WaniKani API token into the TOKEN variable near the top of this script.")
    return TOKEN


def fetch_all_subjects(token):
    """Fetch every radical/kanji/vocabulary subject, following pagination."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_BASE}/subjects"
    params = {"types": "radical,kanji,vocabulary"}
    subjects = []

    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code == 401:
            sys.exit("Invalid API token. Double-check it in WaniKani > Settings > API Tokens.")
        resp.raise_for_status()
        data = resp.json()

        subjects.extend(data["data"])
        print(f"  fetched {len(subjects)} subjects so far...")

        url = data["pages"].get("next_url")
        params = None  # next_url already includes query params
        time.sleep(0.3)  # be polite to the API

    return subjects


def primary_meaning(obj):
    for m in obj.get("meanings", []):
        if m.get("primary"):
            return m["meaning"]
    return obj.get("meanings", [{}])[0].get("meaning", "")


def all_meanings(obj):
    return ", ".join(m["meaning"] for m in obj.get("meanings", []))


def primary_readings(obj, reading_key="readings"):
    readings = obj.get(reading_key) or []
    primaries = [r["reading"] for r in readings if r.get("primary")]
    if primaries:
        return ", ".join(primaries)
    return ", ".join(r["reading"] for r in readings)


def readings_by_type(obj, reading_type):
    """Kanji readings carry an onyomi/kunyomi/nanori tag; vocabulary readings don't."""
    readings = obj.get("readings") or []
    matches = [r["reading"] for r in readings if r.get("type") == reading_type]
    return ", ".join(matches)


def canonical_and_alternates(items, text_key):
    """Some kanji/vocab have more than one WaniKani-accepted answer (e.g. a word
    with two valid readings). Anki's type-in-answer only compares against a single
    stored value, so we pick one canonical answer plus a separate list of other
    accepted answers; a small script on the card treats typing any of them as correct.

    `items` is a WaniKani meanings or readings list; each entry may have `primary`
    and `accepted_answer` flags. For readings, alternates are restricted to the same
    onyomi/kunyomi type as the canonical one, so a reading quiz never accepts an
    answer of the wrong reading type.
    """
    if not items:
        return "", ""

    primary = next((i for i in items if i.get("primary")), items[0])
    canonical = primary[text_key]
    same_type = primary.get("type")  # None for vocabulary/meanings, onyomi/kunyomi for kanji

    seen = {canonical}
    alternates = []
    for item in items:
        if not item.get("accepted_answer", True):
            continue
        if same_type is not None and item.get("type") != same_type:
            continue
        value = item[text_key]
        if value not in seen:
            seen.add(value)
            alternates.append(value)

    return canonical, ", ".join(alternates)


def clean_mnemonic(text):
    if not text:
        return ""
    # WaniKani wraps key terms in custom tags like <radical>, <kanji>, <vocabulary>, <reading>
    import re
    text = re.sub(r"</?(radical|kanji|vocabulary|reading|meaning|ja)>", "", text)
    return html.escape(text).replace("\n", "<br>")


def build_note(subject, model, position):
    obj = subject["data"]
    stype = subject["object"]  # 'radical', 'kanji', or 'vocabulary'
    level = str(obj.get("level", ""))

    characters = obj.get("characters")
    if not characters and stype == "radical":
        # Some radicals have no Unicode character at all — fall back to showing the meaning
        characters = f"[{primary_meaning(obj)}]"

    meanings = all_meanings(obj)
    meaning_answer, meaning_alternates = canonical_and_alternates(obj.get("meanings") or [], "meaning")
    # Stored lowercase so the case-forcing script on the front template (which lowercases
    # whatever you type) always matches, regardless of how you capitalize your answer.
    meaning_answer = meaning_answer.lower()
    meaning_alternates = meaning_alternates.lower()
    meaning_mnemonic = clean_mnemonic(obj.get("meaning_mnemonic", ""))

    onyomi = ""
    kunyomi = ""
    nanori = ""

    if stype == "radical":
        readings = ""
        reading_answer = ""
        reading_alternates = ""
        reading_mnemonic = ""
    elif stype == "kanji":
        # One Reading card, testing WaniKani's actual primary reading (same as WaniKani
        # itself quizzes) — onyomi/kunyomi/nanori are still shown on the back for reference.
        readings = ""
        reading_answer, reading_alternates = canonical_and_alternates(obj.get("readings") or [], "reading")
        reading_mnemonic = clean_mnemonic(obj.get("reading_mnemonic", ""))
        onyomi = readings_by_type(obj, "onyomi")
        kunyomi = readings_by_type(obj, "kunyomi")
        nanori = readings_by_type(obj, "nanori")
    else:  # vocabulary — no onyomi/kunyomi distinction, just plain readings
        readings = primary_readings(obj, "readings")
        reading_answer, reading_alternates = canonical_and_alternates(obj.get("readings") or [], "reading")
        reading_mnemonic = clean_mnemonic(obj.get("reading_mnemonic", ""))

    return genanki.Note(
        model=model,
        fields=[
            characters, meanings, readings, meaning_mnemonic, reading_mnemonic,
            meaning_answer, reading_answer, stype, level, onyomi, kunyomi, nanori,
            meaning_alternates, reading_alternates,
        ],
        tags=[f"level{level}", stype],
        # Without an explicit position, every card defaults to the same internal
        # value and Anki has no real ordering to sort by — it falls back to
        # grouping by card type (all Meaning cards, then all Reading cards)
        # regardless of your Display Order setting. Giving each item its own
        # increasing position makes a note's Meaning and Reading card sit
        # immediately next to each other, item by item.
        due=position,
    )


def main():
    token = get_token()

    print("Fetching subjects from WaniKani API...")
    subjects = fetch_all_subjects(token)
    print(f"Done. Fetched {len(subjects)} total subjects.")

    model = genanki.Model(
        1607392319,  # fixed model id
        "WaniKani Export",
        fields=[
            {"name": "Characters"},
            {"name": "Meanings"},
            {"name": "Readings"},
            {"name": "MeaningMnemonic"},
            {"name": "ReadingMnemonic"},
            {"name": "MeaningAnswer"},
            {"name": "ReadingAnswer"},
            {"name": "Type"},
            {"name": "Level"},
            {"name": "Onyomi"},
            {"name": "Kunyomi"},
            {"name": "Nanori"},
            {"name": "MeaningAlternates"},
            {"name": "ReadingAlternates"},
        ],
        templates=[
            {
                # Generated for every subject: radicals, kanji, and vocabulary all have a meaning.
                "name": "Meaning",
                "qfmt": '''
                    <div style="font-size:48px;text-align:center;">{{Characters}}</div>
                    <div style="text-align:center;color:#888;">{{Type}} · Level {{Level}} — Meaning?</div>
                    <div style="text-align:center;margin-top:16px;">{{type:MeaningAnswer}}</div>
                    <script>
                      (function () {
                        var inp = document.getElementById("typeans");
                        if (!inp) return;
                        // Force whatever is typed to lowercase, so capitalization never
                        // affects whether the answer is marked correct.
                        inp.addEventListener("input", function () {
                          var pos = this.selectionStart;
                          this.value = this.value.toLowerCase();
                          this.setSelectionRange(pos, pos);
                        });
                        // Some items have more than one accepted meaning. If what you
                        // typed exactly matches one of those alternates, silently swap
                        // it to the canonical answer so it's still marked correct.
                        var alternates = "{{MeaningAlternates}}".split(",").map(function (s) {
                          return s.trim();
                        }).filter(Boolean);
                        var canonical = "{{MeaningAnswer}}";
                        function maybeSwap() {
                          if (alternates.indexOf(inp.value.trim()) !== -1) {
                            inp.value = canonical;
                          }
                        }
                        inp.addEventListener("keydown", function (e) {
                          if (e.key === "Enter") maybeSwap();
                        });
                        inp.addEventListener("blur", maybeSwap);
                      })();
                    </script>
                ''',
                "afmt": '''{{FrontSide}}<hr id="answer">
                <div style="text-align:center;">
                  <b>{{Meanings}}</b><br>
                  {{#Readings}}<div>{{Readings}}</div>{{/Readings}}
                  <hr>
                  <div style="text-align:left;font-size:14px;">
                    {{#MeaningMnemonic}}<p><b>Meaning:</b> {{MeaningMnemonic}}</p>{{/MeaningMnemonic}}
                  </div>
                </div>''',
            },
            {
                # Generated for kanji and vocabulary only. The whole prompt is wrapped in
                # {{#ReadingAnswer}}...{{/ReadingAnswer}} — a genuinely empty section for
                # radicals — so the export tool can correctly detect ReadingAnswer as a
                # required field and skip this card for them. (Plain {{type:Field}} alone
                # isn't enough: the tool that builds this file doesn't recognize Anki's
                # special type: syntax when deciding whether a card should exist at all,
                # so without this wrapper it was generating an empty Reading card for
                # every radical too.)
                "name": "Reading",
                "qfmt": '''{{#ReadingAnswer}}
                    <div style="font-size:48px;text-align:center;">{{Characters}}</div>
                    <div style="text-align:center;color:#888;">{{Type}} · Level {{Level}} — Reading?</div>
                    <div style="text-align:center;margin-top:16px;">{{type:ReadingAnswer}}</div>
                    <script>
                      (function () {
                        var inp = document.getElementById("typeans");
                        if (!inp) return;
                        // Some kanji/vocab have more than one accepted reading. If what
                        // you typed exactly matches one of those alternates, silently
                        // swap it to the canonical answer so it's still marked correct.
                        var alternates = "{{ReadingAlternates}}".split(",").map(function (s) {
                          return s.trim();
                        }).filter(Boolean);
                        var canonical = "{{ReadingAnswer}}";
                        function maybeSwap() {
                          if (alternates.indexOf(inp.value.trim()) !== -1) {
                            inp.value = canonical;
                          }
                        }
                        inp.addEventListener("keydown", function (e) {
                          if (e.key === "Enter") maybeSwap();
                        });
                        inp.addEventListener("blur", maybeSwap);
                      })();
                    </script>
                    {{/ReadingAnswer}}''',
                "afmt": '''{{FrontSide}}<hr id="answer">
                <div style="text-align:center;">
                  {{#Onyomi}}<div><b>On'yomi:</b> {{Onyomi}}</div>{{/Onyomi}}
                  {{#Kunyomi}}<div><b>Kun'yomi:</b> {{Kunyomi}}</div>{{/Kunyomi}}
                  {{#Nanori}}<div><b>Nanori:</b> {{Nanori}}</div>{{/Nanori}}
                  {{^Onyomi}}{{^Kunyomi}}<div><b>{{Readings}}</b></div>{{/Kunyomi}}{{/Onyomi}}
                  <div>{{Meanings}}</div>
                  <hr>
                  <div style="text-align:left;font-size:14px;">
                    {{#ReadingMnemonic}}<p><b>Reading:</b> {{ReadingMnemonic}}</p>{{/ReadingMnemonic}}
                  </div>
                </div>''',
            },
        ],
    )

    deck = genanki.Deck(1691234567, "WaniKani (Full Export)")

    # The API returns all radicals first, then all kanji, then all vocabulary
    # (across every level). Sort by level first, then type within each level,
    # so Anki's new-card queue introduces them the way WaniKani actually does
    # (radicals, kanji, vocab, level by level) instead of all 60 levels of
    # radicals before a single kanji shows up.
    type_order = {"radical": 0, "kanji": 1, "vocabulary": 2}
    subjects.sort(key=lambda s: (s["data"].get("level") or 9999, type_order.get(s["object"], 9)))

    position = 1
    for subject in subjects:
        if subject["data"].get("hidden_at"):
            continue  # skip deprecated/hidden items
        note = build_note(subject, model, position)
        deck.add_note(note)
        position += 1

    genanki.Package(deck).write_to_file("wanikani.apkg")
    print(f"\nDone! Wrote {len(deck.notes)} cards to wanikani.apkg")


if __name__ == "__main__":
    main()