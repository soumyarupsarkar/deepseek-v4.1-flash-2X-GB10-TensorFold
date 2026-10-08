FROM nvcr.io/nvidia/pytorch@sha256:7531d90bcbe0e43e1f7363029c7e145ce90eebeb494a7b4695fdba0329d7c3c3
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision=$SOURCE_REVISION
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TENSORFOLD_NO_UPDATE_CHECK=1 HF_HUB_OFFLINE=1 \
    TORCH_EXTENSIONS_DIR=/cache/torch_extensions TRITON_CACHE_DIR=/cache/triton \
    CUDA_CACHE_PATH=/cache/nv/ComputeCache XDG_CACHE_HOME=/cache
COPY engine/deployment/config/requirements-resolved.txt /tmp/requirements-baseline.txt
RUN test -f /usr/include/infiniband/verbs.h || (apt-get update \
    && apt-get install -y --no-install-recommends libibverbs-dev ibverbs-providers \
    && rm -rf /var/lib/apt/lists/*)
RUN python -c "from pathlib import Path; Path('/tmp/constraints.txt').write_text(''.join(line for line in Path('/tmp/requirements-baseline.txt').read_text().splitlines(keepends=True) if '==' in line and ' @ ' not in line))" \
    && python -c "import torch; print(torch.__version__)" > /tmp/torch-before \
    && pip install --no-deps -c /tmp/constraints.txt xgrammar==0.2.8 \
    && pip install -c /tmp/constraints.txt transformers==5.17.0 'Pillow>=10' 'av>=12' 'pytest>=8' jsonschema \
    && python -c "import torch, xgrammar, transformers, PIL; assert torch.__version__ == open('/tmp/torch-before').read().strip()"
COPY engine /opt/tensorfold
RUN pip install --no-deps /opt/tensorfold \
    && python -c "import tensorfold, torch, triton, safetensors, jinja2, numpy; print(tensorfold.__version__, torch.__version__)" \
    && pip freeze > /opt/requirements-resolved.txt
ENTRYPOINT ["python", "-m", "tensorfold"]
