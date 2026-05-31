# ============================================================
# Guru Corpus — Source Manifest ADDITIONS (this session)
# Append to sources/manifest.toml
# 7 sources across 5 new traditions; all public domain.
# ============================================================
 
 
# ============================================
# CONTEMPORARY PAGAN / WITCHCRAFT
# ============================================
# Leland's Aradia is the foundational "discovered scripture" of the
# modern witchcraft revival — the Diana/Lucifer/Aradia emanation myth
# and the liberation-through-sorcery frame. Strong cross-tradition
# edges to the Gnostic Lucifer-as-light-bringer and the Mesopotamian
# descent material already in corpus. ara03.htm = Chapter I; chapters
# run contiguously. ara00-02 (title/preface/contents) excluded.
# NOTE: authenticity disputed (Hutton's three theories) — tag as
# disputed-provenance; it is a real 1899 folklore artifact and a
# foundational Wicca text, not an authentic ancient survival.
 
[[source]]
id = "aradia-gospel-witches"
tradition = "pagan_witchcraft"
# VERIFIED 2026-05-31 — index resolves; ara03.htm = "CHAPTER I — How Diana Gave
# Birth to Aradia (Herodias)"; chapters run ara03..ara17 contiguously. ara00/01/02
# are Title/Preface/Contents; ara18 is the Appendix. html_multi downloader skips
# index but will pull ara00-02 + ara18 alongside the 15 chapters — drop those
# four post-acquisition (or add them to is_apparatus_chunk targets).
label = "Aradia, or the Gospel of the Witches (Leland)"
url = "https://sacred-texts.com/pag/aradia/index.htm"
format = "html_multi"
license = "public_domain"
translator = "Charles Godfrey Leland"
notes = "Leland 1899 (David Nutt, London); author d. 1903, clean PD. Index links to chapter files ara03.htm (Ch. I) onward. Italian incantations interleaved with English translation — keep both; do not strip the Italian. Chunk paragraph-group within each chapter file."
 
 
# ============================================
# NORSE / HEATHEN
# ============================================
# The Poetic Edda is the primary storehouse of Norse pagan cosmology.
# Voluspo (creation->Ragnarok) and Hovamol (Othin's wisdom counsels +
# the rune-charm catalogue) are the conceptually dense mythological
# core. The heroic lays (Helgakvitha onward) are narrative-heavy —
# deferred, like the Orphic Argonautica, unless corpus goes narrative.
 
[[source]]
id = "poetic-edda-voluspo"
tradition = "norse"
# VERIFIED 2026-05-31 — single page; <title>The Poetic Edda: Voluspo</title>,
# <h1>THE POETIC EDDA</h1> / <h2>LAYS OF THE GODS</h2> / <h2>VOLUSPO</h2>.
label = "The Poetic Edda: Voluspo (Bellows)"
url = "https://sacred-texts.com/neu/poe/poe03.htm"
format = "html"
license = "public_domain"
translator = "Henry Adams Bellows"
notes = "Bellows 1923/1936; PD via non-renewal. The Wise-Woman's Prophecy: cosmogony, world-tree, Ragnarok. Bellows interleaves heavy stanza-numbered commentary in [brackets] — treat bracketed notes as text-critical metadata, mirror the Enoch [[ ]] handling. Chunk on stanza-number groups."
 
[[source]]
id = "poetic-edda-hovamol"
tradition = "norse"
# VERIFIED 2026-05-31 — single page; <title>The Poetic Edda: Hovamol</title>,
# <h1>HOVAMOL</h1> with sub-heading "The Ballad of the High One".
label = "The Poetic Edda: Hovamol (Bellows)"
url = "https://sacred-texts.com/neu/poe/poe04.htm"
format = "html"
license = "public_domain"
translator = "Henry Adams Bellows"
notes = "Bellows 1923/1936. 'The High One's Words' — Othin's gnomic wisdom (cf. Biblical Proverbs) plus the Loddfafnismol and the rune-charm list (stanzas 111-165). Same bracket-as-metadata handling as Voluspo."
 
 
# ============================================
# SHINTO (cosmogonic sections only)
# ============================================
# Kojiki Chamberlain 1919, clean PD. Scoped to the kamiyo ("age of
# the gods") cosmogony: the first deities of the Plain of High Heaven.
# The scholarly introduction (kj001-006) and the later imperial-
# genealogy books are narrative/chronicle-heavy — excluded for
# conceptual density, matching the narrative-deferral policy above.
 
[[source]]
id = "kojiki-beginning-heaven-earth"
tradition = "shinto"
# VERIFIED 2026-05-31 — single page; <title>The Kojiki: Volume I: Section I.—
# The Beginning of Heaven and Earth</title>, <h3>[SECT. I.—THE BEGINNING OF
# HEAVEN AND EARTH.]</h3>. Page also contains a Footnotes block — same SBE-style
# apparatus issue documented in extra.md; will need a per-config
# pre_strip_patterns rule or the downloader patch.
label = "The Kojiki: The Beginning of Heaven and Earth (Chamberlain)"
url = "https://sacred-texts.com/shi/kj/kj008.htm"
format = "html"
license = "public_domain"
translator = "Basil Hall Chamberlain"
notes = "Chamberlain 1919. Section I: the first deities of the Plain of High Heaven, born alone and hidden. Chamberlain's numbered footnote markers ride inline in the text — strip the superscript ordinals but preserve sentence flow. Single leaf page; paragraph-group chunk."
 
 
# ============================================
# YORUBA / WEST AFRICAN
# ============================================
# Ellis 1894 is the unambiguously-PD anchor for Yoruba religion —
# the orisha system, Ifa divination substrate, the Ife creation
# material. Strong edges to the emanation-hierarchy and divination
# concepts already in corpus. Multi-chapter; yor05.htm verified live.
# NOTE: Victorian colonial ethnography — outsider lens, dated register
# ("primitive"/"fetish"). Citable for its data, not its framing; tag
# as colonial-ethnography, not insider/practitioner account.
 
[[source]]
id = "yoruba-speaking-peoples-ellis"
tradition = "yoruba"
# VERIFIED 2026-05-31 — index resolves; chapter pattern is yor02..yor13 (yor02=
# Chapter I, yor03=Chapter II, etc.). Note: the index file numbering is not
# perfectly contiguous with Roman-numeral chapters — yor10.htm is Chapter IX,
# yor11.htm is Chapter XIII (Chapters X-XII appear omitted from the archive,
# probably the linguistic appendices). Chapters available: I (Introductory),
# II (Chief Gods), III (Minor Gods), IV (Remarks), V (Priests and Worship),
# VI (Egungun/Oro/Abiku), VII (In-Dwelling Spirits), VIII (Measurements of
# Time), IX (Ceremonies at Birth/Marriage/Death), XIII (Proverbs), XIV
# (Folk-Lore Tales), XV (Conclusions). yor00 (Title) and yor01 (Contents) are
# front-matter — drop or apparatus-reject.
label = "The Yoruba-Speaking Peoples (Ellis)"
url = "https://sacred-texts.com/afr/yor/index.htm"
format = "html_multi"
license = "public_domain"
translator = "A.B. Ellis"
notes = "Ellis 1894 (Chapman & Hall). Clean PD. Chapters on the orisha pantheon (II), minor gods (III), Egungun/Oro/Abiku (VI), in-dwelling spirits (VII), and folk-lore tales (XIV) carry the highest cross-tradition density. NOTE: sacred-texts' archive of this title appears to omit Chapters X-XII (file numbering jumps from yor10=Ch.IX to yor11=Ch.XIII). Ethnography rather than scripture — tag accordingly. Chunk paragraph-group within chapters."
 
 
# ============================================
# FINNIC (Kalevala)
# ============================================
# The Finnish national epic — Lonnrot's 1849 compilation of Karelian/
# Finnish/Ingrian oral folk-song. Self-collected indigenous tradition,
# not outsider ethnography: clean provenance. Saturated with sung magic
# (the "witch-songs" / incantation layer is the oldest stratum), a
# cosmic-egg creation myth, and the word-as-power motif (Vainamoinen
# wins by knowing the true origin-words of things) — strong edges to
# the logos/naming material in the Hermetica and the rune-charm
# catalogue in Hovamol. Crawford 1888, the first English translation;
# explicitly "Public domain in the USA." Single-file HTML, 50 Runos.
 
[[source]]
id = "kalevala"
tradition = "finnic"
# VERIFIED 2026-05-31 — URL resolves (HTTP 200, ~1.1MB gzipped, ~3MB inflated).
# Crawford translator confirmed via <meta name="MARCREL.trl">. RUNE I..L
# table-of-contents confirmed. Note: response is served gzipped; acquire.py
# must request with Accept-Encoding: gzip or the body will be unreadable
# binary — check that the downloader sets `--compressed` / requests' default
# automatic decompression (it does).
label = "The Kalevala (Crawford)"
url = "https://www.gutenberg.org/cache/epub/5186/pg5186.html"
format = "html"
license = "public_domain"
translator = "John Martin Crawford"
notes = "Lonnrot comp. 1849; Crawford tr. 1888 (the first English version). Gutenberg #5186, single-file HTML. Structured as PROEM + RUNE I-L (Roman-numeral canto headings). Chunk regex-section-split on '^RUNE ([IVXLC]+)\\.'. Strip Gutenberg header/license boilerplate and the back-matter (glossary, pronunciation notes) before chunking."
 
 
# ============================================
# CELTIC (Welsh primary)
# ============================================
# The Mabinogion is the clean primary anchor: a medieval Welsh
# manuscript tradition (Red Book of Hergest), Lady Guest's translation
# working from the actual MS, not a reconstruction. The four branches
# proper are pre-Christian in substance — the pagan British pantheon
# (Llyr, Bran, Branwen, Rhiannon, Pwyll, Math, Gwydion) under a light
# medieval-Christian veneer. Strong sovereignty-goddess and otherworld
# (Annwn) material.
# (Irish Mythological Cycle deliberately left unrepresented: no clean
# PD *primary* English translation exists — Macalister's Lebor Gabala
# is still in copyright, and the available syntheses (Rolleston/Squire)
# carry dated authorial framing.)
 
[[source]]
id = "mabinogion"
tradition = "celtic"
# VERIFIED 2026-05-31 — URL resolves (HTTP 200, ~650KB). <title>The Project
# Gutenberg eBook of The Mabinogion, by Lady Charlotte Guest</title>,
# <h1>THE MABINOGION</h1>, <h2>TRANSLATED BY LADY CHARLOTTE GUEST</h2>.
# Contents TOC and chapter anchors (#chap01..#chap13) confirmed.
label = "The Mabinogion (Lady Charlotte Guest)"
url = "https://www.gutenberg.org/files/5160/5160-h/5160-h.htm"
format = "html"
license = "public_domain"
translator = "Lady Charlotte Guest"
notes = "Guest tr. 1838-1849, from the Red Book of Hergest. Gutenberg #5160, single-file HTML. NOT numbered — 13 titled tales (Introduction, The Lady of the Fountain, Peredur, Geraint, Kilhwch and Olwen, The Dream of Rhonabwy, Pwyll, Branwen, Manawyddan, Math, Maxen Wledig, Lludd and Llevelys, Taliesin). Chunk on title-heading split, not numeric. The Four Branches (Pwyll/Branwen/Manawyddan/Math) carry the densest pagan-deity content. Guest's extensive footnotes are scholarly apparatus — treat as metadata."
