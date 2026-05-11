#!/bin/bash
# Collect ALL 601K+ profile IDs using headless Chrome

BASE="https://www.onlinejobs.ph/employers/skillsearch/all/a181a603769c1f98ad927e7367c7aa5112147425"
OUT="/Users/aiserver/OPENCLAW BOT/ojp_progress/all_ids.json"
TOTAL=601598
PAGES=$((TOTAL / 30))  # ~20K pages

echo "=== Collecting ALL $TOTAL jobseekers ==="
echo "Pages to process: $PAGES"

rm -f /tmp/ojp_ids_*.tmp

# Process in batches
BATCH=100
for ((start=0; start<PAGES; start+=BATCH)); do
    end=$((start + BATCH - 1))
    [ $end -ge $PAGES ] && end=$((PAGES - 1))
    
    # Run parallel Chrome processes
    for i in $(seq $start $end); do
        offset=$((i * 30))
        (
            /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
                --headless \
                --disable-gpu \
                --dump-dom \
                "${BASE}/${offset}" \
                2>/dev/null | grep -o '/jobseekers/info/[0-9]*' >> /tmp/ojp_ids_$i.tmp
        ) &
    done
    
    wait
    
    # Merge batch
    for i in $(seq $start $end); do
        cat /tmp/ojp_ids_$i.tmp 2>/dev/null
        rm /tmp/ojp_ids_$i.tmp
    done > /tmp/ojp_batch_$start.tmp
    
    count=$(sort -u /tmp/ojp_batch_$start.tmp | wc -l)
    echo "Batch $start-$end: $count unique IDs"
    
    # Append to total
    cat /tmp/ojp_batch_$start.tmp >> /tmp/ojp_all.tmp
    rm /tmp/ojp_batch_$start.tmp
    
    # Progress
    total_unique=$(sort -u /tmp/ojp_all.tmp | wc -l)
    echo "Total: $total_unique unique IDs (page $end of $PAGES)"
done

# Final dedupe
sort -u /tmp/ojp_all.tmp | sed 's|.*/||' > "${OUT%.json}.txt"
echo "=== DONE ==="
echo "Total unique IDs: $(wc -l < "${OUT%.json}.txt")"