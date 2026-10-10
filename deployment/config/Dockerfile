FROM nvcr.io/nvidia/pytorch@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3 AS builder
ENV ZIG_GLOBAL_CACHE_DIR=/build/global
COPY engine /src
RUN python3 /src/deployment/scripts/build_native.py

FROM nvcr.io/nvidia/pytorch@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 TENSORFOLD_NO_UPDATE_CHECK=1 TENSORFOLD_NO_LIVE=1 \
    CUDA_CACHE_PATH=/cache/nv/ComputeCache XDG_CACHE_HOME=/cache
# Python is used for offline token-map preparation and upstream's bounded Pillow
# image-codec helper. Inference, scheduling and sampling run natively.
RUN pip install --no-deps tokenizers==0.23.1 pillow==12.3.0
COPY --from=builder /build/out/bin /opt/tensorfold/bin
COPY --from=builder /build/grammar/out/lib /opt/tensorfold/lib
COPY engine /opt/tensorfold/source
RUN /opt/tensorfold/bin/tensorfold-native capabilities --json \
    && python3 -c "import tokenizers, PIL; print(tokenizers.__version__, PIL.__version__)" \
    && pip freeze > /opt/requirements-resolved.txt
ENTRYPOINT ["/opt/tensorfold/bin/tensorfold-native"]
