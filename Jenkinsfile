pipeline {
  agent any
  options { disableConcurrentBuilds(); timeout(time: 30, unit: 'MINUTES'); buildDiscarder(logRotator(numToKeepStr: '20')) }
  parameters { string(name: 'BRANCH', defaultValue: 'main'); booleanParam(name: 'DEPLOY', defaultValue: true) }
  stages {
    stage('Checkout') { steps { checkout scm; script {
      env.SOURCE_BRANCH = params.BRANCH
      env.IMAGE = 'lario/model-control:' + sh(script: 'git rev-parse HEAD', returnStdout: true).trim()
      env.TEST_CONTAINER = 'lario-model-control-test-' + env.BUILD_NUMBER
    } } }
    stage('Build') { steps { sh 'docker build --pull -t "$IMAGE" -f shared/serving/Dockerfile shared/serving' } }
    stage('Test') { steps { sh """#!/bin/sh
set -eu
node --check shared/serving/web/app.js
docker create --name "$TEST_CONTAINER" --network none -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/w -w /w "$IMAGE" sh -ec 'python -m unittest discover -s tests -p test_model_panel.py -q; python -m unittest discover -s tests -p test_model_client_control.py -q; test -s /app/web/index.html'
for src in shared tests; do docker cp "\$src" "$TEST_CONTAINER:/w/\$src"; done
docker start -ai "$TEST_CONTAINER"
docker rm "$TEST_CONTAINER"
docker create --name "$TEST_CONTAINER" --network none -w /w "$IMAGE" true
docker cp docs "$TEST_CONTAINER:/w/docs" 2>/dev/null || test 'model-control' = model-control
docker start -ai "$TEST_CONTAINER"
""" } }
    stage('Deploy main') {
      when { expression { params.DEPLOY && params.BRANCH == 'main' } }
      steps {
        dir('.infra') { checkout([$class: 'GitSCM', branches: [[name: '*/main']], userRemoteConfigs: [[url: 'https://github.com/lariocpt/lario-home-infra.git', credentialsId: 'github-pat']]]) }
        sh 'bash deploy/jenkins-model-control.sh'
      }
    }
  }
  post { always { sh 'if [ -n "${TEST_CONTAINER:-}" ]; then docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true; fi' } }
}
