#!/usr/bin/env bash
set -euo pipefail

INPUT_FILE="${ONEC_EXTERNAL_FILE:-}"
OUT_XML_DIR="${OUT_XML_DIR:-}"
LOG_FILE="${LOG_FILE:-${OUT_XML_DIR:-/tmp}/1cv8_unpack.log}"
ONEC_IB_EFFECTIVE="${ONEC_IB:-}"

die() { echo "error: $*" >&2; exit 1; }

find_1cv8() {
	if [[ -n "${ONEC_1CV8:-}" && -x "$ONEC_1CV8" ]]; then
		echo "$ONEC_1CV8"
		return 0
	fi
	local d b
	for d in /opt/1cv8/*; do
		[[ -d "$d" ]] || continue
		for b in "$d/1cv8" "$d"/{aarch64,x86_64,arm64}/1cv8; do
			if [[ -x "$b" ]]; then
				echo "$b"
				return 0
			fi
		done
	done
	return 1
}

[[ -n "$INPUT_FILE" ]] || die "set ONEC_EXTERNAL_FILE to an .epf or .erf file"
[[ -f "$INPUT_FILE" ]] || die "input file does not exist: $INPUT_FILE"
[[ -n "$OUT_XML_DIR" ]] || die "set OUT_XML_DIR to the output XML directory"
mkdir -p "$OUT_XML_DIR"

bin="$(find_1cv8)" || die "1cv8 not found; set ONEC_1CV8"

echo "==> 1cv8 CONFIG /DumpExternalDataProcessorOrReportToFiles"
echo "    input: $INPUT_FILE"
echo "    output dir: $OUT_XML_DIR"
echo "    log: $LOG_FILE"

if [[ -n "$ONEC_IB_EFFECTIVE" ]]; then
	"$bin" CONFIG /DisableStartupMessages /Visible false /F "$ONEC_IB_EFFECTIVE" \
		/DumpExternalDataProcessorOrReportToFiles "$INPUT_FILE" "$OUT_XML_DIR" \
		/Out "$LOG_FILE"
else
	"$bin" CONFIG /DisableStartupMessages /Visible false \
		/DumpExternalDataProcessorOrReportToFiles "$INPUT_FILE" "$OUT_XML_DIR" \
		/Out "$LOG_FILE"
fi
