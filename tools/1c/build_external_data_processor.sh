#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SRC_DIR="${ONEC_EXTERNAL_SRC:-$SCRIPT_DIR}"
ROOT_XML="${ONEC_EXTERNAL_XML:-}"
OUT_EPF="${OUT_EPF:-$SCRIPT_DIR/external-data-processor.epf}"
LOG_FILE="${LOG_FILE:-${OUT_EPF%.epf}_1cv8_build.log}"
ONEC_IB_EFFECTIVE="${ONEC_IB:-}"
CREATED_TEMP_IB=0

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

cleanup_temp_ib() {
	if [[ "${ONEC_REMOVE_TEMP_IB:-0}" == "1" && "$CREATED_TEMP_IB" == "1" && -n "$ONEC_IB_EFFECTIVE" ]]; then
		rm -rf "${ONEC_IB_EFFECTIVE:?}"
	fi
}

create_temp_ib_if_needed() {
	local bin="$1"
	if [[ -n "$ONEC_IB_EFFECTIVE" || "${ONEC_AUTO_TEMP_IB:-0}" != "1" ]]; then
		return 0
	fi
	[[ -n "${ONEC_TEMPLATE:-}" ]] || die "ONEC_AUTO_TEMP_IB=1 requires ONEC_TEMPLATE (.cf or .dt)"
	local tib="${ONEC_TEMP_IB:-${TMPDIR:-/tmp}/onec-external-processor-$$/ib}"
	local parent dump_result create_log
	parent="$(dirname "$tib")"
	mkdir -p "$parent"
	[[ ! -e "$tib" ]] || die "temporary infobase already exists: $tib"
	dump_result="$parent/create_ib_DumpResult.txt"
	create_log="$parent/create_ib_Out.log"
	"$bin" CREATEINFOBASE "File=\"${tib}\";" /UseTemplate "$ONEC_TEMPLATE" /DumpResult "$dump_result" /Out "$create_log"
	python3 -c "import pathlib,sys; b=pathlib.Path(sys.argv[1]).read_bytes().lstrip(b'\\xef\\xbb\\xbf').strip(); sys.exit(0 if b==b'0' else 1)" "$dump_result" \
		|| die "CREATEINFOBASE failed; see $create_log and $dump_result"
	ONEC_IB_EFFECTIVE="$tib"
	CREATED_TEMP_IB=1
	trap cleanup_temp_ib EXIT
}

[[ -n "$ROOT_XML" ]] || die "set ONEC_EXTERNAL_XML to the root XML file"
[[ -f "$ROOT_XML" ]] || die "root XML file does not exist: $ROOT_XML"

bin="$(find_1cv8)" || die "1cv8 not found; set ONEC_1CV8"
create_temp_ib_if_needed "$bin"

echo "==> 1cv8 CONFIG /LoadExternalDataProcessorOrReportFromFiles"
echo "    source: $SRC_DIR"
echo "    root XML: $ROOT_XML"
echo "    output: $OUT_EPF"
echo "    log: $LOG_FILE"

if [[ -n "$ONEC_IB_EFFECTIVE" ]]; then
	"$bin" CONFIG /DisableStartupMessages /Visible false /F "$ONEC_IB_EFFECTIVE" \
		/LoadExternalDataProcessorOrReportFromFiles "$ROOT_XML" "$OUT_EPF" \
		/Out "$LOG_FILE"
else
	"$bin" CONFIG /DisableStartupMessages /Visible false \
		/LoadExternalDataProcessorOrReportFromFiles "$ROOT_XML" "$OUT_EPF" \
		/Out "$LOG_FILE"
fi

cleanup_temp_ib
trap - EXIT
