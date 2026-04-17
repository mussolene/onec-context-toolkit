PYTHON ?= python3
HBK_BASE ?=
METADATA_SOURCE ?=
PLATFORMS ?=
CONFIG_VERSIONS ?=
CONFIG_SOURCE ?=
WORKSPACE_ROOT ?= .
SOURCE_KIND ?= auto
WITH_HELP ?=
WITH_FULL_PACK ?=

.PHONY: init status install-codex install-claude install-cursor kb-build-help kb-build-metadata kb-build-all config-pack code-pack verify benchmark export-skill export-skill-archive

init:
	$(PYTHON) scripts/init_workspace.py --workspace-root "$(WORKSPACE_ROOT)" --source-path "$(CONFIG_SOURCE)" --source-kind "$(SOURCE_KIND)" $(if $(METADATA_SOURCE),--metadata-source "$(METADATA_SOURCE)",) $(if $(HBK_BASE),--hbk-base "$(HBK_BASE)",) $(if $(PLATFORMS),$(foreach v,$(PLATFORMS),--platform $(v)),) $(if $(WITH_HELP),--with-help,) $(if $(WITH_FULL_PACK),--with-full-pack,)

status:
	$(PYTHON) scripts/status_workspace.py --workspace-root "$(WORKSPACE_ROOT)" $(if $(PLATFORMS),$(foreach v,$(PLATFORMS),--platform $(v)),)

install-codex:
	$(PYTHON) scripts/install_agent.py --agent codex

install-claude:
	$(PYTHON) scripts/install_agent.py --agent claude

install-cursor:
	$(PYTHON) scripts/install_agent.py --agent cursor --workspace "$(WORKSPACE_ROOT)"

kb-build-help:
	$(PYTHON) scripts/build_local_kb.py help $(if $(HBK_BASE),--hbk-base "$(HBK_BASE)",) $(if $(PLATFORMS),$(foreach v,$(PLATFORMS),--platform $(v)),)

kb-build-metadata:
	$(PYTHON) scripts/build_local_kb.py metadata $(if $(CONFIG_SOURCE),--config-source "$(CONFIG_SOURCE)",) $(if $(METADATA_SOURCE),--metadata-source "$(METADATA_SOURCE)",) $(if $(CONFIG_VERSIONS),$(foreach v,$(CONFIG_VERSIONS),--config-version $(v)),)

kb-build-all:
	$(PYTHON) scripts/build_local_kb.py all $(if $(HBK_BASE),--hbk-base "$(HBK_BASE)",) $(if $(CONFIG_SOURCE),--config-source "$(CONFIG_SOURCE)",) $(if $(METADATA_SOURCE),--metadata-source "$(METADATA_SOURCE)",) $(if $(PLATFORMS),$(foreach v,$(PLATFORMS),--platform $(v)),) $(if $(CONFIG_VERSIONS),$(foreach v,$(CONFIG_VERSIONS),--config-version $(v)),)

config-pack:
	$(PYTHON) scripts/build_config_pack.py $(if $(CONFIG_SOURCE),--source-dir "$(CONFIG_SOURCE)",)

code-pack:
	$(PYTHON) scripts/build_code_pack.py $(if $(CONFIG_SOURCE),--source-dir "$(CONFIG_SOURCE)",)

verify:
	$(PYTHON) tools/verify_local_kb.py $(if $(WORKSPACE_ROOT),--workspace-root "$(WORKSPACE_ROOT)",)

benchmark:
	$(PYTHON) tools/benchmark_local_kb.py $(if $(WORKSPACE_ROOT),--workspace-root "$(WORKSPACE_ROOT)",)

export-skill:
	$(PYTHON) scripts/export_skill_bundle.py --workspace-root "$(WORKSPACE_ROOT)"

export-skill-archive:
	$(PYTHON) scripts/export_skill_bundle.py --workspace-root "$(WORKSPACE_ROOT)" --archive
