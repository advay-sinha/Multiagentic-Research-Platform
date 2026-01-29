# CI/CD Pipeline Success Guide

This repository ships a Dockerfile at the repo root. Use the steps below to keep a CI/CD pipeline green and the service deployable.

## 1. Build the container image

```bash
docker build -t agentic-research-platform:ci .
```

## 2. Run automated tests

```bash
docker run --rm agentic-research-platform:ci pytest -q
```

## 3. Validate the container startup

```bash
docker run --rm -p 8000:8000 agentic-research-platform:ci
```

Then in another terminal (or CI health check), confirm the API responds:

```bash
curl http://localhost:8000/v1/health
```

## 4. Recommended CI/CD pipeline stages

1. **Checkout** source code.
2. **Build** the Docker image.
3. **Test** by running `pytest` in the container.
4. **Smoke test** the container and hit `/v1/health`.
5. **Publish** the image to your registry once steps 1–4 pass.
6. **Deploy** the published image to your target environment.

## 5. Common failure fixes

- **Dependency issues**: update `backend/requirements.txt` and re-run the build.
- **Test failures**: run `pytest -q` locally before pushing.
- **Port conflicts**: ensure your deploy target exposes port `8000`.

Following these steps ensures the pipeline validates builds, tests, and service availability before deployment.
