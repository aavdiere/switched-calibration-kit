#!/usr/bin/env bash
# Run the NTC heater sim and render all plots into build/
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p build

ngspice -b ntc_divider.cir

for ps in build/*.ps; do
    png="${ps%.ps}.png"
    gs -q -dBATCH -dNOPAUSE -sDEVICE=png16m -r150 -o "$png" "$ps"
done

echo "Done. Outputs in build/:"
ls build/
