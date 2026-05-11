#!/bin/bash
# Collect IDs using Chrome subprocess
BASE="https://www.onlinejobs.ph/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425"
OUT_DIR="/Users/aiserver/OPENCLAW BOT/ojp_progress"
mkdir -p "$OUT_DIR"

for i in {0..10}; do
    offset=$((i * 30))
    file="$OUT_DIR/page_$i.html"
    
    if [ -f "$file" ]; then
        echo "Page $i already saved"
        continue
    fi
    
    echo "Page $i..."
    curl -sL "${BASE}/${offset}" -A "Mozilla/5.0" > "$file"
    
    # Check if we got content
    if [ -s "$file" ]; then
        count=$(grep -o '/jobseekers/info/[0-9]*' "$file" | wc -l)
        echo "  -> $count IDs"
    else
        echo "  -> EMPTY"
        break
    fi
    
    sleep 1
done

echo "Done. Parsing collected pages..."

# Parse all HTML files into IDs
cd "$OUT_DIR"
grep -oh '/jobseekers/info/[0-9]*' page_*.html | sort -u | sed 's|.*/||' > all_ids.txt

echo "Total unique IDs: $(wc -l < all_ids.txt)"