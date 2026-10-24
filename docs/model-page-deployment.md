# Model page deployment

The root Jenkinsfile builds and tests only the model-control web image from `shared/serving`. It does not deploy model backends, gateways, agents or OpenCode settings.

Register the `lario-model-control` job from `lario-home-infra/jenkins/jobs/lario-model-control.xml`. `BRANCH` defaults to `main`; `DEPLOY=false` performs build and tests only. Deployment requires `BRANCH=main`, successful checks, and the tested immutable Git-SHA image. Infrastructure main is checked out through Jenkins SCM credential `github-pat`; no PAT is placed in a Git URL.

Production Compose is owned by `lario-home-infra/containers/personal/model-control/docker-compose.yml`. Its stable image alias is `lario/model-control:deployed`; explicit private configuration paths and existing XFS state remain in place. Compose recreates only `model-control` with `--no-build --no-deps`. There is no unconditional container removal.

Health checks require `/login` HTTP 200 and unauthenticated `/api/state` HTTP 401. Compose or health failure restores the previous image alias and recreates this service, then fails the build. SQLite is never rolled back or copied. A failed first deployment without a previous image is stopped.

Validation: Jenkins live declarative validator passed; seven panel tests and three client-control tests passed in the built image with network disabled. Deployment success, Compose failure, health failure and first-deploy failure were exercised with a fake Docker executable. Live deployment remains a separate integration check.
