.PHONY: help docker-login docker-build docker-push docker-clean docker-build-push docker-tags docker-digest

# GitLab registry authentication — NRP-specific setup.
# Prerequisites:
#   1. source nrp/env.sh          (loads GITLAB_USER, GITLAB_TOKEN, GH_TOKEN)
#   2. make docker-login          (authenticate to registry)
#   3. make docker-push           (build + push to gitlab-registry.nrp-nautilus.io)
#
# NRP requirement: builds use --platform linux/amd64 (NRP nodes are amd64;
# Apple Silicon builds arm64 without this, which fails on NRP).

REGISTRY := gitlab-registry.nrp-nautilus.io
ORG := ucsd-center4health
IMAGE := nrp-worker

# Git commit for versioning
GIT_SHA := $(shell git rev-parse --short HEAD)
GIT_BRANCH := $(shell git rev-parse --abbrev-ref HEAD)

# Image tags: commit SHA + dev
IMAGE_TAG_SHA := $(REGISTRY)/$(ORG)/$(IMAGE):$(GIT_SHA)
IMAGE_TAG_DEV := $(REGISTRY)/$(ORG)/$(IMAGE):dev

help:
	@echo "NRP Docker build + push (GitLab registry)"
	@echo ""
	@echo "Setup (one-time):"
	@echo "  source nrp/env.sh              Load GitLab creds + GH token"
	@echo ""
	@echo "Build & push:"
	@echo "  make docker-login              Authenticate to $(REGISTRY)"
	@echo "  make docker-build              Build image ($(GIT_SHA), dev)"
	@echo "  make docker-push               Build + push both tags"
	@echo "  make docker-build-push         Alias for docker-push"
	@echo "  make docker-digest             Show digest after push"
	@echo ""
	@echo "Cleanup:"
	@echo "  make docker-clean              Remove local images"
	@echo "  make docker-tags               Show image tags (no build)"
	@echo ""
	@echo "NRP environment:"
	@echo "  Registry: $(REGISTRY)"
	@echo "  Organization: $(ORG)"
	@echo "  Image: $(IMAGE)"
	@echo "  Git SHA: $(GIT_SHA)"
	@echo "  Platform: linux/amd64 (required for NRP)"

docker-login:
	@if [ -z "$(GITLAB_USER)" ] || [ -z "$(GITLAB_TOKEN)" ]; then \
		echo "❌ GITLAB_USER or GITLAB_TOKEN not set"; \
		echo "   Run: source nrp/env.sh"; \
		exit 1; \
	fi
	@echo "Logging into $(REGISTRY)..."
	@echo "$(GITLAB_TOKEN)" | docker login -u "$(GITLAB_USER)" --password-stdin $(REGISTRY)
	@echo "✓ Logged in"

docker-build:
	@if [ -z "$(GH_TOKEN)" ]; then \
		echo "❌ GH_TOKEN not set (needed for private tijuana-dispersion dep)"; \
		echo "   Run: source nrp/env.sh"; \
		exit 1; \
	fi
	@echo "Building $(IMAGE_TAG_SHA) (--platform linux/amd64)..."
	DOCKER_BUILDKIT=1 docker build \
		-f nrp/Dockerfile \
		--platform linux/amd64 \
		--target worker \
		--secret id=gh_token,env=GH_TOKEN \
		-t $(IMAGE_TAG_SHA) \
		-t $(IMAGE_TAG_DEV) \
		.
	@echo "✓ Built: $(IMAGE_TAG_SHA)"
	@echo "✓ Tagged: $(IMAGE_TAG_DEV)"

docker-push: docker-build docker-login
	@echo "Pushing $(IMAGE_TAG_SHA)..."
	docker push $(IMAGE_TAG_SHA)
	@echo "Pushing $(IMAGE_TAG_DEV)..."
	docker push $(IMAGE_TAG_DEV)
	@echo "✓ Pushed to $(REGISTRY)/$(ORG)/$(IMAGE)"
	@echo ""
	@echo "📌 Next: capture the digest for DAGSTER_IMAGE:"
	@echo "   export DAGSTER_IMAGE=$$(docker inspect --format='{{index .RepoDigests 0}}' $(IMAGE_TAG_SHA))"

docker-build-push: docker-push

docker-digest:
	@echo "Digest for $(IMAGE_TAG_SHA):"
	@docker inspect --format='{{index .RepoDigests 0}}' $(IMAGE_TAG_SHA)

docker-clean:
	@echo "Removing local images..."
	docker rmi -f $(IMAGE_TAG_SHA) $(IMAGE_TAG_DEV) 2>/dev/null || true
	@echo "✓ Cleaned"

docker-tags:
	@echo "Image tags (ready to build):"
	@echo "  SHA: $(IMAGE_TAG_SHA)"
	@echo "  DEV: $(IMAGE_TAG_DEV)"
