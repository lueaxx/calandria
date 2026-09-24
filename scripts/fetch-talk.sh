#!/usr/bin/env bash
# Fetch a talk and convert it to the format Calandria ingests.
#
# The repository ships short synthetic clips rather than recordings of real
# talks, because a conference recording's licence is rarely compatible with
# redistributing it inside an Apache-2.0 repository. This script gets you a real
# talk locally, where that question does not arise.
#
#   ./scripts/fetch-talk.sh <url> [output.wav] [start] [duration]
#   ./scripts/fetch-talk.sh "https://youtube.com/watch?v=..." samples/talk.wav 120 300

set -euo pipefail

URL="${1:?usage: fetch-talk.sh <url> [output.wav] [start-seconds] [duration-seconds]}"
OUT="${2:-samples/talk.wav}"
START="${3:-0}"
DURATION="${4:-600}"

for tool in yt-dlp ffmpeg; do
  command -v "$tool" >/dev/null || {
    echo "error: $tool is not on PATH." >&2
    echo "  macOS:   brew install $tool" >&2
    echo "  Debian:  apt install $tool" >&2
    echo "  Windows: winget install $tool" >&2
    exit 1
  }
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading audio…"
yt-dlp -f bestaudio -x --audio-format wav \
       --download-sections "*${START}-$((START + DURATION))" \
       --ffmpeg-location "$(dirname "$(command -v ffmpeg)")" \
       -o "$TMP/raw.%(ext)s" "$URL"

echo "Converting to 16 kHz mono PCM…"
mkdir -p "$(dirname "$OUT")"
ffmpeg -y -loglevel error -i "$TMP/raw.wav" \
       -ac 1 -ar 16000 -sample_fmt s16 "$OUT"

echo
echo "Wrote $OUT"
echo "Point a session at it:"
echo
echo "  sessions:"
echo "    - id: talk"
echo "      source: { type: file, path: ./$OUT }"
echo "      source_language: en"
echo "      targets: [es]"
