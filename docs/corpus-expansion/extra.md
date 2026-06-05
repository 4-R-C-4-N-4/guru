# ============================================================
# Guru Corpus — Upanishads (Müller, SBE Vols. 1 & 15)
# Append to sources/manifest.toml
# 11 sources, one per principal Upanishad. Tradition: "upanishads".
# All public domain (Müller, 1879/1884).
# ============================================================
#
# WHY ONE ENTRY PER UPANISHAD (not a volume index crawl):
#   The pipeline keys everything on source_id — raw/{trad}/{id}-NN.txt,
#   one chunking config per id, chunk IDs "upanishads.{id}.NNN", one
#   metadata.toml per id. A single html_multi entry on the SBE volume
#   index would (a) weld 5-7 distinct Upanishads into one "text" with no
#   per-text citation, and (b) scrape Müller's per-Upanishad Introduction
#   essays as if they were scripture. Separate single-page entries give
#   correct provenance (cite "Katha I.3.14", not "SBE15 §47") and skip
#   the intros. Mirrors how Corpus Hermeticum is 17 entries, not 1 crawl.
#
# ⚠️ URL VERIFICATION REQUIRED (agent task):
#   sbe15 filenames do NOT track reading order (same quirk the manifest
#   already documents for the Zoroastrian Yasnas). Each volume has TWO
#   sequences: per-Upanishad Introduction essays FIRST (sbe15007 =
#   Svetasvatara intro, sbe15009 = Maitrayana intro — both verified as
#   INTRO, not translation), then the translations. The `url` on each
#   entry below is the inferred TRANSLATION start page. Every unverified
#   one is tagged `# GUESS`. Confirm each against the volume index
#   (https://sacred-texts.com/hin/sbe15/index.htm and .../sbe01/index.htm)
#   and fix the filename if wrong. Point at the page whose <h2> reads the
#   Upanishad name followed by verse-numbered body (e.g. "FIRST ADHYÂYA"),
#   NOT the "Introduction" essay.
#
# ⚠️ DOWNLOADER PATCH REQUIRED (scripts/downloaders/sacred_texts.py):
#   These SBE pages need two fixes in extract_text_page() that the current
#   extractor lacks. Verified against sbe15009.htm raw markup:
#     1. FOOTNOTE/PAGE-MARKER STRIP: inline refs are
#        <a href="...#fn_NN"><font size="1">N</font></a> and page markers
#        are <a name="page_xliv"><font size="1" color="green">p. xliv</font></a>.
#        The current get_text() flattens these to bare digits glued to words
#        ("Svetâsva 1"). Fix: decompose <font size="1"> and <sup> before
#        get_text(). This also kills the inline page markers.
#     2. FOOTNOTE BLOCK DROP: the apparatus sits in a trailing block after
#        <h3 align="CENTER">Footnotes</h3>. Drop everything from that <h3>
#        onward. (Belt-and-suspenders: the per-config pre_strip below also
#        regex-cuts it, in case the patch lands later.)
#   Without the patch the chunking pre_strip still removes most of it, but
#   the inline <font size="1"> digits are cleaner to kill at extraction.
#
# DIACRITICS: Müller uses heavy diacritics (Svetâsvatara, Saṅkara, â/î/ṅ).
#   They scrape fine but query-time "Svetasvatara" won't match "Svetâsvatara"
#   unless embed_corpus.py folds diacritics. Corpus-wide latent issue these
#   texts surface hard — worth a fold-to-ASCII pass in the embed normalizer.
 
 
# ---------- SBE Vol. 15 ----------
 
[[source]]
id = "katha-upanishad"
tradition = "upanishads"
label = "Katha-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15010.htm"  # VERIFIED 2026-05-31 — first translation page; <h2>FIRST ADHYÂYA</h2> <h3>FIRST VALLÎ</h3>. Intro essay is sbe15003.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (6 sbeNNN pages: sbe15010=I,1 .. sbe15015=II,6).
# Single-page url captures Vallî I,1 only — Vallîs I,2..II,6 are on subsequent
# pages and will be missed by format="html". To capture the full Upanishad,
# either (a) follow the Yasna precedent and split into 6 per-Vallî sub-entries
# (id katha-upanishad-1-1..2-3), or (b) host a per-Upanishad sub-index page that
# format="html_multi" can crawl. See docs/corpus-expansion/url-vetting.md §3.
notes = "SBE15. HIGHEST cross-tradition value in the set: the chariot-of-the-self (I.3.3-9, atman as rider, body as chariot, senses as horses) is a near-exact structural twin of Plato's Phaedrus — direct edge to platonism in corpus. Naciketas/Death dialogue. Structure: two Adhyâyas, three Vallîs each (I.1-I.3, II.1-II.3)."
 
[[source]]
id = "mundaka-upanishad"
tradition = "upanishads"
label = "Mundaka-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15016.htm"  # VERIFIED 2026-05-31 — first translation page (I,1). The draft sbe15014 was Katha-Upanishad II,5. Intro essay is sbe15004.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (6 pages: sbe15016=I,1 .. sbe15021=III,2).
# Same restructure decision as katha-upanishad applies.
notes = "SBE15. The two-birds-on-one-tree image (III.1.1: one bird eats the fruit, the other watches) — witness-consciousness edge. Also the two-knowledges doctrine (parâ/aparâ, higher vs lower vidyâ) -> knowledge_path. Structure: three Mundakas, two Khandas each. number from <h2>."
 
[[source]]
id = "taittiriya-upanishad"
tradition = "upanishads"
label = "Taittirîya-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15022.htm"  # VERIFIED 2026-05-31 — first translation page; <h1>TAITTIRÎYAKA-UPANISHAD.</h1> <h2>FIRST VALLÎ</h2>. The draft sbe15016 was actually Mundaka-Upanishad I,1. Intro essay is sbe15005.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (31 pages: sbe15022=I,1 .. sbe15052=III,10;
# Sikshâ-Vallî I.1-12, Brahmânanda-Vallî II.1-9, Bhrigu-Vallî III.1-10).
# Single-page url captures Sikshâ-Vallî I,1 only. Restructure required.
notes = "SBE15. The pañcakosha (five-sheath) model of the self — annamaya/prânamaya/manomaya/vijñânamaya/ânandamaya — is the primary source for human_constitution. Also the ânanda (bliss) calculus. Structure: three Vallîs (Sikshâ, Brahmânanda, Bhrigu)."
 
[[source]]
id = "brihadaranyaka-upanishad"
tradition = "upanishads"
label = "Brihadâranyaka-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15053.htm"  # VERIFIED 2026-05-31 — first translation page; <h1>BRIHADÂRANYAKA-UPANISHAD.</h1> <h2>FIRST ADHYÂYA</h2>. The draft sbe15018 was Mundaka-Upanishad II,1. Intro essay is sbe15006. ⚠️ MULTI-PAGE — see NOTE below.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: CONFIRMED MULTI-PAGE — by far the heaviest in the set. 47 sacred-texts
# pages: sbe15053 (I,1) through sbe15099 (VI,5), spanning six Adhyâyas:
#   Adhyâya I = sbe15053..sbe15057 (I,1..I,6; note: index skips I,3 — only 5 pages)
#   Adhyâya II = sbe15058..sbe15063 (II,1..II,6)
#   Adhyâya III = sbe15064..sbe15072 (III,1..III,9)
#   Adhyâya IV = sbe15073..sbe15078 (IV,1..IV,6)
#   Adhyâya V = sbe15079..sbe15093 (V,1..V,15)
#   Adhyâya VI = sbe15094..sbe15099 (VI,1..VI,5; plus sbe15098 is a duplicate
#                "VI, 4: Hume Translation" inserted into the sequence — exclude or
#                handle as alternate translation)
# Single [[source]] with format="html" will only capture Adhyâya I,1.
# RECOMMENDED RESTRUCTURE: per-page sub-entries with ids
# brihadaranyaka-upanishad-1-1 .. brihadaranyaka-upanishad-6-5 — matches Yasna
# precedent (each SBE page = one [[source]] = one chunkable text).
# (format="html_multi" pointed at the SBE15 volume index would conflate this
# Upanishad with all six others in the volume — wrong shape.)
notes = "SBE15. The longest and oldest principal Upanishad — neti neti ('not this, not this', II.3.6), the Yâjñavalkya dialogues, 'tat tvam asi' cognates. Structure: six Adhyâyas, split across 47 sacred-texts pages. See multi-page NOTE above before acquisition."
 
[[source]]
id = "svetasvatara-upanishad"
tradition = "upanishads"
label = "Svetâsvatara-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15100.htm"  # VERIFIED 2026-05-31 — first translation page; <h3>FIRST ADHYÂYA</h3>. The draft sbe15022 was actually Taittiriya-Upanishad I,1 (way off). Intro essay is sbe15007 (confirmed).
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (6 pages: sbe15100..sbe15105, one per Adhyâya).
# Same restructure decision as katha-upanishad — per-Adhyâya sub-entries
# (svetasvatara-upanishad-1..6) matches the existing Yasna pattern.
notes = "SBE15. The most theistic principal Upanishad — Rudra/Hara/Siva as the Highest Self, mâyâ as the Lord's self-power (sakti), bhakti in the final verse. Strong edge to sufism (personal God + union) and to the emanation material. Müller's intro (sbe15007, NOT this page) is a 12-page essay on its dating — do NOT ingest the intro. Structure: six Adhyâyas."
 
[[source]]
id = "prasna-upanishad"
tradition = "upanishads"
label = "Prasña-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15106.htm"  # VERIFIED 2026-05-31 — first translation page; <h3>FIRST QUESTION</h3>. The draft sbe15025 was Taittiriya-Upanishad I,4. Intro essay is sbe15008.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (6 pages: sbe15106..sbe15111, one per
# prasña/question). Per-question sub-entries (prasna-upanishad-1..6) match
# the Yasna pattern.
notes = "SBE15. Six questions (prasña) put to the sage Pippalâda — prâna (life-breath) cosmology, the 16 parts of the person, OM meditation (the three mâtrâs). -> origin_events, contemplative_practice. Structure: six Prasñas."
 
[[source]]
id = "maitrayana-upanishad"
tradition = "upanishads"
label = "Maitrâyana-Brâhmana-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe15/sbe15112.htm"  # VERIFIED 2026-05-31 — first translation page; <h3>FIRST PRAPÂTHAKA</h3>. The draft sbe15028 was Taittiriya-Upanishad I,7. Intro essay is sbe15009 (confirmed by user).
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (7 pages: sbe15112..sbe15118, one per
# prapâthaka). Per-prapâthaka sub-entries (maitrayana-upanishad-1..7) match
# the Yasna pattern.
notes = "SBE15. Later/composite; the most yoga-explicit principal Upanishad — sixfold yoga (prânâyâma, pratyâhâra, dhyâna, dhâranâ, tarka, samâdhi, VI.18), the chariot/inner-self imagery. Edge to praxis/transformative_path. Müller's intro is sbe15009 (verified) — do NOT ingest it. Structure: seven Prapâthakas."
 
 
# ---------- SBE Vol. 1 ----------
 
[[source]]
id = "chandogya-upanishad"
tradition = "upanishads"
label = "Khândogya-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe01/sbe01022.htm"  # VERIFIED 2026-05-31 — first translation page; <h1>KHÂNDOGYA-UPANISHAD.</h1> <h2>FIRST PRAPÂTHAKA.</h2> <h3>FIRST KHANDA.</h3>. Draft sbe01023 was page 2 (I,2). Intro essay is sbe01017. ⚠️ MULTI-PAGE — see NOTE.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: CONFIRMED MULTI-PAGE — the heaviest single Upanishad in the set.
# 154 sacred-texts pages: sbe01022 (I,1) through sbe01175 (VIII,15).
#   Prapâthaka I = sbe01022..sbe01034 (I,1..I,13)
#   Prapâthaka II = sbe01035..sbe01058 (II,1..II,24)
#   Prapâthaka III = sbe01059..sbe01077 (III,1..III,19)
#   Prapâthaka IV = sbe01078..sbe01094 (IV,1..IV,17)
#   Prapâthaka V = sbe01095..sbe01118 (V,1..V,24)
#   Prapâthaka VI = sbe01119..sbe01134 (VI,1..VI,16)    ← 'tat tvam asi' lives in VI
#   Prapâthaka VII = sbe01135..sbe01160 (VII,1..VII,26)
#   Prapâthaka VIII = sbe01161..sbe01175 (VIII,1..VIII,15)
# Single [[source]] with format="html" will capture Prapâthaka I,1 only.
# RECOMMENDED RESTRUCTURE: per-page sub-entries with ids chandogya-upanishad-1-1
# .. chandogya-upanishad-8-15 (154 entries) — matches the Yasna precedent.
# If 154 entries is too coarse for the source-roster, a pragmatic middle path
# is to acquire only Prapâthakas VI-VIII (the highest-density material:
# tat-tvam-asi, the honey-doctrine, the Sândilya-vidyâ, Indra/Virocana, the
# bridge metaphors) as ~55 entries and defer I-V to a later expansion.
notes = "SBE01 (Müller spells it 'Khândogya'). Carries the canonical 'tat tvam asi' (VI.8-16, Uddâlaka to Svetaketu) — the single most important non-dual identity statement in the corpus. Also the honey-doctrine and Sândilya-vidyâ. 154 sacred-texts pages — see multi-page NOTE before acquisition."
 
[[source]]
id = "kena-upanishad"
tradition = "upanishads"
label = "Kena-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe01/sbe01176.htm"  # VERIFIED 2026-05-31 — first translation page; <h1>TALAVAKÂRA</h1> <h1>KENA-UPANISHAD.</h1>. Draft sbe01015 was an Introduction essay titled "Meaning of the Word Upanishad" — VERY wrong (not even an Upanishad-specific intro). Per-Upanishad intro is sbe01018 ("II. The Talavakâra-Upanishad").
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: MULTI-PAGE on sacred-texts (4 pages: sbe01176..sbe01179, one per Khanda).
# Per-Khanda sub-entries (kena-upanishad-1..4) match the Yasna pattern.
notes = "SBE01. Short. 'That which is not thought by the mind, by which the mind is thought' — Brahman as the ground of cognition, unknowable as object. -> divine_nature, knowledge_path. Four Khandas. Sacred-texts calls this Upanishad 'Talavakâra or Kena' interchangeably (it sits in the Talavakâra-Brâhmana of the Sâma-Veda)."
 
[[source]]
id = "aitareya-upanishad"
tradition = "upanishads"
label = "Aitareya-Âranyaka (Müller)"
url = "https://sacred-texts.com/hin/sbe01/sbe01180.htm"  # VERIFIED 2026-05-31 — first translation page; <h2>FIRST ADHYÂYA.</h2>. Draft sbe01018 was an Introduction essay ("II. The Talavakâra-Upanishad" intro — not even the Aitareya intro). Per-Upanishad intro is sbe01019.
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: CONFIRMED MULTI-PAGE — substantial. 59 sacred-texts pages:
# sbe01180 (I,1,1) through sbe01238 (III,2,6). Müller publishes the entire
# Aitareya-Âranyaka (not only the narrow "Aitareya Upanishad" subset which is
# Âranyaka II.4-7). Structure: three Adhyâyas, each subdivided further:
#   Adhyâya I = sbe01180..sbe01201 (I,1,1..I,5,3; 22 pages)
#   Adhyâya II = sbe01202..sbe01227 (II,1,1..II,7,1; 26 pages — the canonical
#                  "Aitareya Upanishad" lives in II.4-7, sbe01222..01227)
#   Adhyâya III = sbe01228..sbe01238 (III,1,1..III,2,6; 11 pages; note index
#                  appears to skip III,1,3)
# Label has been corrected to "Aitareya-Âranyaka" because Müller's text IS the
# whole Âranyaka, not the narrower Upanishad. If only the Upanishad proper is
# wanted, scope acquisition to sbe01222..sbe01227 (6 pages: Âranyaka II.4-7).
# Otherwise, per-page sub-entries (aitareya-aranyaka-1-1-1 .. -3-2-6) match
# the Yasna pattern.
notes = "SBE01. Cosmogony — the Self (Âtman) alone in the beginning, emitting the worlds; 'prajñânam brahma' (consciousness is Brahman), one of the four mahâvâkyas. -> origin_events, cosmology. NOTE: Müller publishes the full Aitareya-Âranyaka; the Upanishad proper is the subset Âranyaka II.4-7 (sbe01222..sbe01227). See multi-page NOTE above to decide scope."
 
[[source]]
id = "isa-upanishad"
tradition = "upanishads"
label = "Îsâ-Upanishad (Müller)"
url = "https://sacred-texts.com/hin/sbe01/sbe01243.htm"  # VERIFIED 2026-05-31 — single-page translation; <h3>VÂGASANEYI-SAMHITÂ-UPANISHAD, SOMETIMES CALLED ÎSÂVÂSYA OR ÎSÂ-UPANISHAD</h3> followed by the 18 numbered verses. Draft sbe01021 was an Introduction essay ("V. The Vâgasaneyi-Samhitâ-Upanishad").
format = "html"
license = "public_domain"
translator = "F. Max Müller"
# NOTE: Genuinely single-page (the only Upanishad in the set that is). The page
# contains the 18-verse translation AT THE TOP, followed by ~30 pages of Müller's
# commentary on each verse (still inline in the same page). Add a
# pre_strip_patterns rule in chunking/upanishads/isa-upanishad.toml to drop
# everything from the post-verse-18 horizontal rule onward, OR accept the
# commentary as supplementary scripture (Müller's discussion of Sankara, Uvata,
# Mahidhara). Decide before chunking.
notes = "SBE01. The shortest principal Upanishad (18 verses) — 'enveloped by the Lord is all this', action-without-attachment, the famous paradox verses (it moves / it moves not). Single short page that ALSO contains Müller's verse-by-verse commentary — see NOTE above for scope decision. Good edge to the Gita's karma-yoga."
 
# ---------- Kaushîtaki deliberately omitted ----------
# In SBE01 but lower edge-density for this taxonomy and textually
# difficult; add later if the cluster wants it. Not worth a GUESS URL now.

# ---------- Mandukya-Upanishad: NOT INCLUDED (and not available in SBE) ----------
# VERIFIED 2026-05-31 against both volume indexes: Müller did NOT translate the
# Mandukya-Upanishad in either SBE01 (1879) or SBE15 (1884). Both indexes were
# walked end-to-end; the only Upanishads carried are the 11 listed above plus
# the deliberately-omitted Kaushîtaki. The 12-verse Mandukya (four states of
# consciousness, the OM analysis A-U-M-silence) would need a different
# translation source — e.g. Nikhilananda 1949 (still in copyright), Hume 1921
# ("The Thirteen Principal Upanishads", PD in US), or Gambhirananda's Sankara-
# bhasya English (in copyright). Hume's text is hosted at sacred-texts.com
# (/hin/sbe* slot does NOT cover it; see /hin/upan/ or look up Hume separately)
# — needs its own scoping pass; do NOT just slot a "mandukya-upanishad" entry
# under SBE15 pointing at any sbe15NNN file. There isn't one.
