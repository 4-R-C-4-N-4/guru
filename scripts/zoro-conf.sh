#!/usr/bin/env bash
# Generates page-as-chunk configs for Yasna 28-53 (Gathas)
# Run from the guru-pipeline repo root.

set -euo pipefail

OUT_DIR="chunking/zoroastrianism"
mkdir -p "$OUT_DIR"

# Yasna chapter number -> roman numeral + Gatha name
# Yasna 52 is deliberately excluded (not Gathic material)
declare -A YASNAS=(
  [28]="XXVIII|Ahunavaiti Gatha"
  [29]="XXIX|Ahunavaiti Gatha"
  [30]="XXX|Ahunavaiti Gatha"
  [31]="XXXI|Ahunavaiti Gatha"
  [32]="XXXII|Ahunavaiti Gatha"
  [33]="XXXIII|Ahunavaiti Gatha"
  [34]="XXXIV|Ahunavaiti Gatha"
  [43]="XLIII|Ushtavaiti Gatha"
  [44]="XLIV|Ushtavaiti Gatha"
  [45]="XLV|Ushtavaiti Gatha"
  [46]="XLVI|Ushtavaiti Gatha"
  [47]="XLVII|Spenta Mainyu Gatha"
  [48]="XLVIII|Spenta Mainyu Gatha"
  [49]="XLIX|Spenta Mainyu Gatha"
  [50]="L|Spenta Mainyu Gatha"
  [51]="LI|Vohu Khshathra Gatha"
  [53]="LIII|Vahishtoishti Gatha"
)

for num in "${!YASNAS[@]}"; do
  IFS='|' read -r roman gatha <<< "${YASNAS[$num]}"
  config_path="${OUT_DIR}/yasna-${num}.toml"

  cat > "$config_path" <<EOF
# Auto-generated chunking config for Yasna ${roman}
# Source: sacred-texts.com SBE Vol. 31 (Mills, 1886)

[chunking]
strategy = "page-as-chunk"
section_label_format = "Yasna ${roman} (${gatha})"
max_tokens = 800

[metadata]
tradition = "Zoroastrianism"
text_name = "Avesta (Gathas)"
translator = "L.H. Mills"
sections_format = "yasna_chapter"
EOF

  echo "Wrote $config_path"
done

# Also generate config for the Mills introduction
cat > "${OUT_DIR}/gathas-introduction.toml" <<EOF
# Auto-generated chunking config for Mills' introduction to the Gathas

[chunking]
strategy = "page-as-chunk"
section_label_format = "Introduction to the Gathas"
max_tokens = 800

[metadata]
tradition = "Zoroastrianism"
text_name = "Avesta (Gathas)"
translator = "L.H. Mills"
sections_format = "introduction"
EOF

echo "Wrote ${OUT_DIR}/gathas-introduction.toml"
echo ""
echo "Done. Generated $(ls "${OUT_DIR}"/yasna-*.toml "${OUT_DIR}"/gathas-introduction.toml | wc -l) configs."
