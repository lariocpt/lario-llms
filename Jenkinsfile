// lario-llms (lario-models-ci) model-control CI/deployment glue.
// Branch builds are test-only; deploy from main only.
// Python is NOT installed on the runner, so the model test suite runs INSIDE the
// built Python image (contract pattern: docker create with WORKDIR /w + docker cp
// of shared/ and the two tests into /w, then docker start -ai; the create command
// is the test runner, so start -ai streams output and its exit code is the real
// test result). PYTHONPATH=/w resolves shared.serving.*. No GPU, --network none,
// temp state only. The static web page is checked with the runner's node.
// Deploy from main: tag lario/model-control:<sha>, move the
// lario/model-control:deployed alias, and bring the infra model-control service up
// via deploy/jenkins-model-control.sh.

def BRANCH = sh(script: 'git rev-parse --abbrev-ref HEAD', returnStdout: true).trim()
def GIT_SHA = sh(script: 'git rev-parse --short=12 HEAD', returnStdout: true).trim()

pipeline {
    agent any
    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
        timeout(time: 30, unit: 'MINUTES')
    }
    environment {
        BRANCH = "${BRANCH}"
        GIT_SHA = "${GIT_SHA}"
    }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Build Docker image') {
            steps {
                sh 'docker build -f shared/serving/Dockerfile --pull -t lario/model-control:ci-test shared/serving'
            }
        }

        stage('Static web check (runner)') {
            steps {
                sh 'test -s shared/serving/web/index.html'
                sh 'node -e "const h=require(\"fs\").readFileSync(\"shared/serving/web/index.html\",\"utf8\"); if(!/<!doctype html>/i.test(h)) process.exit(1)"'
            }
        }

        stage('Model tests (built image)') {
            steps {
                // Contract pattern: create (WORKDIR /w) + cp shared/ and the two
                // tests into /w, then start -ai. PYTHONPATH=/w makes
                // shared.serving.* importable. No GPU, --network none, temp state only.
                sh 'docker create --name lario_model_ci --network none -w /w lario/model-control:ci-test sh -c "PYTHONPATH=/w python -m unittest -v tests.test_model_panel tests.test_model_client_control"'
                sh 'docker cp shared lario_model_ci:/w/shared'
                sh 'docker cp tests/test_model_panel.py lario_model_ci:/w/tests/test_model_panel.py'
                sh 'docker cp tests/test_model_client_control.py lario_model_ci:/w/tests/test_model_client_control.py'
                sh 'docker start -ai lario_model_ci'
            }
        }

        stage('Deploy (main only)') {
            when {
                expression { BRANCH == 'main' }
            }
            steps {
                // The infra model-control compose template lives in lario-home-infra;
                // fetch main into .infra via the github-pat credential (bound so the
                // PAT stays out of logs). The deploy script materializes a copy of
                // that template with the stable alias + an absolute config dir
                // injected (no HOME override), then brings the fixed service up.
                withCredentials([string(credentialsId: 'github-pat', variable: 'GITHUB_PAT')]) {
                    sh 'rm -rf .infra && git clone --branch main --single-branch --depth 1 https://x-access-token:${GITHUB_PAT}@github.com/lariocpt/lario-home-infra.git .infra'
                }
                sh 'deploy/jenkins-model-control.sh'
            }
        }
    }
    post {
        cleanup {
            sh 'docker rm -f lario_model_ci 2>/dev/null || true'
        }
    }
}
