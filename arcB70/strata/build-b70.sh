#!/usr/bin/env bash
# Build the pinned official source for B70; never replace the signed engine.
set -eo pipefail
source /opt/intel/oneapi/setvars.sh --force >/dev/null
set -u
strata_app_root=/home/lario/.local/share/strata
strata_source_revision=4b9e05a2a806a3fe24f7b2560d98626c37dade35
strata_ggml_revision=3cf03257f219afbe7334045ff7c6a06ac68c627d
strata_source_dir="$strata_app_root/source/$strata_source_revision"
strata_ggml_dir="$strata_app_root/source/llama.cpp-$strata_ggml_revision"
strata_build_dir="$strata_app_root/build/$strata_source_revision-b70"
python3 "$(dirname "$0")/build_deps.py"
export CPATH="$strata_app_root/build-deps/opt/intel/oneapi/mkl/2026.0/include:${CPATH:-}"
export LIBRARY_PATH="$strata_app_root/build-deps/lib:${LIBRARY_PATH:-}"
export LD_LIBRARY_PATH="$strata_app_root/components/engine/0.1.50-linux-x86_64-sycl:${LD_LIBRARY_PATH:-}"
test "$(git -C "$strata_source_dir" rev-parse HEAD)" = "$strata_source_revision"
test -z "$(git -C "$strata_source_dir" status --porcelain --untracked-files=no)"
if [[ ! -f "$strata_ggml_dir/.strata-source-revision" ]]; then
    mkdir -p "$strata_ggml_dir"
    curl --fail --location --retry 2 \
        "https://github.com/ggml-org/llama.cpp/archive/$strata_ggml_revision.tar.gz" \
        -o "$strata_app_root/source/llama.cpp-$strata_ggml_revision.tar.gz"
    tar -xzf "$strata_app_root/source/llama.cpp-$strata_ggml_revision.tar.gz" \
        --strip-components=1 -C "$strata_ggml_dir"
    echo "$strata_ggml_revision" > "$strata_ggml_dir/.strata-source-revision"
fi
test "$(cat "$strata_ggml_dir/.strata-source-revision")" = "$strata_ggml_revision"
cmake -S "$strata_source_dir/sycl" -B "$strata_build_dir" -G Ninja \
    -DCMAKE_C_COMPILER=icx -DCMAKE_CXX_COMPILER=icpx \
    -DSTRATA_SYCL_AOT=bmg-g31 -DSTRATA_SYCL_PARITY=ON \
    -DSTRATA_GGML_DIR="$strata_ggml_dir"
cmake --build "$strata_build_dir" --target strata -j 8
"$strata_build_dir/strata" --version
sha256sum "$strata_build_dir/strata"
touch "$strata_build_dir/.complete"
