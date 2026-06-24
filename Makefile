.PHONY: help docker-login docker-build docker-push docker-clean docker-build-push docker-tags

# GitLab registry authentication.
# Option 1 (interactive): make docker-login
# Option 2 (env vars):   GITLAB_USERNAME=<user> GITLAB_TOKEN=<pat> make docker-push
#   where <pat> is a GitLab personal access token with 'write_registry' scope
# Option 3 (cached):     docker login gitlab-registry.nrp-nautilus.io (once; cached in ~/.docker/config.json)

# NRP container repository
REGISTRY := gitlab-registry.nrp-nautilus.io
ORG := ucsd-center4health
IMAGE := nrp-worker

# Git commit for versioning
GIT_SHA := $(shell git rev-parse --short HEAD)
GIT_BRANCH := $(shell git rev-parse --abbrev-ref HEAD)

# Image tags: commit SHA + dev
IMAGE_TAG_SHA := $(REGISTRY)/$(ORG)/$(IMAGE):$(GIT_SHA)
IMAGE_TAG_DEV := $(REGISTRY)/$(ORG)/$(IMAGE):dev

# Default: show help
help:
	@echo "NRP Docker build targets:"
	@echo "  make docker-login     Login to GitLab registry"
	@echo "  make docker-build     Build image (tags: $(GIT_SHA), dev)"
	@echo "  make docker-push      Push to GitLab registry (requires auth)"
	@echo "  make docker-build-push  Build and push (same command)"
	@echo "  make docker-clean     Remove local images"
	@echo "  make docker-tags      Show image tags (no build)"
	@echo ""
	@echo "Environment:"
	@echo "  Registry: $(REGISTRY)"
	@echo "  Organization: $(ORG)"
	@echo "  Image: $(IMAGE)"
	@echo "  Git SHA: $(GIT_SHA)"
	@echo "  Branch: $(GIT_BRANCH)"

# Login to GitLab container registry.
# Uses GITLAB_USERNAME and GITLAB_TOKEN env vars if set; otherwise prompts interactively.
docker-login:
	@if [ -z "$(GITLAB_USERNAME)" ] || [ -z "$(GITLAB_TOKEN)" ]; then \
		echo "Logging into $(REGISTRY)..."; \
		docker login $(REGISTRY); \
	else \
		echo "Using GITLAB_USERNAME and GITLAB_TOKEN env vars..."; \
		echo "$(GITLAB_TOKEN)" | docker login -u "$(GITLAB_USERNAME)" --password-stdin $(REGISTRY); \
	fi
	@echo "✓ Logged in to $(REGISTRY)"

# Build the NRP worker image with BuildKit (required for --mount=type=secret).
# Requires GH_TOKEN env var for accessing private tijuana-dispersion repo.
docker-build:
	@echo "Building $(IMAGE_TAG_SHA)..."
	DOCKER_BUILDKIT=1 docker build \
		-f nrp/Dockerfile \
		--secret id=gh_token,env=GH_TOKEN \
		-t $(IMAGE_TAG_SHA) \
		-t $(IMAGE_TAG_DEV) \
		.
	@echo "✓ Built: $(IMAGE_TAG_SHA)"
	@echo "✓ Tagged: $(IMAGE_TAG_DEV)"

# Push both tags to GitLab registry.
# Ensures login before pushing.
docker-push: docker-build docker-login
	@echo "Pushing $(IMAGE_TAG_SHA) to $(REGISTRY)..."
	docker push $(IMAGE_TAG_SHA)
	@echo "Pushing $(IMAGE_TAG_DEV) to $(REGISTRY)..."
	docker push $(IMAGE_TAG_DEV)
	@echo "✓ Pushed to $(REGISTRY)/$(ORG)/$(IMAGE)"

# Build and push in one command.
docker-build-push: docker-push

# Clean up local images.
docker-clean:
	@echo "Removing local images..."
	docker rmi -f $(IMAGE_TAG_SHA) $(IMAGE_TAG_DEV) 2>/dev/null || true
	@echo "✓ Cleaned"

# Show current tags without building.
docker-tags:
	@echo "Image tags (ready to build):"
	@echo "  SHA: $(IMAGE_TAG_SHA)"
	@echo "  DEV: $(IMAGE_TAG_DEV)"
