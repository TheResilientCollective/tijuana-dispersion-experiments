.PHONY: help docker-login docker-build docker-push docker-build-push docker-digest docker-clean docker-tags

# NRP worker image — build on Apple Silicon, push to the NRP GitLab registry.
#
# Credentials (read automatically from nrp/.env, no manual `source` needed):
#   GITLAB_USER, GITLAB_TOKEN   GitLab registry push (scopes: read_registry, write_registry)
# GH_TOKEN for the private tijuana-dispersion build dep is taken from `gh auth token`.
#
# Quick start:
#   make docker-build-push      # build (amd64) + login + push, all in one
#
# NRP requirement: --platform linux/amd64 (nodes are amd64; an Apple-Silicon
# arm64 image fails on-cluster with "no match for platform in manifest").

REGISTRY := gitlab-registry.nrp-nautilus.io
ORG      := ucsd-center4health
IMAGE    := nrp-worker

GIT_SHA := $(shell git rev-parse --short HEAD)

IMAGE_TAG_SHA := $(REGISTRY)/$(ORG)/$(IMAGE):$(GIT_SHA)
IMAGE_TAG_DEV := $(REGISTRY)/$(ORG)/$(IMAGE):dev

# Source GitLab creds from nrp/.env; resolve GH_TOKEN from gh if unset. Used as a
# prefix inside every recipe that talks to Docker so login + push share one shell
# (the Docker Desktop credential store is flaky across separate shells).
LOAD_ENV := set -a; . nrp/.env; set +a; export GH_TOKEN="$${GH_TOKEN:-$$(gh auth token 2>/dev/null)}";

help:
	@echo "NRP worker image — build + push to $(REGISTRY)"
	@echo ""
	@echo "  make docker-build-push   Build (amd64) + login + push  [most common]"
	@echo "  make docker-build        Build image only ($(GIT_SHA) + dev)"
	@echo "  make docker-push         Login + push existing image (no rebuild)"
	@echo "  make docker-login        Authenticate to the registry"
	@echo "  make docker-digest       Print pushed image digest (for DAGSTER_IMAGE)"
	@echo "  make docker-clean        Remove local image tags"
	@echo "  make docker-tags         Print the tag names (no build)"
	@echo ""
	@echo "  Tags:     $(IMAGE_TAG_SHA)"
	@echo "            $(IMAGE_TAG_DEV)"
	@echo "  Platform: linux/amd64 (required for NRP)"

docker-login:
	@bash -c '$(LOAD_ENV) \
		: "$${GITLAB_USER:?set GITLAB_USER in nrp/.env}"; \
		: "$${GITLAB_TOKEN:?set GITLAB_TOKEN in nrp/.env}"; \
		echo "Logging in to $(REGISTRY) as $$GITLAB_USER..."; \
		echo "$$GITLAB_TOKEN" | docker login $(REGISTRY) -u "$$GITLAB_USER" --password-stdin'

docker-build:
	@bash -c '$(LOAD_ENV) \
		: "$${GH_TOKEN:?no GH_TOKEN — run: gh auth login}"; \
		echo "Building $(IMAGE_TAG_SHA) (--platform linux/amd64)..."; \
		DOCKER_BUILDKIT=1 docker build \
			-f nrp/Dockerfile \
			--platform linux/amd64 \
			--target worker \
			--secret id=gh_token,env=GH_TOKEN \
			-t $(IMAGE_TAG_SHA) \
			-t $(IMAGE_TAG_DEV) \
			. ; \
		echo "Built + tagged: $(IMAGE_TAG_SHA) , :dev"'

# Login AND push in the SAME shell — the Docker Desktop keychain helper can drop
# a credential written by a prior shell ("context deadline exceeded"), which is
# what made earlier pushes silently fail. Does NOT rebuild; run docker-build first
# (or use docker-build-push).
docker-push:
	@bash -c '$(LOAD_ENV) \
		: "$${GITLAB_USER:?set GITLAB_USER in nrp/.env}"; \
		: "$${GITLAB_TOKEN:?set GITLAB_TOKEN in nrp/.env}"; \
		if ! docker image inspect $(IMAGE_TAG_SHA) >/dev/null 2>&1; then \
			echo "✗ $(IMAGE_TAG_SHA) not built yet — run: make docker-build"; exit 1; \
		fi; \
		echo "$$GITLAB_TOKEN" | docker login $(REGISTRY) -u "$$GITLAB_USER" --password-stdin; \
		docker push $(IMAGE_TAG_SHA); \
		docker push $(IMAGE_TAG_DEV); \
		echo "✓ Pushed $(IMAGE_TAG_SHA) and :dev"; \
		echo "  Pin the digest for Helm/.env:"; \
		echo "  DAGSTER_IMAGE=$$(docker inspect --format='"'"'{{index .RepoDigests 0}}'"'"' $(IMAGE_TAG_SHA))"'

docker-build-push: docker-build docker-push

docker-digest:
	@docker inspect --format='{{index .RepoDigests 0}}' $(IMAGE_TAG_SHA)

docker-clean:
	@docker rmi -f $(IMAGE_TAG_SHA) $(IMAGE_TAG_DEV) 2>/dev/null || true
	@echo "✓ Removed local tags"

docker-tags:
	@echo "$(IMAGE_TAG_SHA)"
	@echo "$(IMAGE_TAG_DEV)"
