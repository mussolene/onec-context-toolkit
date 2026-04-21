# 1C External Processor CLI Helpers

This directory contains neutral helper scripts for packaging and unpacking 1C
external data processors/reports from XML file trees.

No concrete external processor payload is stored here. Provide your own source
XML tree and output path through environment variables.

## Build

```bash
ONEC_1CV8=/opt/1cv8/8.3.xx.xxxx/x86_64/1cv8 \
ONEC_EXTERNAL_XML=/path/to/source/root.xml \
OUT_EPF=/path/to/output/tool.epf \
ONEC_IB=/path/to/file-ib \
./tools/1c/build_external_data_processor.sh
```

## Unpack

```bash
ONEC_1CV8=/opt/1cv8/8.3.xx.xxxx/x86_64/1cv8 \
ONEC_EXTERNAL_FILE=/path/to/input/tool.epf \
OUT_XML_DIR=/path/to/output/xml-tree \
ONEC_IB=/path/to/file-ib \
./tools/1c/unpack_external_data_processor.sh
```

For headless Linux runs, use a virtual display such as `xvfb-run` when the
platform build requires GUI libraries.
