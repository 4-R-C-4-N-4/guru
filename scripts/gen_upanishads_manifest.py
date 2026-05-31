"""
Generate the Upanishads ingest manifest fragment + chunking configs.

Self-contained. Hardcodes the file-to-section mapping derived from the
SBE01 and SBE15 volume indexes (see docs/corpus-expansion/url-vetting.md
§3.2-§3.5, cross-checked against the live index pages 2026-05-31).

Outputs:
  - /tmp/manifest-upanishads.fragment.toml   (~174 [[source]] stanzas)
  - chunking/upanishads/*.toml               (one config per stanza)

Design notes:
  * One [[source]] per SBE page. Matches the Yasna precedent in
    sources/manifest.toml:386-440 (one yasna-NN per SBE page).
  * Chunking strategy: "paragraph-group" (single-file strategy). The
    spec mentioned "page-as-chunk" but that strategy expects multi-page
    {id}-NN.txt raw files, not the single-file shape this manifest
    produces. "paragraph-group" with max_tokens=800 is what every Yasna
    config uses and what fits the actual file shape.
  * Îsâ-Upanishad is the only true single-file source (one SBE page
    contains the whole 18-verse text plus Müller's inline commentary
    tail). Its chunking config adds an extra pre_strip_patterns regex
    to drop everything from the post-translation horizontal rule onward.

Scope (pragmatic prune; ~174 entries total):
  * Katha          6  sbe15010..sbe15015
  * Mundaka        6  sbe15016..sbe15021
  * Taittirîya    31  sbe15022..sbe15052
  * Brihadâranyaka 46 sbe15053..sbe15099 minus sbe15098 (Hume insert)
  * Svetâsvatara   6  sbe15100..sbe15105
  * Prasña         6  sbe15106..sbe15111
  * Maitrâyana     7  sbe15112..sbe15118
  * Chandogya     57  sbe01119..sbe01175 (Prapâthakas VI-VIII; spec said
                       55 but the live SBE01 index shows 57 — every
                       file is present and labelled VI,1..VIII,15)
  * Kena           4  sbe01176..sbe01179
  * Aitareya       6  sbe01222..sbe01227 (Upanishad proper II.4-7;
                       spec said sbe01183..sbe01188 but those are
                       Aitareya-Âranyaka I,1,4..I,3,1 — confirmed
                       against vetting §2.10 which gives the correct
                       range as sbe01222..sbe01227)
  * Îsâ            1  sbe01243
  * --------------
  * Total        176  (spec said 174; the +2 comes from the corrected
                       Chandogya VI-VIII count)
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CHUNKING_DIR = PROJECT_ROOT / "chunking" / "upanishads"
FRAGMENT_PATH = Path("/tmp/manifest-upanishads.fragment.toml")


# ---------------------------------------------------------------------------
# File-to-section maps
# ---------------------------------------------------------------------------
# Each entry: (sbe_volume, sbe_num, sub_id, section_label, notes_blurb)
#   sbe_volume:    01 or 15
#   sbe_num:       integer file number  (e.g. 15010)
#   sub_id:        sub-id appended to the upanishad slug (e.g. "1-1")
#   section_label: human-readable section (e.g. "I,1")
#   notes_blurb:   short description for the [[source]] notes field
# ---------------------------------------------------------------------------


def katha_entries() -> list[tuple]:
    """Katha-Upanishad: 6 files, Vallîs I,1..I,3 and II,4..II,6."""
    # (sbe_num, vallî_number_as_displayed, adhyaya_for_id)
    # SBE15 index labels: sbe15010=I,1; sbe15011=I,2; sbe15012=I,3;
    #                     sbe15013=II,4; sbe15014=II,5; sbe15015=II,6.
    raw = [
        (15010, 1, 1, "I,1"),
        (15011, 1, 2, "I,2"),
        (15012, 1, 3, "I,3"),
        (15013, 2, 4, "II,4"),
        (15014, 2, 5, "II,5"),
        (15015, 2, 6, "II,6"),
    ]
    out = []
    for sbe_num, adh, sub, label in raw:
        sub_id = f"{adh}-{sub}"
        out.append((15, sbe_num, sub_id, label, f"Vallî {label}"))
    return out


def mundaka_entries() -> list[tuple]:
    """Mundaka-Upanishad: 6 files. I,1/I,2/II,1/II,2/III,1/III,2."""
    raw = [
        (15016, 1, 1, "I,1"),
        (15017, 1, 2, "I,2"),
        (15018, 2, 1, "II,1"),
        (15019, 2, 2, "II,2"),
        (15020, 3, 1, "III,1"),
        (15021, 3, 2, "III,2"),
    ]
    out = []
    for sbe_num, mund, kh, label in raw:
        sub_id = f"{mund}-{kh}"
        out.append((15, sbe_num, sub_id, label, f"Mundaka {mund}, Khanda {kh}"))
    return out


def taittiriya_entries() -> list[tuple]:
    """Taittirîya-Upanishad: 31 files. Three Vallîs."""
    out = []
    # Sikshâ-Vallî I.1..I.12 (sbe15022..sbe15033)
    for i, sbe_num in enumerate(range(15022, 15034), start=1):
        out.append((15, sbe_num, f"1-{i}", f"I,{i}", f"Sikshâ-Vallî I,{i}"))
    # Brahmânanda-Vallî II.1..II.9 (sbe15034..sbe15042)
    for i, sbe_num in enumerate(range(15034, 15043), start=1):
        out.append((15, sbe_num, f"2-{i}", f"II,{i}", f"Brahmânanda-Vallî II,{i}"))
    # Bhrigu-Vallî III.1..III.10 (sbe15043..sbe15052)
    for i, sbe_num in enumerate(range(15043, 15053), start=1):
        out.append((15, sbe_num, f"3-{i}", f"III,{i}", f"Bhrigu-Vallî III,{i}"))
    return out


def brihadaranyaka_entries() -> list[tuple]:
    """Brihadâranyaka-Upanishad: 46 files. Skip sbe15098 (Hume insert)."""
    # Adhyâya I = 5 files (index appears to skip I,3 — only labels are
    # I,1 I,2 I,4 I,5 I,6 per the live SBE15 index).
    out = []
    a1 = [
        (15053, "1-1", "I,1"),
        (15054, "1-2", "I,2"),
        (15055, "1-4", "I,4"),
        (15056, "1-5", "I,5"),
        (15057, "1-6", "I,6"),
    ]
    for sbe_num, sub_id, label in a1:
        out.append((15, sbe_num, sub_id, label, f"Adhyâya I, Brâhmana {label.split(',')[1]}"))

    # Adhyâya II..VI run contiguous except the sbe15098 skip.
    # II: sbe15058..sbe15063 = II,1..II,6
    for i, sbe_num in enumerate(range(15058, 15064), start=1):
        out.append((15, sbe_num, f"2-{i}", f"II,{i}", f"Adhyâya II, Brâhmana {i}"))
    # III: sbe15064..sbe15072 = III,1..III,9
    for i, sbe_num in enumerate(range(15064, 15073), start=1):
        out.append((15, sbe_num, f"3-{i}", f"III,{i}", f"Adhyâya III, Brâhmana {i}"))
    # IV: sbe15073..sbe15078 = IV,1..IV,6
    for i, sbe_num in enumerate(range(15073, 15079), start=1):
        out.append((15, sbe_num, f"4-{i}", f"IV,{i}", f"Adhyâya IV, Brâhmana {i}"))
    # V: sbe15079..sbe15093 = V,1..V,15
    for i, sbe_num in enumerate(range(15079, 15094), start=1):
        out.append((15, sbe_num, f"5-{i}", f"V,{i}", f"Adhyâya V, Brâhmana {i}"))
    # VI: sbe15094..sbe15097 = VI,1..VI,4; skip sbe15098 (Hume); sbe15099 = VI,5
    a6 = [
        (15094, "6-1", "VI,1"),
        (15095, "6-2", "VI,2"),
        (15096, "6-3", "VI,3"),
        (15097, "6-4", "VI,4"),
        # sbe15098 skipped (= "VI, 4: Hume Translation", duplicate)
        (15099, "6-5", "VI,5"),
    ]
    for sbe_num, sub_id, label in a6:
        out.append((15, sbe_num, sub_id, label, f"Adhyâya VI, Brâhmana {label.split(',')[1]}"))

    return out


def svetasvatara_entries() -> list[tuple]:
    """Svetâsvatara-Upanishad: 6 files, one per Adhyâya."""
    out = []
    for i, sbe_num in enumerate(range(15100, 15106), start=1):
        roman = ["I", "II", "III", "IV", "V", "VI"][i - 1]
        out.append((15, sbe_num, str(i), roman, f"Adhyâya {roman}"))
    return out


def prasna_entries() -> list[tuple]:
    """Prasña-Upanishad: 6 files, one per Question."""
    out = []
    names = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]
    for i, sbe_num in enumerate(range(15106, 15112), start=1):
        out.append((15, sbe_num, str(i), f"Question {i}", f"{names[i-1]} Question"))
    return out


def maitrayana_entries() -> list[tuple]:
    """Maitrâyana-Brâhmana-Upanishad: 7 files, one per Prapâthaka."""
    out = []
    names = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh"]
    for i, sbe_num in enumerate(range(15112, 15119), start=1):
        out.append((15, sbe_num, str(i), f"Prapâthaka {i}", f"{names[i-1]} Prapâthaka"))
    return out


def chandogya_entries() -> list[tuple]:
    """Chandogya (Khândogya): Prapâthakas VI-VIII only.
    sbe01119..sbe01175 = 57 files (every file present in SBE01 index)."""
    out = []
    # VI: sbe01119..sbe01134 = VI,1..VI,16
    for i, sbe_num in enumerate(range(1119, 1135), start=1):
        out.append((1, sbe_num, f"6-{i}", f"VI,{i}", f"Prapâthaka VI, Khanda {i}"))
    # VII: sbe01135..sbe01160 = VII,1..VII,26
    for i, sbe_num in enumerate(range(1135, 1161), start=1):
        out.append((1, sbe_num, f"7-{i}", f"VII,{i}", f"Prapâthaka VII, Khanda {i}"))
    # VIII: sbe01161..sbe01175 = VIII,1..VIII,15
    for i, sbe_num in enumerate(range(1161, 1176), start=1):
        out.append((1, sbe_num, f"8-{i}", f"VIII,{i}", f"Prapâthaka VIII, Khanda {i}"))
    return out


def kena_entries() -> list[tuple]:
    """Kena (Talavakâra): 4 files, one per Khanda."""
    out = []
    names = ["First", "Second", "Third", "Fourth"]
    for i, sbe_num in enumerate(range(1176, 1180), start=1):
        out.append((1, sbe_num, str(i), f"Khanda {i}", f"{names[i-1]} Khanda"))
    return out


def aitareya_entries() -> list[tuple]:
    """Aitareya-Upanishad proper: II.4-7 (sbe01222..sbe01227, 6 files).
    Defers the rest of the Aitareya-Âranyaka."""
    # Per live SBE01 index:
    #   sbe01222 = II, 4, 1
    #   sbe01223 = II, 4, 2
    #   sbe01224 = II, 4, 3
    #   sbe01225 = II, 5, 1
    #   sbe01226 = II, 6, 1
    #   sbe01227 = II, 7, 1
    raw = [
        (1222, "2-4-1", "II,4,1"),
        (1223, "2-4-2", "II,4,2"),
        (1224, "2-4-3", "II,4,3"),
        (1225, "2-5-1", "II,5,1"),
        (1226, "2-6-1", "II,6,1"),
        (1227, "2-7-1", "II,7,1"),
    ]
    out = []
    for sbe_num, sub_id, label in raw:
        out.append((1, sbe_num, sub_id, label, f"Aitareya-Upanishad {label}"))
    return out


def isa_entry() -> tuple:
    """Îsâ-Upanishad: single page sbe01243. No sub-id."""
    return (1, 1243, None, "(18 verses)", "Whole text; 18 verses with Müller's commentary tail")


# ---------------------------------------------------------------------------
# Per-Upanishad config
# ---------------------------------------------------------------------------

UPANISHADS = [
    # (slug, display_name, label_short, entries_fn, intro_blurb)
    ("katha-upanishad",         "Katha-Upanishad",                 "Katha",              katha_entries,         "Naciketas/Yama dialogue; the chariot-of-the-self image (I.3.3-9)."),
    ("mundaka-upanishad",       "Mundaka-Upanishad",               "Mundaka",            mundaka_entries,       "Two-birds-on-one-tree image (III.1.1); parâ/aparâ vidyâ."),
    ("taittiriya-upanishad",    "Taittirîya-Upanishad",            "Taittirîya",         taittiriya_entries,    "Pañcakosha (five-sheath) model of the self."),
    ("brihadaranyaka-upanishad","Brihadâranyaka-Upanishad",        "Brihadâranyaka",     brihadaranyaka_entries,"Yâjñavalkya dialogues; neti neti (II.3.6)."),
    ("svetasvatara-upanishad",  "Svetâsvatara-Upanishad",          "Svetâsvatara",       svetasvatara_entries,  "The most theistic principal Upanishad; Rudra as Highest Self."),
    ("prasna-upanishad",        "Prasña-Upanishad",                "Prasña",             prasna_entries,        "Six questions to Pippalâda; prâna cosmology, OM meditation."),
    ("maitrayana-upanishad",    "Maitrâyana-Brâhmana-Upanishad",   "Maitrâyana",         maitrayana_entries,    "Sixfold yoga (VI.18); the most yoga-explicit principal Upanishad."),
    ("chandogya-upanishad",     "Khândogya-Upanishad",             "Khândogya",          chandogya_entries,     "Prapâthakas VI-VIII (tat tvam asi, honey-doctrine, Indra/Virocana, Sândilya-vidyâ)."),
    ("kena-upanishad",          "Kena-Upanishad",                  "Kena",               kena_entries,          "Brahman as the ground of cognition."),
    ("aitareya-upanishad",      "Aitareya-Upanishad",              "Aitareya",           aitareya_entries,      "Upanishad proper (Âranyaka II.4-7): cosmogony, prajñânam brahma."),
]


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

def _toml_str(s: str) -> str:
    """TOML-escape a string for a basic double-quoted literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit_stanza(source_id: str, label: str, url: str, notes: str) -> str:
    return (
        "[[source]]\n"
        f'id = "{_toml_str(source_id)}"\n'
        'tradition = "upanishads"\n'
        f'label = "{_toml_str(label)}"\n'
        f'url = "{_toml_str(url)}"\n'
        'format = "html"\n'
        'license = "public_domain"\n'
        'translator = "F. Max Müller"\n'
        f'notes = "{_toml_str(notes)}"\n'
    )


def emit_chunking_config(
    source_id: str,
    text_name: str,
    label_short: str,
    section_label: str,
    is_isa: bool,
) -> str:
    """Standard paragraph-group config. Îsâ gets extra pre_strip."""
    if section_label:
        section_label_format = f"{label_short}, {section_label}"
    else:
        section_label_format = label_short

    if is_isa:
        # Îsâ-specific: drop the post-translation commentary tail.
        # The page layout (verified 2026-05-31) is:
        #   <h3>VÂGASANEYI-SAMHITÂ-UPANISHAD, ... ÎSÂ-UPANISHAD</h3>
        #   18 numbered verses
        #   <hr> (horizontal rule) — rendered in the plaintext extract
        #                            as a single long underscore run
        #   ~30 paragraphs of verse-by-verse commentary
        #   <h3 align="CENTER">Footnotes</h3>
        #   footnotes block
        # The underscore run is the only one in the page (verified) so
        # it's a clean cut-point. The Footnotes fallback handles any
        # raw-extractor change that drops the <hr>.
        chunking = (
            '[chunking]\n'
            'strategy = "paragraph-group"\n'
            f'section_label_format = "{section_label_format}, Section {{n}}"\n'
            'paragraphs_per_chunk = 3\n'
            'max_tokens = 800\n'
            '# Drop everything from Müller\'s verse-by-verse commentary tail onward.\n'
            "# The HTML <hr> between verse 18 and the commentary renders as a\n"
            '# long underscore run (the only one in the page).\n'
            'pre_strip_patterns = [\n'
            "    '_{5,}.*$',\n"
            "    '(?m)^Footnotes\\b.*$',\n"
            ']\n'
        )
    else:
        chunking = (
            '[chunking]\n'
            'strategy = "paragraph-group"\n'
            f'section_label_format = "{section_label_format}, Section {{n}}"\n'
            'paragraphs_per_chunk = 3\n'
            'max_tokens = 800\n'
            "pre_strip_patterns = ['''(?m)^Footnotes\\b[\\s\\S]*$''']\n"
        )

    metadata = (
        '\n[metadata]\n'
        'tradition = "Upanishads"\n'
        f'text_name = "{_toml_str(text_name)}"\n'
        'translator = "F. Max Müller"\n'
        'sections_format = "section"\n'
    )
    return chunking + metadata


def main() -> None:
    CHUNKING_DIR.mkdir(parents=True, exist_ok=True)

    fragment_lines: list[str] = [
        "# ============================================================\n",
        "# Guru Corpus — Upanishads (Müller, SBE Vols. 1 & 15)\n",
        "# Generated by scripts/gen_upanishads_manifest.py\n",
        "# tradition = \"upanishads\"\n",
        "# One [[source]] per SBE page (Yasna precedent).\n",
        "# ============================================================\n",
        "\n",
    ]

    total_stanzas = 0
    total_configs = 0
    per_upanishad: list[tuple[str, int]] = []

    for slug, display_name, label_short, entries_fn, intro_blurb in UPANISHADS:
        entries = entries_fn()
        per_upanishad.append((slug, len(entries)))

        fragment_lines.append(f"# ---------- {display_name} ({len(entries)} files) ----------\n")

        for sbe_volume, sbe_num, sub_id, section_label, notes_blurb in entries:
            source_id = f"{slug}-{sub_id}" if sub_id else slug
            vol_str = f"sbe{sbe_volume:02d}"
            # sbe_num is the full 5-digit page number (e.g. 15010, 01243).
            url = f"https://sacred-texts.com/hin/{vol_str}/sbe{sbe_num:05d}.htm"
            label = f"{display_name} (Müller), {section_label}"
            notes = f"SBE{sbe_volume}. {notes_blurb}. {intro_blurb}"

            fragment_lines.append(emit_stanza(source_id, label, url, notes))
            fragment_lines.append("\n")
            total_stanzas += 1

            cfg_text = emit_chunking_config(
                source_id=source_id,
                text_name=display_name,
                label_short=label_short,
                section_label=section_label,
                is_isa=False,
            )
            cfg_path = CHUNKING_DIR / f"{source_id}.toml"
            cfg_path.write_text(cfg_text, encoding="utf-8")
            total_configs += 1

    # Îsâ — single-page, special pre_strip
    sbe_volume, sbe_num, sub_id, section_label, notes_blurb = isa_entry()
    slug = "isa-upanishad"
    display_name = "Îsâ-Upanishad"
    label_short = "Îsâ"
    vol_str = f"sbe{sbe_volume:02d}"
    url = f"https://sacred-texts.com/hin/{vol_str}/sbe{sbe_num:05d}.htm"
    label = f"{display_name} (Müller)"
    intro_blurb = "Shortest principal Upanishad (18 verses); single sacred-texts page also carries Müller's verse-by-verse commentary tail."
    notes = f"SBE{sbe_volume}. {notes_blurb}. {intro_blurb}"

    fragment_lines.append(f"# ---------- {display_name} (1 file, includes commentary tail) ----------\n")
    fragment_lines.append(emit_stanza(slug, label, url, notes))
    fragment_lines.append("\n")
    total_stanzas += 1

    cfg_text = emit_chunking_config(
        source_id=slug,
        text_name=display_name,
        label_short=label_short,
        section_label="",  # whole-text — section_label injection handled in format string
        is_isa=True,
    )
    cfg_path = CHUNKING_DIR / f"{slug}.toml"
    cfg_path.write_text(cfg_text, encoding="utf-8")
    total_configs += 1
    per_upanishad.append((slug, 1))

    FRAGMENT_PATH.write_text("".join(fragment_lines), encoding="utf-8")

    # Summary
    print(f"Manifest fragment: {FRAGMENT_PATH}")
    print(f"Chunking configs:  {CHUNKING_DIR}")
    print()
    for slug, count in per_upanishad:
        print(f"  {slug:36s} {count:3d}")
    print()
    print(f"Total stanzas:        {total_stanzas}")
    print(f"Total chunking configs: {total_configs}")
    if total_stanzas != total_configs:
        print(f"  WARNING: stanza/config mismatch ({total_stanzas} vs {total_configs})")


if __name__ == "__main__":
    main()
