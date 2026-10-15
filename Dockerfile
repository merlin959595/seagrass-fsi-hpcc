# Seagrass FSI: Ubuntu 24.04 / linux-amd64
# Pinned application versions. This build intentionally fails on unresolved dependencies.
FROM --platform=linux/amd64 opencfd/openfoam-default:2512

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Install baseline developer and runtime dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl pkg-config make g++ gcc git \
    libarpack2 libblas3 liblapack3 libspooles2.2t64 \
    && rm -rf /var/lib/apt/lists/*

# Official preCICE and CalculiX adapter Debian packages for Ubuntu 24.04.
RUN curl -fL --retry 5 --retry-all-errors -o /tmp/libprecice3.deb \
    https://github.com/precice/precice/releases/download/v3.4.1/libprecice3_3.4.1_noble.deb \
    && curl -fL --retry 5 --retry-all-errors -o /tmp/calculix-precice3.deb \
    https://github.com/precice/calculix-adapter/releases/download/v2.20.2/calculix-precice3_2.20.2-1_amd64_noble.deb \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/libprecice3.deb /tmp/calculix-precice3.deb \
    && rm -f /tmp/libprecice3.deb /tmp/calculix-precice3.deb \
    && rm -rf /var/lib/apt/lists/*

# Build only the OpenFOAM adapter, not OpenFOAM itself.
RUN curl -fL --retry 5 --retry-all-errors \
    https://github.com/precice/openfoam-adapter/archive/refs/tags/v1.4.0.tar.gz \
    | tar -xz -C /opt

# Load OpenFOAM before enabling errexit: its optional feature probes can return 1.
RUN export WM_MPLIB=SYSTEMOPENMPI; \
    source /usr/lib/openfoam/openfoam2512/etc/bashrc; \
    set -e; \
    test "${WM_PROJECT_VERSION:-}" = v2512; \
    pkg-config --modversion libprecice; \
    command -v ccx_preCICE; \
    export PRECICE_OPENFOAM_TARGET_DIR="$FOAM_LIBBIN"; \
    cd /opt/openfoam-adapter-1.4.0; \
    ./Allwmake; \
    test -s "$FOAM_LIBBIN/libpreciceAdapterFunctionObject.so"; \
    ldd -r "$FOAM_LIBBIN/libpreciceAdapterFunctionObject.so" > /tmp/openfoam-adapter-ldd.txt; \
    ! grep -E '(not found|undefined symbol)' /tmp/openfoam-adapter-ldd.txt; \
    echo BUILD_AND_LINK_CHECK_OK

# Fail the build if the expected applications/libraries do not exist.
RUN export WM_MPLIB=SYSTEMOPENMPI; \
    source /usr/lib/openfoam/openfoam2512/etc/bashrc; \
    set -e; \
    command -v blockMesh; \
    command -v pimpleFoam; \
    command -v ccx_preCICE; \
    pkg-config --exists libprecice; \
    echo FSI_IMAGE_SMOKE_OK

# No scientific cases or secrets are baked into the image.
WORKDIR /work
