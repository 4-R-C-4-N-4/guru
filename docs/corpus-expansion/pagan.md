# ============================================================
# Guru Corpus — Source Manifest ADDITIONS (this session)
# Append to sources/manifest.toml
# Originally drafted with 7 sources across 6 new traditions; 5 of those
# 7 landed in sources/manifest.toml. The other two were CUT after
# review — see docs/corpus-expansion-candidates.md §0.2 for the
# editorial principle. Cut entries are kept here for the historical
# record of what was considered, with REMOVED markers.
# ============================================================
 
 
# ============================================
# CONTEMPORARY PAGAN / WITCHCRAFT — REMOVED 2026-06-05 (see commit 395bcae)
# ============================================
# REMOVED on the same editorial principle that cut Yoruba on 2026-06-04
# (see corpus-expansion-candidates.md §0.2): outsider voice on a
# subaltern tradition, with the would-be informant centering
# (Maddalena) itself disputed by modern scholarship (Hutton, Mathiesen).
# Leland was an American man of English descent paying an Italian
# peasant woman to "extract" lore he then framed and published. The
# 1899 PD status was clean; the cut is editorial, not legal. There is
# no clean PD insider-perspective alternative for modern witchcraft —
# the slug stays unrepresented rather than misrepresented.
#
# Original draft preserved below for historical record.
#
# [original notes: foundational "discovered scripture" of modern
# witchcraft revival; Diana/Lucifer/Aradia emanation myth; cross-
# tradition edges to Gnostic Lucifer-as-light-bringer and Mesopotamian
# descent material; authenticity disputed (Hutton's three theories);
# 1899 folklore artifact + foundational Wicca text, not authentic
# ancient survival]
 
# [[source]]
# id = "aradia-gospel-witches"
# tradition = "pagan_witchcraft"
# # VERIFIED 2026-05-31 — index resolves; ara03.htm = "CHAPTER I — How Diana Gave
# # Birth to Aradia (Herodias)"; chapters run ara03..ara17 contiguously. ara00/01/02
# # are Title/Preface/Contents; ara18 is the Appendix.
# label = "Aradia, or the Gospel of the Witches (Leland)"
# url = "https://sacred-texts.com/pag/aradia/index.htm"
# format = "html_multi"
# license = "public_domain"
# translator = "Charles Godfrey Leland"
# notes = "Leland 1899 (David Nutt, London); author d. 1903, clean PD."
 
 
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
# YORUBA / WEST AFRICAN — REMOVED 2026-06-04 (see commit de21074)
# ============================================
# REMOVED on editorial grounds — the source's framing is outsider-
# colonial (Ellis was a British colonial officer in West Africa), uses
# patronizing register ("primitive"/"fetish"), and offers no informant
# centering. Citing it as a primary source for orisha cosmology would
# give the colonial gaze a voice the corpus shouldn't amplify. PD
# status was clean (1894 pre-1929); the cut is editorial, not legal.
#
# Insider-perspective sources for Yoruba/orisha religion (modern Lukumi
# writers, Bascom, Drewal, Awolalu) are all under copyright. The
# `yoruba` slug stays unrepresented until a clean PD insider source
# surfaces.
#
# This cut established the project-wide principle that later removed
# Aradia (above) — see corpus-expansion-candidates.md §0.2.
#
# Original draft preserved below for historical record.
#
# [original notes: Ellis 1894 "the unambiguously-PD anchor for Yoruba
# religion — orisha system, Ifa divination, Ife creation material;
# chapter pattern yor02..yor13 with X-XII omitted in the archive]
 
# [[source]]
# id = "yoruba-speaking-peoples-ellis"
# tradition = "yoruba"
# label = "The Yoruba-Speaking Peoples (Ellis)"
# url = "https://sacred-texts.com/afr/yor/index.htm"
# format = "html_multi"
# license = "public_domain"
# translator = "A.B. Ellis"
# notes = "Ellis 1894 (Chapman & Hall)."
 
 
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
